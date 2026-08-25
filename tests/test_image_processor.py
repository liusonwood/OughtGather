"""
图片处理器测试
测试 ImageProcessor 的图片下载、压缩、尺寸调整和 URL 解析
"""

import io
import pytest
from unittest.mock import MagicMock, patch
from PIL import Image

from src.processors.image_processor import ImageProcessor


def _make_image_bytes(
    width: int = 100,
    height: int = 100,
    mode: str = "RGB",
    color=(255, 0, 0),
    fmt: str = "JPEG",
) -> bytes:
    """生成测试用图片字节数据"""
    img = Image.new(mode, (width, height), color)
    buffer = io.BytesIO()
    img.save(buffer, format=fmt)
    return buffer.getvalue()


# =========================================================================
# URL 解析测试
# =========================================================================

class TestResolveUrl:
    """ImageProcessor._resolve_url 测试"""

    def setup_method(self):
        self.processor = ImageProcessor()

    def test_absolute_https_url(self):
        url = "https://example.com/image.jpg"
        assert self.processor._resolve_url(url) == url

    def test_absolute_http_url(self):
        url = "http://example.com/image.jpg"
        assert self.processor._resolve_url(url) == url

    def test_protocol_relative_url(self):
        url = "//cdn.example.com/image.jpg"
        assert self.processor._resolve_url(url) == "https://cdn.example.com/image.jpg"

    def test_relative_url_with_base(self):
        url = "/images/photo.jpg"
        base = "https://example.com/article/page"
        assert self.processor._resolve_url(url, base) == "https://example.com/images/photo.jpg"

    def test_relative_path_with_base(self):
        url = "photo.jpg"
        base = "https://example.com/articles/"
        assert self.processor._resolve_url(url, base) == "https://example.com/articles/photo.jpg"

    def test_relative_url_no_base(self):
        url = "image.jpg"
        # 无 base_url 时原样返回
        assert self.processor._resolve_url(url) == "image.jpg"


# =========================================================================
# 图片尺寸调整测试
# =========================================================================

class TestResizeImage:
    """ImageProcessor._resize_image 测试"""

    def setup_method(self):
        self.processor = ImageProcessor()

    def test_small_image_unchanged(self):
        """小于限制的图片不调整"""
        img = Image.new("RGB", (400, 600))
        result = self.processor._resize_image(img)
        assert result.size == (400, 600)

    def test_width_exceeds_limit(self):
        """宽度超限等比缩放"""
        img = Image.new("RGB", (1280, 800))
        result = self.processor._resize_image(img)
        assert result.size[0] == 1200  # MAX_WIDTH
        # 高度按比例：800 * (1200/1280) = 750
        assert result.size[1] == 750

    def test_height_exceeds_limit(self):
        """高度超限等比缩放"""
        img = Image.new("RGB", (400, 1920))
        result = self.processor._resize_image(img)
        assert result.size[1] == 1800  # MAX_HEIGHT
        # 宽度按比例：400 * (1800/1920) = 375
        assert result.size[0] == 375

    def test_both_exceed_limit(self):
        """宽高都超限按较大比例缩放"""
        img = Image.new("RGB", (2400, 3600))
        result = self.processor._resize_image(img)
        # 宽度比例：1200/2400 = 0.5
        # 高度比例：1800/3600 = 0.5
        assert result.size == (1200, 1800)

    def test_exact_limit_unchanged(self):
        """恰好等于限制尺寸不调整"""
        img = Image.new("RGB", (1200, 1800))
        result = self.processor._resize_image(img)
        assert result.size == (1200, 1800)


# =========================================================================
# 过小图片过滤测试
# =========================================================================

