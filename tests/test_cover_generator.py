
from src.epub.cover import CoverGenerator
from src.config import TitleConfig
from PIL import Image
import pytest
from unittest.mock import MagicMock, patch

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
