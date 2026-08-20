"""
封面生成器模块
负责生成 EPUB 封面图片
"""

import io
import os
import platform
from typing import List, Optional, Tuple
from PIL import Image, ImageDraw, ImageFont
import httpx

from src.config import TitleConfig
from src.utils.logger import get_logger


class CoverGenerator:
    """封面生成器"""

    # 封面尺寸（3:4，匹配 Kindle 屏幕比例）
    WIDTH = 1440
    HEIGHT = 1920

    def __init__(self, title_config: TitleConfig):
        """
        初始化封面生成器

        Args:
            title_config: 标题配置
        """
        self.title_config = title_config
        self.logger = get_logger()

    def generate(self) -> Tuple[str, bytes]:
        """
        生成封面

        Returns:
            Tuple[str, bytes]: (文件名, 图片数据)
        """
        # 1. 获取背景图片
        background = self._get_background()

        # 2. 叠加文字
        cover = self._add_text_overlay(background)

        # 3. 转换为字节
        image_data = self._image_to_bytes(cover)

        return ("cover.jpg", image_data)

    def _get_background(self) -> Image.Image:
        """
        获取背景图片
        优先使用自定义图片，否则使用 Bing 壁纸

        Returns:
            Image.Image: 背景图片
        """
        # 1. 尝试使用自定义图片
        if self.title_config.img:
            self.logger.info(f"Using custom cover image: {self.title_config.img}")
            img = self._download_image(self.title_config.img)
            if img:
                return img

        # 2. 使用 Bing 壁纸
        self.logger.info("Fetching Bing daily wallpaper as cover")
        img = self._fetch_bing_wallpaper()
        if img:
            return img

        # 3. 创建纯色背景
        self.logger.warning("Failed to get cover image, using solid color background")
        return self._create_solid_background()

    def _fetch_bing_wallpaper(self) -> Optional[Image.Image]:
        """
        获取 Bing 每日壁纸

        Returns:
            Optional[Image.Image]: 壁纸图片
        """
        try:
            # Bing API
            api_url = "https://www.bing.com/HPImageArchive.aspx?format=js&idx=0&n=1&mkt=zh-CN"

            with httpx.Client(timeout=30, follow_redirects=True) as client:
                # 获取 JSON 数据
                response = client.get(api_url)
                response.raise_for_status()
                data = response.json()

                # 提取图片 URL
                if "images" in data and len(data["images"]) > 0:
                    relative_path = data["images"][0]["url"]
                    full_url = f"https://www.bing.com{relative_path}"

                    # 下载图片
                    return self._download_image(full_url)

        except Exception as e:
            self.logger.error(f"Failed to fetch Bing wallpaper: {e}")

        return None

    def _download_image(self, url: str) -> Optional[Image.Image]:
        """
        下载图片

        Args:
            url: 图片 URL

        Returns:
            Optional[Image.Image]: 图片对象
        """
        try:
            headers = {"User-Agent": "OughtGather/1.0"}

            with httpx.Client(timeout=30, follow_redirects=True) as client:
                response = client.get(url, headers=headers)
                response.raise_for_status()

                # 打开图片
                img = Image.open(io.BytesIO(response.content))

                # 转换为 RGB
                if img.mode != 'RGB':
                    img = img.convert('RGB')

                # 居中裁剪以适配套封面尺寸（而不是拉伸压缩）
                img = self._center_cover_crop(img, self.WIDTH, self.HEIGHT)

                return img

        except Exception as e:
            self.logger.error(f"Failed to download image from {url}: {e}")
            return None

    def _create_solid_background(self) -> Image.Image:
        """
        创建纯色背景

        Returns:
            Image.Image: 纯色背景图片
        """
        # 使用深蓝色背景
        img = Image.new('RGB', (self.WIDTH, self.HEIGHT), color=(30, 60, 120))
        return img

    def _add_text_overlay(self, background: Image.Image) -> Image.Image:
        """
        在背景上叠加文字

        Args:
            background: 背景图片

        Returns:
            Image.Image: 带文字的封面
        """
        # 添加浅白色的半透明蒙版以提升文字可读性
        overlay = Image.new('RGBA', (self.WIDTH, self.HEIGHT), (255, 255, 255, 33))  # 约 30% 透明度
        background = background.convert('RGBA')
        background = Image.alpha_composite(background, overlay)
        background = background.convert('RGB')

        # 创建可编辑的对象
        draw = ImageDraw.Draw(background)

        # 获取标题文本并处理换行
        title_text = self.title_config.get_display_text()
        lines = title_text.replace('</br>', '\n').split('\n')

        # 为每行文字计算合适的字体大小（自动适应）
        max_line_width = max(self.WIDTH * 0.9, 1200)  # 最大行宽（封面宽度的90%）
        max_total_height = self.HEIGHT * 0.4  # 最大总高度（封面高度的40%）

        # 估算每行的字体大小
        font_sizes = []
        for line in lines:
            font_size = self._calculate_font_size(draw, line, max_line_width)
            font_sizes.append(font_size)

        # 确保所有行使用相同的字体大小（取最小值）
        common_font_size = min(font_sizes) if font_sizes else 120

        # 加载字体（使用共同的字体大小）
        font = self._load_font(common_font_size, bold=True)

        # 计算每行的文字边界框
        line_heights = []
        line_widths = []
        for line in lines:
            bbox = draw.textbbox((0, 0), line, font=font)
            line_width = bbox[2] - bbox[0]
            line_height = bbox[3] - bbox[1]
            line_widths.append(line_width)
            line_heights.append(line_height)

        # 计算总高度（包含行间距）
        line_spacing = common_font_size * 0.3  # 行间距为字体大小的30%
        total_height = sum(line_heights) + (len(lines) - 1) * line_spacing

        # 计算起始Y位置（垂直居中）
        start_y = (self.HEIGHT - total_height) // 2

        # 绘制每行文字（带黑色边框）
        stroke_width = max(4, common_font_size // 15)  # 描边宽度，至少4像素

        for i, line in enumerate(lines):
            # 计算X位置（水平居中）
            x = (self.WIDTH - line_widths[i]) // 2

            # 计算Y位置
            y = start_y + sum(line_heights[:i]) + i * line_spacing

            # 绘制带描边的文字（黑色边框 + 白色文字）
            # PIL的text方法支持stroke参数来实现描边效果
            draw.text(
                (x, y),
                line,
                font=font,
                fill=(255, 255, 255),  # 白色文字
                stroke_width=stroke_width,
                stroke_fill=(0, 0, 0)  # 黑色边框
            )

        return background

    def _calculate_font_size(self, draw: ImageDraw.ImageDraw, text: str, max_width: float) -> int:
        """
        计算适合给定宽度的字体大小

        Args:
            draw: ImageDraw 对象
            text: 要绘制的文本
            max_width: 最大允许宽度

        Returns:
            int: 合适的字体大小
        """
        # 从大到小尝试字体大小
        for font_size in range(300, 40, -5):
            font = self._load_font(font_size, bold=True)
            bbox = draw.textbbox((0, 0), text, font=font)
            width = bbox[2] - bbox[0]

            if width <= max_width:
                return font_size

        # 如果文本太长，返回最小字体大小
        return 40

    def _get_cjk_font_candidates(self) -> List[str]:
        """
        获取支持中文的字体候选路径列表（按优先级排序）。
        按平台（macOS / Linux）提供不同候选。
        """
        system = platform.system()

        # 仓库内置字体候选（优先使用，避免依赖系统包）
        repo_fonts_dir = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..", "Fonts"))
        repo_candidates = [
            os.path.join(repo_fonts_dir, "wqy-microhei.ttc"),
            os.path.join(repo_fonts_dir, "wqy-zenhei.ttc"),
            os.path.join(repo_fonts_dir, "NotoSansSC-Bold.otf"),
            os.path.join(repo_fonts_dir, "NotoSansSC-Bold.ttf"),
            os.path.join(repo_fonts_dir, "NotoSansSC-Regular.otf"),
            os.path.join(repo_fonts_dir, "NotoSansSC-Regular.ttf"),
        ]

        # 通用 Linux 候选（GitHub Actions / Ubuntu）
        linux_candidates = [
            # Noto Sans CJK（需安装 fonts-noto-cjk-extra 或 fonts-noto-cjk）
            "/usr/share/fonts/opentype/noto/NotoSansCJK-Bold.ttc",
            "/usr/share/fonts/truetype/noto/NotoSansCJK-Bold.ttc",
            "/usr/share/fonts/opentype/noto/NotoSansCJK-Regular.ttc",
            "/usr/share/fonts/truetype/noto/NotoSansCJK-Regular.ttc",
            # WenQuanYi
            "/usr/share/fonts/truetype/wqy/wqy-zenhei.ttc",
            "/usr/share/fonts/truetype/wqy/wqy-microhei.ttc",
            # Droid
            "/usr/share/fonts/truetype/droid/DroidSansFallback.ttf",
        ]

        # macOS 候选
        macos_candidates = [
            "/System/Library/Fonts/PingFang.ttc",
            "/System/Library/Fonts/STHeiti Medium.ttc",
            "/System/Library/Fonts/STHeiti Light.ttc",
            "/Library/Fonts/Arial Unicode.ttf",
            "/System/Library/Fonts/Supplemental/Arial Unicode.ttf",
        ]

        # Windows 候选（本地开发）
        windows_candidates = [
            "C:/Windows/Fonts/msyh.ttc",   # 微软雅黑
            "C:/Windows/Fonts/msyhbd.ttc",  # 微软雅黑 Bold
            "C:/Windows/Fonts/simhei.ttf",  # 黑体
        ]

        if system == "Darwin":
            return repo_candidates + macos_candidates + linux_candidates
        elif system == "Windows":
            return repo_candidates + windows_candidates + linux_candidates
        else:
            return repo_candidates + linux_candidates

    def _load_font(self, size: int, bold: bool = False) -> ImageFont.FreeTypeFont:
        """
        加载支持中文的字体。依次尝试候选路径，首个可用即返回；
        全部失败则回退到 DejaVu（拉丁）→ Pillow 默认字体。
        """
        candidates = self._get_cjk_font_candidates()

        # bold 变体：在 Noto CJK 里 Bold/Regular 是不同文件，优先 Bold
        if not bold:
            candidates = [
                p.replace("-Bold.ttc", "-Regular.ttc").replace("-Bold.ttf", "-Regular.ttf")
                for p in candidates
            ]

        # 追加 DejaVu 作为非中文兜底（保持与原行为兼容）
        candidates += [
            "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf" if bold
            else "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf",
        ]

        for path in candidates:
            try:
                return ImageFont.truetype(path, size)
            except (OSError, IOError):
                continue

        # 最终回退
        self.logger.warning(
            "No CJK-capable font found; Chinese characters may render as boxes. "
            "Install fonts-noto-cjk-extra on Ubuntu or ensure a CJK font is available."
        )
        return ImageFont.load_default()

    @staticmethod
    def _center_cover_crop(img: Image.Image, target_w: int, target_h: int) -> Image.Image:
        """
        居中裁剪图片至目标宽高比（类似 CSS object-fit: cover），
        而非拉伸压缩。

        Args:
            img: 原始图片
            target_w: 目标宽度
            target_h: 目标高度

        Returns:
            Image.Image: 裁剪后的图片
        """
        src_w, src_h = img.size
        src_ratio = src_w / src_h
        target_ratio = target_w / target_h

        if src_ratio > target_ratio:
            # 源图更宽：以高度为基准，裁剪左右两侧
            new_h = src_h
            new_w = int(src_h * target_ratio)
        else:
            # 源图更高（或相等）：以宽度为基准，裁剪上下两侧
            new_w = src_w
            new_h = int(src_w / target_ratio)

        # 居中裁切
        left = (src_w - new_w) // 2
        top = (src_h - new_h) // 2
        img = img.crop((left, top, left + new_w, top + new_h))

        # 缩放到目标尺寸（仅缩放，不改变内容）
        return img.resize((target_w, target_h), Image.Resampling.LANCZOS)

    def _image_to_bytes(self, img: Image.Image) -> bytes:
        """
        将图片转换为字节

        Args:
            img: PIL Image 对象

        Returns:
            bytes: 图片数据
        """
        buffer = io.BytesIO()
        img.save(buffer, format='JPEG', quality=90, optimize=True)
        return buffer.getvalue()
