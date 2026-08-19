
import pytest
from unittest.mock import MagicMock, patch
from bs4 import BeautifulSoup
from ebooklib import epub

from src.fetchers.web_fetcher import WebFetcher
from src.epub.generator import EPUBGenerator
from src.config import ContentSource, Config, _parse_config
from src.fetchers.base import Article, FetchResult

class TestImageBugs:
    """Specialized tests for image-related bugs."""

    def test_lazy_loading_extraction(self):
        """Test Bug 3: Lazy loading attributes extraction."""
        source = ContentSource(type="web", src="https://example.com", title="Test")
        fetcher = WebFetcher(source)
        
        html = """
        <html>
            <body>
                <img src="placeholder.gif" data-src="https://example.com/real-image.jpg">
                <img data-original="https://example.com/real-image-2.jpg">
                <img src="https://example.com/normal.jpg">
            </body>
        </html>
        """
        
        images = fetcher._extract_images(html)
        assert "https://example.com/real-image.jpg" in images
        assert "https://example.com/real-image-2.jpg" in images
        assert "https://example.com/normal.jpg" in images
        # placeholder.gif should be ignored if data-src is present
        assert "placeholder.gif" not in images

    def test_srcset_gif_svg_and_data_uri_filtering(self):
        """Test Bug 3: srcset parsing filters out .gif, .svg, and data: URIs."""
        source = ContentSource(type="web", src="https://example.com", title="Test")
        fetcher = WebFetcher(source)
        
        html = """
        <html>
            <body>
                <img srcset="https://example.com/small.gif 100w, https://example.com/large.svg 200w">
                <img srcset="data:image/png;base64,12345 100w, https://example.com/real-srcset.jpg 200w">
                <img src="https://example.com/static.gif">
            </body>
        </html>
        """
        
        images = fetcher._extract_images(html)
        assert images == ["https://example.com/real-srcset.jpg"]

    def test_image_replacement_with_encoding(self):
        """Test Bug 2: URL encoding mismatch (& vs &amp;)."""
        config_data = {
            "title": {"text": "Test", "img": ""},
            "body": [{"type": "web", "src": "https://example.com", "title": "Test"}]
        }
        config = _parse_config(config_data)
        generator = EPUBGenerator(config)
        
        # HTML with encoded ampersand
        url_with_amp = "https://example.com/img?w=800&h=600"
        html_content = f'<div><img src="https://example.com/img?w=800&amp;h=600"></div>'
        
        article = Article(
            title="Test",
            content=html_content,
            url="https://example.com",
            images=[url_with_amp]
        )
        
        chapter = epub.EpubHtml(title="Test", file_name="test.xhtml")
        chapter.content = generator._generate_chapter_content(article, 0)
        
        book = epub.EpubBook()
        
        with patch.object(generator.image_processor, "download_and_process", return_value=("processed.jpg", b"data")):
            generator._add_images_to_chapter(book, chapter, article)
            
        assert "images/processed.jpg" in chapter.content
        assert url_with_amp not in chapter.content
        assert "w=800&amp;h=600" not in chapter.content

    def test_trafilatura_images_from_raw_html(self):
        """Test Bug 1: trafilatura 剥离图片时，从原始 HTML 取回图片 URL。"""
        source = ContentSource(type="web", src="https://example.com", title="Test")
        fetcher = WebFetcher(source)

        raw_html = """
        <html>
            <body>
                <article>
                    <h1>Title</h1>
                    <img src="https://example.com/test.jpg">
                    <p>Content</p>
                </article>
            </body>
        </html>
        """

        # Mock trafilatura.extract 返回不含 <img> 的内容
        trafilatura_content = "<html><body><h1>Title</h1><p>Content</p></body></html>"
        with patch("src.fetchers.web_fetcher.trafilatura.extract", return_value=trafilatura_content):
            with patch.object(fetcher, "_make_request") as mock_req:
                mock_req.return_value.text = raw_html
                result = fetcher.fetch()

                assert result.success
                assert len(result.articles) == 1
                # 内容用 trafilatura 的（_restore_img_tags 会去掉 html/body 包装）
                assert result.articles[0].content == "<h1>Title</h1><p>Content</p>"
                # 图片从原始 HTML 取回
                assert "https://example.com/test.jpg" in result.articles[0].images

    def test_lazy_loading_removal_in_epub(self):
        """Test that lazy loading attributes are removed in the final EPUB content."""
        config_data = {
            "title": {"text": "Test", "img": ""},
            "body": [{"type": "web", "src": "https://example.com", "title": "Test"}]
        }
        config = _parse_config(config_data)
        generator = EPUBGenerator(config)
        
        html_content = '<img src="placeholder.jpg" data-src="https://example.com/real.jpg">'
        article = Article(
            title="Test",
            content=html_content,
            url="https://example.com",
            images=["https://example.com/real.jpg"]
        )
        
        chapter = epub.EpubHtml(title="Test", file_name="test.xhtml")
        chapter.content = html_content
        book = epub.EpubBook()
        
        with patch.object(generator.image_processor, "download_and_process", return_value=("real.jpg", b"data")):
            generator._add_images_to_chapter(book, chapter, article)
            
        assert "images/real.jpg" in chapter.content
        assert "data-src" not in chapter.content
        assert "placeholder.jpg" not in chapter.content

    def test_restore_img_tags_converts_graphic_to_img(self):
        """Test that _restore_img_tags converts <graphic> tags to <img> tags.

        trafilatura in output_format="html" converts <img> to <graphic>
        (an HTML5 element), which downstream code doesn't recognize.
        """
        from src.fetchers.base import BaseFetcher

        html = """<html><body>
        <h1>Title</h1>
        <graphic src="https://example.com/img1.jpg"></graphic>
        <p>Some text</p>
        <graphic src="https://example.com/img2.png"></graphic>
        </body></html>"""

        result = BaseFetcher._restore_img_tags(html)
        soup = BeautifulSoup(result, 'lxml')

        # All <graphic> should be converted to <img>
        assert len(soup.find_all('graphic')) == 0
        imgs = soup.find_all('img')
        assert len(imgs) == 2
        assert imgs[0]['src'] == 'https://example.com/img1.jpg'
        assert imgs[1]['src'] == 'https://example.com/img2.png'

    def test_restore_img_tags_preserves_existing_img(self):
        """Test that _restore_img_tags doesn't affect existing <img> tags."""
        from src.fetchers.base import BaseFetcher

        html = """<html><body>
        <img src="https://example.com/normal.jpg">
        <graphic src="https://example.com/converted.jpg"></graphic>
        </body></html>"""

        result = BaseFetcher._restore_img_tags(html)
        soup = BeautifulSoup(result, 'lxml')

        imgs = soup.find_all('img')
        assert len(imgs) == 2
        assert imgs[0]['src'] == 'https://example.com/normal.jpg'
        assert imgs[1]['src'] == 'https://example.com/converted.jpg'

    def test_restore_img_tags_does_not_split_pre_inside_p(self):
        """_restore_img_tags 不得用 lxml 把 <p> 内的 <pre> 拆出段落"""
        from src.fetchers.base import BaseFetcher

        html = (
            '<html><body>'
            '<p>是用 <pre>codesign</pre> 给微信重新签名</p>'
            '<graphic src="https://example.com/a.jpg"></graphic>'
            '</body></html>'
        )
        result = BaseFetcher._restore_img_tags(html)
        assert '<p>是用 <pre>codesign</pre> 给微信重新签名</p>' in result
        assert '</p><pre>' not in result
        assert '<img src="https://example.com/a.jpg">' in result or '<img src="https://example.com/a.jpg"/>' in result
        assert '<graphic' not in result.lower()

    def test_web_fetcher_restores_graphic_tags(self):
        """Test that WebFetcher restores <graphic> tags from trafilatura output."""
        source = ContentSource(type="web", src="https://example.com", title="Test")
        fetcher = WebFetcher(source)

        raw_html = """
        <html>
            <body>
                <article>
                    <h1>Title</h1>
                    <img src="https://example.com/test.jpg">
                    <p>Content</p>
                </article>
            </body>
        </html>
        """

        # Mock trafilatura to return <graphic> instead of <img>
        trafilatura_content = "<html><body><h1>Title</h1><graphic src=\"https://example.com/test.jpg\"></graphic><p>Content</p></body></html>"
        with patch("src.fetchers.web_fetcher.trafilatura.extract", return_value=trafilatura_content):
            with patch.object(fetcher, "_make_request") as mock_req:
                mock_req.return_value.text = raw_html
                result = fetcher.fetch()

                assert result.success
                assert len(result.articles) == 1
                # Content should have <img> tags, not <graphic>
                content = result.articles[0].content
                assert "<graphic" not in content
                assert "https://example.com/test.jpg" in content

    def test_rss_fetcher_full_text_restores_graphic_tags(self):
        """Test that RSSFetcher with full_text=Y restores <graphic> tags from trafilatura."""
        from src.fetchers.rss_fetcher import RSSFetcher

        source = ContentSource(
            type="rss",
            src="https://example.com/feed.xml",
            priority=10,
            full_text="Y"
        )
        fetcher = RSSFetcher(source)

        raw_html = """
        <html>
            <body>
                <article>
                    <h1>Article Title</h1>
                    <img src="https://cdn.example.com/photo.webp">
                    <p>Article content here.</p>
                </article>
            </body>
        </html>
        """

        # Mock trafilatura to return <graphic> instead of <img>
        trafilatura_content = "<html><body><h1>Article Title</h1><graphic src=\"https://cdn.example.com/photo.webp\"></graphic><p>Article content here.</p></body></html>"

        with patch.object(fetcher, "_make_request") as mock_req:
            mock_req.return_value.text = raw_html
            with patch("src.fetchers.base.trafilatura.extract", return_value=trafilatura_content):
                content, raw = fetcher._fetch_full_text("https://example.com/article")

                # Content should have <img> tags, not <graphic>
                assert "<graphic" not in content
                assert "https://cdn.example.com/photo.webp" in content
                soup = BeautifulSoup(content, 'lxml')
                assert len(soup.find_all('img')) == 1

    def test_emoji_images_not_decomposed(self):
        """Test that local emoji images are not decomposed/removed during image sanitization."""
        config_data = {
            "title": {"text": "Test", "img": ""},
            "body": [{"type": "web", "src": "https://example.com", "title": "Test"}]
        }
        config = _parse_config(config_data)
        generator = EPUBGenerator(config)

        html_content = '<p>Hello <img class="emoji" src="images/emoji_1f34c.png" alt="🍌"> World</p>'
        article = Article(
            title="Test Emoji",
            content=html_content,
            url="https://example.com"
        )

        chapter = epub.EpubHtml(title="Test Emoji", file_name="test.xhtml")
        chapter.content = html_content
        book = epub.EpubBook()

        # Call _add_images_to_chapter
        generator._add_images_to_chapter(book, chapter, article)

        # The emoji img tag should still exist
        assert "images/emoji_1f34c.png" in chapter.content
        assert 'class="emoji"' in chapter.content