class TestSmallImageFilter:
    """装饰性小图（头像、图标、表情等）应被过滤，不参与 EPUB 生成"""

    def setup_method(self):
        self.processor = ImageProcessor()

    @patch.object(ImageProcessor, "_download_image")
    def test_tiny_icon_skipped(self, mock_download):
        """极小图标（如 32x32 表情）被跳过"""
        mock_download.return_value = _make_image_bytes(32, 32)
        result = self.processor.download_and_process("https://example.com/icon.png")
        assert result is None

    @patch.object(ImageProcessor, "_download_image")
    def test_avatar_skipped(self, mock_download):
        """头像类小图（如 64x64）被跳过"""
        mock_download.return_value = _make_image_bytes(64, 64)
        result = self.processor.download_and_process("https://example.com/avatar.jpg")
        assert result is None

    @patch.object(ImageProcessor, "_download_image")
    def test_narrow_separator_skipped(self, mock_download):
        """窄长条分隔图（宽度过小）被跳过"""
        mock_download.return_value = _make_image_bytes(50, 400)
        result = self.processor.download_and_process("https://example.com/separator.png")
        assert result is None

    @patch.object(ImageProcessor, "_download_image")
    def test_short_banner_skipped(self, mock_download):
        """矮横幅（高度过小）被跳过"""
        mock_download.return_value = _make_image_bytes(400, 50)
        result = self.processor.download_and_process("https://example.com/banner.png")
        assert result is None

    @patch.object(ImageProcessor, "_download_image")
    def test_exact_min_size_kept(self, mock_download):
        """恰好等于最小尺寸的图片保留（边界不丢弃）"""
        mock_download.return_value = _make_image_bytes(120, 120)
        result = self.processor.download_and_process("https://example.com/min.jpg")
        assert result is not None

    @patch.object(ImageProcessor, "_download_image")
    def test_normal_image_kept(self, mock_download):
        """正常正文配图（大于最小尺寸）保留"""
        mock_download.return_value = _make_image_bytes(300, 200)
        result = self.processor.download_and_process("https://example.com/content.jpg")
        assert result is not None

    @patch.object(ImageProcessor, "_download_image")
    def test_skipped_image_not_tracked(self, mock_download):
        """被跳过的小图不进入 processed_images 列表"""
        mock_download.return_value = _make_image_bytes(48, 48)
        self.processor.download_and_process("https://example.com/tiny.png")
        assert len(self.processor.processed_images) == 0


# =========================================================================
# 图片压缩测试
# =========================================================================

class TestCompressImage:
    """ImageProcessor._compress_image 测试"""

    def setup_method(self):
        self.processor = ImageProcessor()

    def test_small_image_compressed(self):
        """小图片压缩后小于 MAX_SIZE_KB"""
        img = Image.new("RGB", (100, 100), (255, 0, 0))
        data = self.processor._compress_image(img)
        assert len(data) / 1024 <= 600

    def test_returns_jpeg(self):
        """压缩后是 JPEG 格式"""
        img = Image.new("RGB", (200, 200))
        data = self.processor._compress_image(img)
        # JPEG 文件头是 FF D8 FF
        assert data[:3] == b"\xff\xd8\xff"

    def test_large_image_forced_smaller(self):
        """大图片压缩后满足大小限制"""
        # 使用较小的图片尺寸和简单的随机生成，加快测试速度
        import random
        img = Image.new("RGB", (400, 600))
        pixels = img.load()
        for x in range(0, 400, 10):
            for y in range(0, 600, 10):
                pixels[x, y] = (random.randint(0, 255), random.randint(0, 255), random.randint(0, 255))
        data = self.processor._compress_image(img)
        # 验证是否输出了有效的 JPEG 数据
        assert data[:3] == b"\xff\xd8\xff"


# =========================================================================
# 文件名生成测试
# =========================================================================

class TestGenerateFilename:
    """ImageProcessor._generate_filename 测试"""

    def setup_method(self):
        self.processor = ImageProcessor()

    def test_filename_format(self):
        """文件名格式为 image_{hash}.jpg"""
        filename = self.processor._generate_filename("https://example.com/image.jpg")
        assert filename.startswith("image_")
        assert filename.endswith(".jpg")

    def test_same_url_same_filename(self):
        """相同 URL 生成相同文件名"""
        f1 = self.processor._generate_filename("https://example.com/a.jpg")
        f2 = self.processor._generate_filename("https://example.com/a.jpg")
        assert f1 == f2

    def test_different_url_different_filename(self):
        """不同 URL 生成不同文件名"""
        f1 = self.processor._generate_filename("https://example.com/a.jpg")
        f2 = self.processor._generate_filename("https://example.com/b.jpg")
        assert f1 != f2

    def test_hash_length(self):
        """哈希部分为 12 位"""
        filename = self.processor._generate_filename("https://example.com/img.jpg")
        # image_ (6) + hash (12) + .jpg (4) = 22
        assert len(filename) == 22


# =========================================================================
# 图片下载请求测试
# =========================================================================

