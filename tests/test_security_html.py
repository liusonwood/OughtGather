"""Security regression tests for HTML and URI sanitization (PY-04)."""

from bs4 import BeautifulSoup
from src.config import ContentSource
from src.fetchers.base import Article
from src.processors.content_processor import ContentProcessor


def _process_html(html: str) -> str:
    source = ContentSource(type="web", src="https://example.com")
    processor = ContentProcessor(source)
    article = Article(title="Test", content=html, url="https://example.com/article")
    processed = processor.process(article)
    return processed.content


# =========================================================================
# Dangerous Tag Decomposing (PY-04)
# =========================================================================

def test_decomposes_executable_and_dangerous_tags():
    raw_html = (
        "<div>"
        "<p>Safe content</p>"
        "<script>alert('xss');</script>"
        "<iframe src='https://evil.com'></iframe>"
        "<object data='evil.swf'></object>"
        "<embed src='evil.pdf'></embed>"
        "<form action='/evil'><input type='text'/><button>Submit</button></form>"
        "<svg onload='alert(1)'><circle/></svg>"
        "<video src='movie.mp4'></video>"
        "<audio src='song.mp3'></audio>"
        "<applet code='evil.class'></applet>"
        "</div>"
    )
    result = _process_html(raw_html)

    for forbidden in (
        "<script", "<iframe", "<object", "<embed", "<form",
        "<input", "<button", "<svg", "<video", "<audio", "<applet"
    ):
        assert forbidden not in result.lower()
    assert "Safe content" in result


# =========================================================================
# Dangerous URI Schemes (PY-04)
# =========================================================================

def test_sanitizes_dangerous_href_schemes():
    raw_html = (
        "<div>"
        "<a href='javascript:alert(1)'>JS Link</a>"
        "<a href='vbscript:msgbox(1)'>VBS Link</a>"
        "<a href='file:///etc/passwd'>File Link</a>"
        "<a href='data:text/html,<script>alert(1)</script>'>Data Link</a>"
        "<a href='https://example.com/safe'>Safe Link</a>"
        "<a href='#section-1'>Anchor Link</a>"
        "</div>"
    )
    result = _process_html(raw_html)

    assert "javascript:" not in result.lower()
    assert "vbscript:" not in result.lower()
    assert "file:///" not in result.lower()
    assert "data:text/html" not in result.lower()
    assert "https://example.com/safe" in result
    assert "#section-1" in result


def test_removes_dangerous_img_schemes():
    raw_html = (
        "<div>"
        "<img src='javascript:alert(1)' alt='evil js'/>"
        "<img src='file:///etc/shadow' alt='evil file'/>"
        "<img src='blob:http://example.com/xyz' alt='evil blob'/>"
        "<img src='https://example.com/valid.jpg' alt='good img'/>"
        "</div>"
    )
    result = _process_html(raw_html)

    assert "javascript:" not in result.lower()
    assert "file:///" not in result.lower()
    assert "blob:" not in result.lower()
    assert "https://example.com/valid.jpg" in result


# =========================================================================
# Event Handler Stripping (PY-04)
# =========================================================================

def test_strips_inline_event_handlers():
    raw_html = (
        "<div onclick='alert(1)'>"
        "<p onmouseover='evil()' onload='evil()' onerror='evil()'>Text</p>"
        "</div>"
    )
    result = _process_html(raw_html)

    assert "onclick" not in result.lower()
    assert "onmouseover" not in result.lower()
    assert "onload" not in result.lower()
    assert "onerror" not in result.lower()
    assert "Text" in result


# =========================================================================
# CSS / Style Sanitization (PY-04)
# =========================================================================

def test_sanitizes_dangerous_css_expressions_and_urls():
    raw_html = (
        "<p style='background-image: url(javascript:alert(1)); expression(alert(1));'>Styled text</p>"
    )
    result = _process_html(raw_html)

    assert "expression" not in result.lower()
    assert "javascript:" not in result.lower()
    assert "url(" not in result.lower()
    assert "Styled text" in result
