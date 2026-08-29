"""Security regression tests for image processing (PY-02, PY-03)."""

import io
from unittest.mock import patch, MagicMock
from PIL import Image
import pytest

from src.processors.image_processor import (
    ImageProcessor,
    is_valid_image_header,
    ALLOWED_IMAGE_FORMATS,
)


def _make_image_bytes(width: int = 150, height: int = 150, fmt: str = "JPEG") -> bytes:
    img = Image.new("RGB", (width, height), (255, 0, 0))
    buf = io.BytesIO()
    img.save(buf, format=fmt)
    return buf.getvalue()


# =========================================================================
# Magic Bytes and Format Validation (PY-03)
# =========================================================================

def test_magic_bytes_detection_valid():
    assert is_valid_image_header(_make_image_bytes(150, 150, "JPEG"))
    assert is_valid_image_header(_make_image_bytes(150, 150, "PNG"))
    assert is_valid_image_header(_make_image_bytes(150, 150, "GIF"))
    assert is_valid_image_header(_make_image_bytes(150, 150, "WEBP"))


def test_magic_bytes_rejection_invalid_and_svg():
    # SVG XML
    assert not is_valid_image_header(b"<svg xmlns='http://www.w3.org/2000/svg'><circle/></svg>")
    # HTML masquerading as image
    assert not is_valid_image_header(b"<!DOCTYPE html><html><body>Error</body></html>")
    # Empty or short bytes
    assert not is_valid_image_header(b"")
    assert not is_valid_image_header(b"short")


def test_process_image_rejects_invalid_magic_bytes():
    processor = ImageProcessor()
    fake_img = b"<html><body>Not an image</body></html>"
    result = processor._process_image(fake_img, "https://example.com/fake.jpg")
    assert result is None


def test_process_image_rejects_svg():
    processor = ImageProcessor()
    svg_data = b"<svg xmlns='http://www.w3.org/2000/svg' width='200' height='200'></svg>"
    result = processor._process_image(svg_data, "https://example.com/vector.svg")
    assert result is None


# =========================================================================
# Decompression Bomb and Pixel Limit Protection (PY-02)
# =========================================================================

def test_process_image_rejects_pixel_limit_exceeded():
    processor = ImageProcessor()
    # Create image exceeding MAX_IMAGE_PIXELS
    with patch("PIL.Image.open") as mock_open:
        mock_img = MagicMock()
        mock_img.format = "JPEG"
        # 6000 x 5000 = 30,000,000 pixels > 25,000,000 limit
        mock_img.size = (6000, 5000)
        mock_open.return_value = mock_img

        valid_jpeg_header = b"\xff\xd8\xff\xe0\x00\x10JFIF\x00\x01\x01\x00" + b"\x00" * 20
        result = processor._process_image(valid_jpeg_header, "https://example.com/bomb.jpg")
        assert result is None


def test_process_image_handles_decompression_bomb_exception():
    processor = ImageProcessor()
    with patch("PIL.Image.open", side_effect=Image.DecompressionBombError("Bomb detected")):
        valid_jpeg_header = b"\xff\xd8\xff\xe0\x00\x10JFIF\x00\x01\x01\x00" + b"\x00" * 20
        result = processor._process_image(valid_jpeg_header, "https://example.com/bomb.jpg")
        assert result is None


# =========================================================================
# Resource Limit Guards in Download (PY-06)
# =========================================================================

def test_download_rejects_unsupported_content_type():
    processor = ImageProcessor()
    with patch("src.processors.image_processor.validate_url", return_value=True):
        with patch("src.processors.image_processor.create_safe_client") as mock_client_factory:
            mock_client = MagicMock()
            mock_response = MagicMock()
            mock_response.headers = {"Content-Type": "image/svg+xml"}
            mock_client.stream.return_value.__enter__.return_value = mock_response
            mock_client_factory.return_value.__enter__.return_value = mock_client

            assert processor._download_image("https://example.com/image.svg") is None