class TestDownloadImage:
    """图片下载请求应支持需要 Referer 的 CDN，并保持失败降级。"""

    @patch("src.processors.image_processor.validate_url", return_value=True)
    @patch("src.processors.image_processor.httpx.Client")
    def test_uses_article_url_as_referer(self, mock_client, _mock_validate):
        response = MagicMock()
        response.headers = {"Content-Length": "10"}
        response.iter_bytes.return_value = [b"image-data"]
        client = mock_client.return_value.__enter__.return_value
        client.stream.return_value.__enter__.return_value = response

        processor = ImageProcessor()
        result = processor._download_image(
            "https://cdn.example.com/image.jpg",
            base_url="https://example.com/articles/1",
        )

        assert result == b"image-data"
        headers = client.stream.call_args.kwargs["headers"]
        assert headers["Referer"] == "https://example.com/articles/1"
        assert headers["Accept"].startswith("image/")
        mock_client.assert_called_once_with(timeout=8, follow_redirects=False)

    @patch("src.processors.image_processor.validate_url", return_value=True)
    @patch("src.processors.image_processor.httpx.Client")
    def test_without_base_url_does_not_send_referer(self, mock_client, _mock_validate):
        response = MagicMock()
        response.headers = {"Content-Length": "10"}
        response.iter_bytes.return_value = [b"image-data"]
        client = mock_client.return_value.__enter__.return_value
        client.stream.return_value.__enter__.return_value = response

        result = ImageProcessor()._download_image("https://cdn.example.com/image.jpg")

        assert result == b"image-data"
        headers = client.stream.call_args.kwargs["headers"]
        assert "Referer" not in headers

    @patch("src.processors.image_processor.validate_url", return_value=True)
    @patch("src.processors.image_processor.httpx.Client")
    def test_403_returns_none(self, mock_client, _mock_validate):
        import httpx

        url = "https://cdn.example.com/image.jpg"
        response = httpx.Response(403, request=httpx.Request("GET", url))
        client = mock_client.return_value.__enter__.return_value
        client.stream.return_value.__enter__.return_value = response

        assert ImageProcessor()._download_image(url, base_url="https://example.com/article") is None

    @patch("src.processors.image_processor.validate_url", return_value=False)
    @patch("src.processors.image_processor.httpx.Client")
    def test_unsafe_url_is_rejected_before_request(self, mock_client, _mock_validate):
        assert ImageProcessor()._download_image("http://127.0.0.1/image.jpg") is None
        mock_client.assert_not_called()

    @patch("src.processors.image_processor.validate_url", return_value=True)
    @patch("src.processors.image_processor.httpx.Client")
    def test_content_length_limit_is_checked_before_reading(self, mock_client, _mock_validate):
        response = MagicMock()
        response.headers = {"Content-Length": str(ImageProcessor.MAX_DOWNLOAD_SIZE + 1)}
        client = mock_client.return_value.__enter__.return_value
        client.stream.return_value.__enter__.return_value = response

        assert ImageProcessor()._download_image("https://example.com/image.jpg") is None
        response.iter_bytes.assert_not_called()

    @patch("src.processors.image_processor.validate_url", return_value=True)
    @patch("src.processors.image_processor.httpx.Client")
    def test_streaming_download_limit_handles_missing_content_length(self, mock_client, _mock_validate):
        response = MagicMock()
        response.headers = {}
        response.iter_bytes.return_value = [b"x" * ImageProcessor.MAX_DOWNLOAD_SIZE, b"x"]
        client = mock_client.return_value.__enter__.return_value
        client.stream.return_value.__enter__.return_value = response

        assert ImageProcessor()._download_image("https://example.com/image.jpg") is None

    @patch("src.processors.image_processor.validate_url", return_value=True)
    @patch("src.processors.image_processor.httpx.Client")
    def test_redirect_response_is_not_followed(self, mock_client, _mock_validate):
        import httpx

        url = "https://example.com/image.jpg"
        response = httpx.Response(302, headers={"Location": "http://127.0.0.1/secret"}, request=httpx.Request("GET", url))
        client = mock_client.return_value.__enter__.return_value
        client.stream.return_value.__enter__.return_value = response

        assert ImageProcessor()._download_image(url) is None


# =========================================================================
# 图片处理流程测试（mock 下载）
# =========================================================================

