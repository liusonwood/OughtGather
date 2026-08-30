
from src.epub.cover import CoverGenerator
from src.config import TitleConfig
from PIL import Image
import pytest
from unittest.mock import MagicMock, patch
import io

# conftest.py replaces these methods for normal EPUB tests. Keep references to
# the real implementations so the focused unit tests need no module reload.
REAL_DOWNLOAD_IMAGE = CoverGenerator._download_image
REAL_FETCH_BING_WALLPAPER = CoverGenerator._fetch_bing_wallpaper

def test_add_text_overlay_mask():
    config = TitleConfig(text="Test Title", img="")
    cg = CoverGenerator(config)
    
    # Create a solid red background
    background = Image.new('RGB', (1440, 1920), color=(255, 0, 0))
    
    # Apply the overlay
    covered = cg._add_text_overlay(background)
    
    # Check a pixel in the middle
    # The red color (255, 0, 0) blended with white (255, 255, 255, 76/255)
    # The result should be roughly (255, 179, 179)
    pixel = covered.getpixel((720, 960))
    
    print(f"Pixel color: {pixel}")
    
    # Assert the color is no longer pure red
    assert pixel != (255, 0, 0)
    assert pixel[0] == 255 # Red component should still be high
    assert pixel[1] > 0   # Green component should have increased
    assert pixel[2] > 0   # Blue component should have increased


def test_bing_wallpaper_uses_epub_locale(monkeypatch):
    monkeypatch.setenv("EPUB_LANGUAGE", "ja-JP")
    generator = CoverGenerator(TitleConfig(text="Test Title", img=""))
    assert "mkt=ja-JP" in generator._build_bing_api_url()


def _image_bytes(fmt="PNG", mode="RGB", size=(20, 30)):
    image = Image.new(mode, size, (20, 40, 60, 128) if "A" in mode else (20, 40, 60))
    buffer = io.BytesIO()
    image.save(buffer, format=fmt)
    return buffer.getvalue()


def test_generate_uses_solid_background_when_all_downloads_fail():
    generator = CoverGenerator(TitleConfig(text="Daily", img=""))
    with patch.object(generator, "_fetch_bing_wallpaper", return_value=None):
        filename, data = generator.generate()
    assert filename == "cover.jpg"
    result = Image.open(io.BytesIO(data))
    assert result.size == (1440, 1920)
    assert result.format == "JPEG"


def test_get_background_prefers_working_custom_image():
    generator = CoverGenerator(TitleConfig(text="Daily", img="https://example.com/cover.png"))
    custom = Image.new("RGB", (10, 10), "red")
    with patch.object(generator, "_download_image", return_value=custom) as download, \
         patch.object(generator, "_fetch_bing_wallpaper") as bing:
        assert generator._get_background() is custom
    download.assert_called_once_with("https://example.com/cover.png")
    bing.assert_not_called()


def test_download_image_rejects_unsafe_url():
    generator = CoverGenerator(TitleConfig(text="Daily", img=""))
    with patch("src.epub.cover.validate_url", return_value=False), \
         patch("src.epub.cover.create_safe_client") as client:
        assert REAL_DOWNLOAD_IMAGE(generator, "http://127.0.0.1/image") is None
    client.assert_not_called()


def test_download_image_accepts_png_and_converts_transparency():
    generator = CoverGenerator(TitleConfig(text="Daily", img=""))
    response = MagicMock(content=_image_bytes(mode="RGBA"))
    client = MagicMock()
    client.__enter__.return_value = client
    client.__exit__.return_value = None
    with patch("src.epub.cover.validate_url", return_value=True), \
         patch("src.epub.cover.create_safe_client", return_value=client), \
         patch("src.epub.cover.safe_request", return_value=response):
        image = REAL_DOWNLOAD_IMAGE(generator, "https://example.com/image.png")
    assert image is not None
    assert image.mode == "RGB"
    assert image.size == (1440, 1920)


def test_download_image_rejects_disallowed_format():
    generator = CoverGenerator(TitleConfig(text="Daily", img=""))
    response = MagicMock(content=_image_bytes(fmt="BMP"))
    client = MagicMock()
    client.__enter__.return_value = client
    client.__exit__.return_value = None
    with patch("src.epub.cover.validate_url", return_value=True), \
         patch("src.epub.cover.create_safe_client", return_value=client), \
         patch("src.epub.cover.safe_request", return_value=response):
        assert REAL_DOWNLOAD_IMAGE(generator, "https://example.com/image.bmp") is None


def test_fetch_bing_wallpaper_downloads_first_image():
    generator = CoverGenerator(TitleConfig(text="Daily", img=""))
    client = MagicMock()
    client.__enter__.return_value = client
    client.__exit__.return_value = None
    api_response = MagicMock()
    api_response.json.return_value = {"images": [{"url": "/th?id=wallpaper"}]}
    expected = Image.new("RGB", (10, 10))
    with patch("src.epub.cover.create_safe_client", return_value=client), \
         patch("src.epub.cover.safe_request", return_value=api_response), \
         patch.object(generator, "_download_image", return_value=expected) as download:
        assert REAL_FETCH_BING_WALLPAPER(generator) is expected
    download.assert_called_once_with("https://www.bing.com/th?id=wallpaper")


def test_fetch_bing_wallpaper_handles_missing_images_and_errors():
    generator = CoverGenerator(TitleConfig(text="Daily", img=""))
    client = MagicMock()
    client.__enter__.return_value = client
    client.__exit__.return_value = None
    empty = MagicMock()
    empty.json.return_value = {"images": []}
    with patch("src.epub.cover.create_safe_client", return_value=client), \
         patch("src.epub.cover.safe_request", return_value=empty):
        assert REAL_FETCH_BING_WALLPAPER(generator) is None
    with patch("src.epub.cover.create_safe_client", side_effect=RuntimeError("network")):
        assert REAL_FETCH_BING_WALLPAPER(generator) is None
