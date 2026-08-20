import datetime
import pytest
from unittest.mock import MagicMock, patch
from lxml import html as lxml_html
from bs4 import BeautifulSoup

from src.config import ContentSource
from src.fetchers.xpath_fetcher import XPathListAutoFetcher
from src.fetchers.base import FetchResult, Article

class TestXPathListAutoFetcher:
    """XPathListAutoFetcher 单元与集成测试"""

    def test_missing_xpath_metadata(self):
        """测试未配置 list_xpath 时报错"""
        source = ContentSource(
            type="xpath_list_auto",
            src="http://example.com/list",
            metadata={}  # 缺少 list_xpath
        )
        fetcher = XPathListAutoFetcher(source)
        result = fetcher.fetch()
        
        assert result.success is False
        assert "未配置 'list_xpath'" in result.error
        assert len(result.articles) == 0

    @patch.object(XPathListAutoFetcher, "_make_request")
    def test_fetch_no_candidate_links(self, mock_request):
        """测试列表页未提取到任何链接时，返回成功但文章列表为空"""
        mock_response = MagicMock()
        mock_response.content = "<html><body><div class='no-news'>没有内容</div></body></html>".encode("utf-8")
        mock_request.return_value = mock_response

        source = ContentSource(
            type="xpath_list_auto",
            src="http://example.com/list",
            metadata={"list_xpath": "//div[@class='item']/a/@href"}
        )
        fetcher = XPathListAutoFetcher(source)
        result = fetcher.fetch()

        assert result.success is True
        assert len(result.articles) == 0
        mock_request.assert_called_once_with("http://example.com/list")

    @patch("src.fetchers.xpath_fetcher.trafilatura.extract_metadata")
    @patch.object(XPathListAutoFetcher, "_fetch_full_text")
    @patch.object(XPathListAutoFetcher, "_make_request")
    def test_fetch_with_candidate_links_string_and_element(self, mock_request, mock_fetch, mock_extract_meta):
        """测试列表页分别返回字符、含有get方法的对象、以及不含get含有text属性的对象等各种提取结果时的链接解析与去重"""
        list_html = b"<html><body>mocked</body></html>"
        mock_list_response = MagicMock()
        mock_list_response.content = list_html
        mock_request.return_value = mock_list_response

        # 模拟 _fetch_full_text：分别针对 detail1, detail2, detail3 返回内容
        mock_fetch.side_effect = [
            ("<p>Content 1</p>", "<html><body><p>Content 1</p></body></html>"),
            ("<p>Content 2</p>", "<html><body><p>Content 2</p></body></html>"),
            ("<p>Content 3</p>", "<html><body><p>Content 3</p></body></html>")
        ]

        # 模拟 trafilatura.extract_metadata
        class MockMeta:
            def __init__(self, title, author, date):
                self.title = title
                self.author = author
                self.date = date

        mock_extract_meta.side_effect = [
            MockMeta("Title 1", "Author 1", "2026-07-20 10:00:00"),
            MockMeta("Title 2", "Author 2", "2026-07-20 11:00:00"),
            MockMeta("Title 3", "Author 3", "2026-07-20 12:00:00")
        ]

        source = ContentSource(
            type="xpath_list_auto",
            src="http://example.com/list",
            metadata={"list_xpath": "//some/path"}
        )
        fetcher = XPathListAutoFetcher(source)

        # 构造不同形式的候选链接列表：
        # 1. 直接是 string (例如: /detail1)
        # 2. 含有 get() 属性的对象 (例如: /detail2)
        # 3. 不含有 get() 属性但含有 text 属性的对象 (例如: /detail3)
        # 4. 重复的链接
        # 5. 空字符链接
        mock_link_with_get = MagicMock()
        mock_link_with_get.get.return_value = "/detail2"
        
        mock_link_with_text = MagicMock(spec=['text'])
        mock_link_with_text.text = "/detail3"

        mock_xpath_results = [
            "/detail1",
            mock_link_with_get,
            mock_link_with_text,
            "/detail1",  # 重复
            "",          # 空
        ]

        # 拦截 lxml_html.fromstring 返回的对象，使其 xpath 结果为我们构造的候选列表
        mock_tree = MagicMock()
        mock_tree.xpath.return_value = mock_xpath_results

        with patch("src.fetchers.xpath_fetcher.lxml_html.fromstring", return_value=mock_tree):
            result = fetcher.fetch()

        assert result.success is True
        # 应该只有 3 篇，去重、过滤空链接
        assert len(result.articles) == 3
        
        art1, art2, art3 = result.articles
        assert art1.title == "Title 1"
        assert art1.url == "http://example.com/detail1"
        assert art1.content == "<p>Content 1</p>"

        assert art2.title == "Title 2"
        assert art2.url == "http://example.com/detail2"
        assert art2.content == "<p>Content 2</p>"

        assert art3.title == "Title 3"
        assert art3.url == "http://example.com/detail3"
        assert art3.content == "<p>Content 3</p>"

    @patch("src.fetchers.xpath_fetcher.trafilatura.extract_metadata", side_effect=Exception("mocked trafilatura error"))
    @patch.object(XPathListAutoFetcher, "_fetch_full_text")
    @patch.object(XPathListAutoFetcher, "_make_request")
    def test_title_fallback_logic(self, mock_request, mock_fetch, mock_extract_meta):
        """测试标题提取的兜底逻辑（H1 -> title -> Untitled）"""
        list_html = b'<html><body><a href="/detail">Link</a></body></html>'
        mock_request.return_value = MagicMock(content=list_html)

        source = ContentSource(
            type="xpath_list_auto",
            src="http://example.com/list",
            metadata={"list_xpath": "//a/@href"}
        )

        # 1. 优先使用 <h1> 标题
        mock_fetch.return_value = (
            "<p>Content</p>",
            "<html><body><h1>Title From H1</h1><title>Title From Title Tag</title></body></html>"
        )
        fetcher = XPathListAutoFetcher(source)
        result = fetcher.fetch()
        assert len(result.articles) == 1
        assert result.articles[0].title == "Title From H1"

        # 2. 无 <h1>，使用 <title> 标签
        mock_fetch.return_value = (
            "<p>Content</p>",
            "<html><head><title>Title From Title Tag</title></head><body></body></html>"
        )
        result = fetcher.fetch()
        assert result.articles[0].title == "Title From Title Tag"

        # 3. 都没有，兜底使用 "Untitled"
        mock_fetch.return_value = (
            "<p>Content</p>",
            "<html><body></body></html>"
        )
        result = fetcher.fetch()
        assert result.articles[0].title == "Untitled"

    @patch("src.fetchers.xpath_fetcher.trafilatura.extract_metadata", return_value=None)
    @patch.object(XPathListAutoFetcher, "_fetch_full_text")
    @patch.object(XPathListAutoFetcher, "_make_request")
    def test_content_fallback_logic(self, mock_request, mock_fetch, mock_extract_meta):
        """测试正文提取的兜底逻辑 (article -> div.article -> div.content -> div.entry-content -> div#content -> main -> body)"""
        list_html = b'<html><body><a href="/detail">Link</a></body></html>'
        mock_request.return_value = MagicMock(content=list_html)

        source = ContentSource(
            type="xpath_list_auto",
            src="http://example.com/list",
            metadata={"list_xpath": "//a/@href"}
        )
        fetcher = XPathListAutoFetcher(source)

        # 各个降级 HTML 正文结构对应的测试
        cases = [
            ("<html><body><article>Article Tag Content</article></body></html>", "Article Tag Content"),
            ("<html><body><div class=\"article\">Div Article Content</div></body></html>", "Div Article Content"),
            ("<html><body><div class=\"content\">Div Content Content</div></body></html>", "Div Content Content"),
            ("<html><body><div class=\"entry-content\">Entry Content Content</div></body></html>", "Entry Content Content"),
            ("<html><body><div id=\"content\">Id Content Content</div></body></html>", "Id Content Content"),
            ("<html><body><main>Main Content Content</main></body></html>", "Main Content Content"),
            ("<html><body>Just body text, nothing else</body></html>", "Just body text, nothing else")
        ]

        for raw, expected_text in cases:
            # 模拟基类 _fetch_full_text 未能提取到正文 HTML (content_html 为空)
            mock_fetch.return_value = ("", raw)
            result = fetcher.fetch()
            assert len(result.articles) == 1
            article_content = result.articles[0].content
            assert expected_text in article_content

    @patch("src.fetchers.xpath_fetcher.get_now")
    @patch("src.fetchers.xpath_fetcher.trafilatura.extract_metadata", return_value=None)
    @patch.object(XPathListAutoFetcher, "_fetch_full_text")
    @patch.object(XPathListAutoFetcher, "_make_request")
    def test_pub_date_fallback_logic(self, mock_request, mock_fetch, mock_extract_meta, mock_get_now):
        """测试发布日期的兜底逻辑（北京时间）"""
        list_html = b'<html><body><a href="/detail">Link</a></body></html>'
        mock_request.return_value = MagicMock(content=list_html)

        # Mock 当前系统北京时间
        fixed_now = datetime.datetime(2026, 7, 21, 8, 30, 0)
        mock_get_now.return_value = fixed_now

        source = ContentSource(
            type="xpath_list_auto",
            src="http://example.com/list",
            metadata={"list_xpath": "//a/@href"}
        )
        fetcher = XPathListAutoFetcher(source)

        mock_fetch.return_value = ("<p>content</p>", "<html><body></body></html>")
        result = fetcher.fetch()
        
        assert len(result.articles) == 1
        assert result.articles[0].published_date == "2026-07-21 08:30:00"

    @patch.object(XPathListAutoFetcher, "_extract_images")
    @patch.object(XPathListAutoFetcher, "_extract_og_image")
    @patch("src.fetchers.xpath_fetcher.trafilatura.extract_metadata", return_value=None)
    @patch.object(XPathListAutoFetcher, "_fetch_full_text")
    @patch.object(XPathListAutoFetcher, "_make_request")
    def test_image_extraction_and_deduplication(self, mock_request, mock_fetch, mock_extract_meta, mock_og_img, mock_body_img):
        """测试详情页封面图（og:image）和正文图的提取与去重，且封面图排在第一位"""
        list_html = b'<html><body><a href="/detail">Link</a></body></html>'
        mock_request.return_value = MagicMock(content=list_html)

        source = ContentSource(
            type="xpath_list_auto",
            src="http://example.com/list",
            metadata={"list_xpath": "//a/@href"}
        )
        fetcher = XPathListAutoFetcher(source)

        mock_fetch.return_value = ("<p>Content</p>", "<html><body></body></html>")
        
        # 模拟提取到的封面图和正文图片（有重复）
        mock_og_img.return_value = ["http://example.com/cover.jpg"]
        mock_body_img.return_value = ["http://example.com/cover.jpg", "http://example.com/body_image1.jpg", "http://example.com/body_image2.jpg"]

        result = fetcher.fetch()
        assert len(result.articles) == 1
        assert result.articles[0].images == [
            "http://example.com/cover.jpg",
            "http://example.com/body_image1.jpg",
            "http://example.com/body_image2.jpg"
        ]

    @patch("src.fetchers.xpath_fetcher.trafilatura.extract_metadata", return_value=None)
    @patch.object(XPathListAutoFetcher, "_fetch_full_text")
    @patch.object(XPathListAutoFetcher, "_make_request")
    def test_delete_rule_filtering(self, mock_request, mock_fetch, mock_extract_meta):
        """测试 delete 屏蔽词规则，符合标题屏蔽规则的文章应被过滤"""
        list_html = b'<html><body><a href="/detail1">L1</a><a href="/detail2">L2</a></body></html>'
        mock_request.return_value = MagicMock(content=list_html)

        # 包含 "广告" 和 "垃圾" 的 delete 过滤规则
        source = ContentSource(
            type="xpath_list_auto",
            src="http://example.com/list",
            delete="广告,垃圾",
            metadata={"list_xpath": "//a/@href"}
        )
        fetcher = XPathListAutoFetcher(source)

        # 详情页1标题含"广告"，详情页2正常
        mock_fetch.side_effect = [
            ("<p>Content 1</p>", "<html><body><h1>优惠大酬宾！这是一条广告</h1></body></html>"),
            ("<p>Content 2</p>", "<html><body><h1>正常的干货文章</h1></body></html>")
        ]

        result = fetcher.fetch()
        assert len(result.articles) == 1
        assert result.articles[0].title == "正常的干货文章"

    @patch("src.fetchers.xpath_fetcher.trafilatura.extract_metadata", return_value=None)
    @patch.object(XPathListAutoFetcher, "_fetch_full_text")
    @patch.object(XPathListAutoFetcher, "_make_request")
    def test_global_limit_capping(self, mock_request, mock_fetch, mock_extract_meta):
        """测试全局抓取数量上限限制（global_limit）"""
        list_html = b'<html><body><a href="/d1"></a><a href="/d2"></a><a href="/d3"></a></body></html>'
        mock_request.return_value = MagicMock(content=list_html)

        source = ContentSource(
            type="xpath_list_auto",
            src="http://example.com/list",
            metadata={"list_xpath": "//a/@href"}
        )
        # 限制 global_limit 为 2
        fetcher = XPathListAutoFetcher(source, global_limit=2)

        mock_fetch.return_value = ("<p>Content</p>", "<html><body><h1>Title</h1></body></html>")

        result = fetcher.fetch()
        # 虽然列表提取到 3 个链接，由于限制 global_limit=2，所以只抓取 2 个
        assert len(result.articles) == 2
        assert mock_fetch.call_count == 2

    @patch("src.fetchers.xpath_fetcher.trafilatura.extract_metadata", return_value=None)
    @patch.object(XPathListAutoFetcher, "_fetch_full_text")
    @patch.object(XPathListAutoFetcher, "_make_request")
    def test_detail_page_error_handling(self, mock_request, mock_fetch, mock_extract_meta):
        """测试某一个详情页抓取失败时，记录异常但不打断后续详情页的解析"""
        list_html = b'<html><body><a href="/d1"></a><a href="/d2"></a></body></html>'
        mock_request.return_value = MagicMock(content=list_html)

        source = ContentSource(
            type="xpath_list_auto",
            src="http://example.com/list",
            metadata={"list_xpath": "//a/@href"}
        )
        fetcher = XPathListAutoFetcher(source)

        # 详情页1报错，详情页2正常
        mock_fetch.side_effect = [
            Exception("Detail page fetch failure!"),
            ("<p>Content 2</p>", "<html><body><h1>Title 2</h1></body></html>")
        ]

        result = fetcher.fetch()
        assert result.success is True
        assert result.error_count == 1
        assert len(result.articles) == 1
        assert result.articles[0].title == "Title 2"

    @patch.object(XPathListAutoFetcher, "_make_request")
    def test_overall_error_handling(self, mock_request):
        """测试列表页访问或处理抛出致命异常时的捕获机制"""
        mock_request.side_effect = Exception("List page request error!")

        source = ContentSource(
            type="xpath_list_auto",
            src="http://example.com/list",
            metadata={"list_xpath": "//a/@href"}
        )
        fetcher = XPathListAutoFetcher(source)

        result = fetcher.fetch()
        assert result.success is False
        assert "List page request error!" in result.error
        assert len(result.articles) == 0