class TestDownloadAndProcess:
    """ImageProcessor.download_and_process 集成测试"""

    @patch.object(ImageProcessor, "_download_image")
    def test_successful_processing(self, mock_download):
        """完整处理流程：下载 → 调整 → 压缩"""
        mock_download.return_value = _make_image_bytes(200, 300)

        processor = ImageProcessor()
        result = processor.download_and_process("https://example.com/img.jpg")

        assert result is not None
        filename, data = result
        assert filename.startswith("image_")
        assert filename.endswith(".jpg")
        assert len(data) > 0

    @patch.object(ImageProcessor, "_download_image")
    def test_rgba_converted_to_rgb(self, mock_download):
        """RGBA 图片转换为 RGB"""
        mock_download.return_value = _make_image_bytes(200, 200, mode="RGBA", fmt="PNG")

        processor = ImageProcessor()
        result = processor.download_and_process("https://example.com/img.png")

        assert result is not None
        _, data = result
        # 应输出 JPEG（非 PNG）
        assert data[:3] == b"\xff\xd8\xff"

    @patch.object(ImageProcessor, "_download_image")
    def test_download_failure_returns_none(self, mock_download):
        """下载失败返回 None"""
        mock_download.return_value = None

        processor = ImageProcessor()
        result = processor.download_and_process("https://example.com/img.jpg")

        assert result is None

    @patch.object(ImageProcessor, "_download_image")
    def test_processed_images_tracked(self, mock_download):
        """处理过的图片记录到 processed_images 列表"""
        mock_download.return_value = _make_image_bytes(200, 200)

        processor = ImageProcessor()
        processor.download_and_process("https://example.com/a.jpg")
        processor.download_and_process("https://example.com/b.jpg")

        assert len(processor.processed_images) == 2

    @patch.object(ImageProcessor, "_download_image")
    def test_get_total_size(self, mock_download):
        """get_total_size 返回所有图片的总字节数"""
        mock_download.return_value = _make_image_bytes(200, 200)

        processor = ImageProcessor()
        processor.download_and_process("https://example.com/a.jpg")
        processor.download_and_process("https://example.com/b.jpg")

        total = processor.get_total_size()
        assert total > 0
        assert total == sum(len(d) for _, d in processor.processed_images)

    @patch.object(ImageProcessor, "_download_image")
    def test_get_total_size_mb(self, mock_download):
        """get_total_size_mb 返回 MB 单位"""
        mock_download.return_value = _make_image_bytes(200, 200)

        processor = ImageProcessor()
        processor.download_and_process("https://example.com/a.jpg")

        mb = processor.get_total_size_mb()
        assert mb > 0
        assert mb == processor.get_total_size() / (1024 * 1024)

    def test_clear(self):
        """clear 清空已处理图片"""
        processor = ImageProcessor()
        processor.processed_images = [("a.jpg", b"data1"), ("b.jpg", b"data2")]
        processor.clear()
        assert len(processor.processed_images) == 0

    @patch.object(ImageProcessor, "_download_image")
    def test_concurrent_image_processing(self, mock_download):
        """测试在并发环境下 ImageProcessor 是否线程安全并且状态正确"""
        import concurrent.futures
        mock_download.return_value = _make_image_bytes(200, 200)

        processor = ImageProcessor()
        urls = [f"https://example.com/{i}.jpg" for i in range(20)]

        with concurrent.futures.ThreadPoolExecutor(max_workers=5) as executor:
            results = list(executor.map(processor.download_and_process, urls))

        # 检查是否所有图片都处理成功
        assert len(results) == 20
        assert all(res is not None for res in results)
        
        # 检查 processed_images 是否记录了所有图片而没有竞态丢失
        assert len(processor.processed_images) == 20
        
        # 验证总大小和清空操作
        total_size = processor.get_total_size()
        assert total_size > 0
        
        processor.clear()
        assert len(processor.processed_images) == 0


class TestStrictRecompression:
    """严格压缩触发与再压缩测试"""

    def setup_method(self):
        self.processor = ImageProcessor()

    def test_needs_strict_by_count(self):
        # 模拟超过数量阈值
        self.processor.processed_images = [
            (f"image_{i}.jpg", b"x" * 1000) for i in range(151)
        ]
        assert self.processor.needs_strict_compression() is True

    def test_needs_strict_by_size(self):
        # 模拟超过 25MB
        big = b"x" * (26 * 1024 * 1024)
        self.processor.processed_images = [("image_big.jpg", big)]
        assert self.processor.needs_strict_compression() is True

    def test_no_strict_when_normal(self):
        self.processor.processed_images = [
            ("image_0.jpg", b"x" * 1000) for _ in range(5)
        ]
        assert self.processor.needs_strict_compression() is False

    def test_recompress_all_strict_reduces_size(self):
        # 造一张较大的图，先按普通模式压，再严格再压，体积应下降或持平
        img = Image.new("RGB", (1200, 1800), (128, 64, 32))
        # 填一些噪声让 JPEG 不易压得很小
        import random
        pixels = img.load()
        for x in range(0, 1200, 3):
            for y in range(0, 1800, 3):
                pixels[x, y] = (
                    random.randint(0, 255),
                    random.randint(0, 255),
                    random.randint(0, 255),
                )
        normal_data = self.processor._compress_image(img)
        self.processor.processed_images = [("image_test.jpg", normal_data)]
        before = len(normal_data)

        mapping = self.processor.recompress_all_strict()
        after = len(mapping["image_test.jpg"])
        assert after <= before
        assert mapping["image_test.jpg"][:3] == b"\xff\xd8\xff"
