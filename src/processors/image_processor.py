"""
图片处理器模块
负责图片下载、压缩和嵌入
"""

import io
import os
import threading
from typing import List, Tuple, Optional
from urllib.parse import urlparse
import httpx
from PIL import Image

from src.utils.logger import get_logger
from src.utils.safe_url import validate_url


class ImageProcessor:
    """图片处理器"""

    MAX_SIZE_KB = 600  # 单张图片最大大小（KB）- 提高以保留更多细节
    MAX_WIDTH = 1200  # 最大宽度 - 适配 modern Kindle (300 ppi) 和大屏阅读器
    MAX_HEIGHT = 1800  # 最大高度 - 适配常见阅读器视口
    MAX_DOWNLOAD_SIZE = 10 * 1024 * 1024  # 单张图片原始响应最大 10 MB
    JPEG_QUALITY = 88  # JPEG 质量 - 提高以获得更清晰的图片
    MIN_WIDTH = 120  # 最小宽度（过滤头像、图标、表情等装饰性小图）
    MIN_HEIGHT = 120  # 最小高度

    # --- 严格压缩模式（体积/数量超限时自动启用）---
    STRICT_MAX_SIZE_KB = 180
    STRICT_MAX_WIDTH = 800
    STRICT_MAX_HEIGHT = 1200
    STRICT_JPEG_QUALITY = 55

    # 触发严格压缩的阈值
    # 图片总大小超过该值（MB）或数量超过该值 → 自动严格压缩
    TRIGGER_TOTAL_MB = 25.0
    TRIGGER_IMAGE_COUNT = 150

    def __init__(self):
        """初始化图片处理器"""
        self.logger = get_logger()
        self.processed_images: List[Tuple[str, bytes]] = []  # (filename, data)
        self._lock = threading.Lock()

    def download_and_process(self, url: str, base_url: Optional[str] = None) -> Optional[Tuple[str, bytes]]:
        """
        下载并处理图片

        Args:
            url: 图片 URL
            base_url: 基础 URL（用于处理相对路径）

        Returns:
            Tuple[str, bytes]: (文件名, 图片数据)
        """
        try:
            # 处理相对 URL
            full_url = self._resolve_url(url, base_url)

            # 下载图片
            self.logger.debug(f"Downloading image: {full_url}")
            response = self._download_image(full_url, base_url=base_url)

            if not response:
                return None

            # 处理图片
            result = self._process_image(response, url)
            if not result:
                return None

            filename, image_data = result
            with self._lock:
                self.processed_images.append((filename, image_data))
            size_kb = len(image_data) / 1024
            self.logger.info(f"Successfully processed image: {filename} ({size_kb:.1f}KB) from {url}")
            return result

        except Exception as e:
            self.logger.error(f"Failed to process image {url}: {e}")
            return None

    def _resolve_url(self, url: str, base_url: Optional[str] = None) -> str:
        """
        解析 URL（处理相对路径）

        Args:
            url: 图片 URL
            base_url: 基础 URL

        Returns:
            str: 完整的 URL
        """
        from urllib.parse import urljoin
        
        if not base_url:
            if url.startswith('//'):
                return 'https:' + url
            return url
            
        return urljoin(base_url, url)

    def _download_image(self, url: str, base_url: Optional[str] = None) -> Optional[bytes]:
        """
        下载图片

        Args:
            url: 图片 URL
            base_url: 来源文章 URL，用于防盗链请求的 Referer
        Returns:
            Optional[bytes]: 图片数据
        """
        try:
            if not validate_url(url):
                self.logger.warning(f"Blocked unsafe image URL: {url}")
                return None

            headers = {
                "User-Agent": (
                    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                    "AppleWebKit/537.36 (KHTML, like Gecko) "
                    "Chrome/120.0.0.0 Safari/537.36"
                ),
                "Accept": "image/avif,image/webp,image/apng,image/svg+xml,image/*,*/*;q=0.8",
            }
            if base_url:
                parsed_base_url = urlparse(base_url)
                if parsed_base_url.scheme in ("http", "https") and parsed_base_url.netloc:
                    headers["Referer"] = base_url

            with httpx.Client(timeout=8, follow_redirects=False) as client:
                with client.stream("GET", url, headers=headers) as response:
                    response.raise_for_status()

                    content_length = response.headers.get("Content-Length")
                    if content_length:
                        try:
                            if int(content_length) > self.MAX_DOWNLOAD_SIZE:
                                self.logger.warning(f"Image exceeds download limit: {url}")
                                return None
                        except ValueError:
                            self.logger.warning(f"Invalid Content-Length for image: {url}")

                    chunks = []
                    total_size = 0
                    for chunk in response.iter_bytes():
                        total_size += len(chunk)
                        if total_size > self.MAX_DOWNLOAD_SIZE:
                            self.logger.warning(f"Image exceeds download limit: {url}")
                            return None
                        chunks.append(chunk)
                    return b"".join(chunks)

        except Exception as e:
            self.logger.error(f"Failed to download image from {url}: {e}")
            return None

    def _process_image(self, image_data: bytes, original_url: str) -> Optional[Tuple[str, bytes]]:
        """
        处理图片（压缩、转换格式）

        Args:
            image_data: 原始图片数据
            original_url: 原始 URL

        Returns:
            Tuple[str, bytes]: (文件名, 处理后的图片数据)
        """
        try:
            # 打开图片
            img = Image.open(io.BytesIO(image_data))

            # 跳过过小的图片（头像、图标、表情等装饰性小图）
            width, height = img.size
            if width < self.MIN_WIDTH or height < self.MIN_HEIGHT:
                self.logger.debug(f"Skipping small image ({width}x{height}): {original_url}")
                return None

            # 转换为 RGB：对透明/半透明像素，先以白色背景合成
            if img.mode in ('RGBA', 'LA', 'PA') or 'A' in img.mode:
                # 创建白色背景
                white_bg = Image.new('RGB', img.size, (255, 255, 255))
                if img.mode == 'RGBA':
                    # 使用 alpha 通道作为蒙版将图片合成到白色背景上
                    white_bg.paste(img, mask=img.split()[3])
                else:
                    # 其他带 alpha 的模式，先转 RGBA 再处理
                    img = img.convert('RGBA')
                    white_bg.paste(img, mask=img.split()[3])
                img = white_bg
            elif img.mode != 'RGB':
                img = img.convert('RGB')

            # 调整尺寸
            img = self._resize_image(img)

            # 压缩并转换为 JPEG
            compressed_data = self._compress_image(img)

            # 生成文件名
            filename = self._generate_filename(original_url)

            return (filename, compressed_data)

        except Exception as e:
            self.logger.error(f"Failed to process image: {e}")
            return None

    def _resize_image(
        self,
        img: Image.Image,
        max_width: int = None,
        max_height: int = None,
    ) -> Image.Image:
        """
        调整图片尺寸

        Args:
            img: PIL Image 对象
            max_width: 最大宽度
            max_height: 最大高度

        Returns:
            Image.Image: 调整后的图片
        """
        max_width = max_width if max_width is not None else self.MAX_WIDTH
        max_height = max_height if max_height is not None else self.MAX_HEIGHT

        width, height = img.size

        # 如果尺寸在限制内，不调整
        if width <= max_width and height <= max_height:
            return img

        # 计算缩放比例
        ratio = min(max_width / width, max_height / height)
        new_size = (int(width * ratio), int(height * ratio))

        # 调整尺寸（使用高质量重采样）
        return img.resize(new_size, Image.Resampling.LANCZOS)

    def _compress_image(
        self,
        img: Image.Image,
        max_size_kb: int = None,
        jpeg_quality: int = None,
    ) -> bytes:
        """
        压缩图片

        Args:
            img: PIL Image 对象
            max_size_kb: 最大大小（KB）
            jpeg_quality: JPEG 质量

        Returns:
            bytes: 压缩后的图片数据
        """
        max_size_kb = max_size_kb if max_size_kb is not None else self.MAX_SIZE_KB
        quality = jpeg_quality if jpeg_quality is not None else self.JPEG_QUALITY

        # 逐步降低质量，直到满足大小要求
        while quality >= 20:
            buffer = io.BytesIO()
            img.save(buffer, format='JPEG', quality=quality, optimize=True)
            data = buffer.getvalue()

            # 检查大小
            size_kb = len(data) / 1024
            if size_kb <= max_size_kb:
                return data

            # 降低质量
            quality -= 5

        # 如果仍然太大，进一步降低尺寸
        self.logger.warning("Image still too large after quality reduction, resizing further")
        width, height = img.size
        new_size = (int(width * 0.7), int(height * 0.7))
        img = img.resize(new_size, Image.Resampling.LANCZOS)

        buffer = io.BytesIO()
        # 维持在 25 左右画质，避免反弹回 40 导致体积再次超标
        img.save(buffer, format='JPEG', quality=max(quality, 25), optimize=True)
        return buffer.getvalue()

    def needs_strict_compression(self) -> bool:
        """图片总大小或数量超限时返回 True"""
        with self._lock:
            count = len(self.processed_images)
        total_mb = self.get_total_size_mb()
        return (
            total_mb > self.TRIGGER_TOTAL_MB
            or count > self.TRIGGER_IMAGE_COUNT
        )

    def recompress_all_strict(self) -> dict:
        """
        用严格参数重新压缩所有已处理图片。
        不重新下载，直接基于现有 JPEG 再压。

        Returns:
            dict: {filename: new_bytes}，便于调用方更新引用
        """
        mapping = {}
        with self._lock:
            new_list = []
            for filename, data in self.processed_images:
                try:
                    img = Image.open(io.BytesIO(data))
                    if img.mode != 'RGB':
                        img = img.convert('RGB')

                    img = self._resize_image(
                        img,
                        max_width=self.STRICT_MAX_WIDTH,
                        max_height=self.STRICT_MAX_HEIGHT,
                    )
                    new_data = self._compress_image(
                        img,
                        max_size_kb=self.STRICT_MAX_SIZE_KB,
                        jpeg_quality=self.STRICT_JPEG_QUALITY,
                    )
                    new_list.append((filename, new_data))
                    mapping[filename] = new_data

                    old_kb = len(data) / 1024
                    new_kb = len(new_data) / 1024
                    self.logger.info(
                        f"Strict recompress {filename}: {old_kb:.1f}KB → {new_kb:.1f}KB"
                    )
                except Exception as e:
                    self.logger.error(f"Strict recompress failed for {filename}: {e}")
                    new_list.append((filename, data))  # 失败则保留原图
                    mapping[filename] = data

            self.processed_images = new_list

        self.logger.info(
            f"Strict recompression done. Total images size: {self.get_total_size_mb():.2f} MB"
        )
        return mapping

    def _generate_filename(self, url: str) -> str:
        """
        生成文件名

        Args:
            url: 原始 URL

        Returns:
            str: 文件名
        """
        # 使用 URL 的哈希作为文件名
        import hashlib
        url_hash = hashlib.md5(url.encode('utf-8')).hexdigest()[:12]
        return f"image_{url_hash}.jpg"

    def get_total_size(self) -> int:
        """
        获取所有已处理图片的总大小

        Returns:
            int: 总大小（字节）
        """
        with self._lock:
            return sum(len(data) for _, data in self.processed_images)

    def get_total_size_mb(self) -> float:
        """
        获取所有已处理图片的总大小（MB）

        Returns:
            float: 总大小（MB）
        """
        return self.get_total_size() / (1024 * 1024)

    def clear(self):
        """清除已处理的图片"""
        with self._lock:
            self.processed_images.clear()
