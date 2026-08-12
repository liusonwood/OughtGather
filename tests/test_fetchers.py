"""
抓取器测试（使用 mock 模拟 HTTP 请求）
测试 RSSFetcher、WebFetcher、MailFetcher、TrendingFetcher
"""

import json
import pytest
from unittest.mock import MagicMock, patch
from urllib.parse import quote

from src.config import ContentSource
from src.fetchers.base import BaseFetcher, FetchResult, Article, get_fetcher_class
from src.fetchers.rss_fetcher import RSSFetcher
from src.fetchers.web_fetcher import WebFetcher
from src.fetchers.mail_fetcher import MailFetcher
from src.fetchers.trending_fetcher import TrendingFetcher


# =========================================================================
# Article / FetchResult 数据类测试
# =========================================================================

class TestArticle:
    """Article 数据类测试"""

    def test_article_creation(self):
        article = Article(
            title="Test",
            content="<p>Hello</p>",
            url="https://example.com",
        )
        assert article.title == "Test"
        assert article.content == "<p>Hello</p>"
        assert article.url == "https://example.com"
        assert article.author is None
        assert article.images == []
        assert article.metadata == {}

    def test_article_to_dict(self):
        article = Article(
            title="Test",
            content="<p>Hello</p>",
            url="https://example.com",
            author="Author",
        )
        d = article.to_dict()
        assert d["title"] == "Test"
        assert d["url"] == "https://example.com"
        assert d["author"] == "Author"


class TestFetchResult:
    """FetchResult 数据类测试"""

    def test_fetch_result_defaults(self):
        source = ContentSource(type="rss", src="https://example.com")
        result = FetchResult(source=source, articles=[])
        assert result.success is True
        assert result.error is None
        assert result.error_count == 0

    def test_add_error(self):
        source = ContentSource(type="rss", src="https://example.com")
        result = FetchResult(source=source, articles=[])
        result.add_error("Error 1")
        assert result.error == "Error 1"
        assert result.error_count == 1
        result.add_error("Error 2")
        assert "Error 1" in result.error
        assert "Error 2" in result.error
        assert result.error_count == 2


# =========================================================================
# BaseFetcher._should_delete 测试
# =========================================================================

class TestBaseFetcherShouldDelete:
    """BaseFetcher._should_delete 测试"""

    def _make_fetcher(self, source):
        """构造一个具体的 BaseFetcher 子类用于测试"""

        class DummyFetcher(BaseFetcher):
            def fetch(self):
                return FetchResult(source=self.source, articles=[])

        return DummyFetcher(source)

    def test_no_delete_config(self):
        source = ContentSource(type="rss", src="test")
        fetcher = self._make_fetcher(source)
        assert fetcher._should_delete("任何标题") is False

    def test_delete_matches(self):
        source = ContentSource(type="rss", src="test", delete="广告,推广")
        fetcher = self._make_fetcher(source)
        assert fetcher._should_delete("这是一条广告") is True
        assert fetcher._should_delete("推广内容") is True

    def test_delete_no_match(self):
        source = ContentSource(type="rss", src="test", delete="广告,推广")
        fetcher = self._make_fetcher(source)
        assert fetcher._should_delete("正常文章") is False


# =========================================================================
# RSSFetcher 测试
# =========================================================================

def _make_feedparser_dict(d):
    """模拟 feedparser 的 FeedParserDict，同时支持 dict 和属性访问"""
    class FeedParserDict(dict):
        def __getattr__(self, name):
            try:
                return self[name]
            except KeyError:
                raise AttributeError(name)
    return FeedParserDict(d)


class TestRSSFetcher:
    """RSSFetcher 测试（mock feedparser）"""

    @patch("src.fetchers.rss_fetcher.feedparser.parse")
    def test_parse_entries(self, mock_parse, rss_source):
        """测试解析 RSS 条目"""
        # feedparser 返回的对象同时支持 dict 和属性访问
        mock_feed = MagicMock()
        mock_feed.bozo = False
        mock_feed.feed = {"title": "Test Feed"}
        mock_feed.entries = [
            _make_feedparser_dict({
                "title": "Entry 1",
                "link": "https://example.com/1",
                "author": "Author 1",
                "published": "2024-01-01",
                "content": [_make_feedparser_dict({"value": "<p>Content 1</p>"})],
                "tags": [{"term": "python"}],
            }),
            _make_feedparser_dict({
                "title": "Entry 2",
                "link": "https://example.com/2",
                "summary": "<p>Summary 2</p>",
                "tags": [],
            }),
        ]
        mock_parse.return_value = mock_feed

        fetcher = RSSFetcher(rss_source)
        result = fetcher.fetch()

        assert result.success is True
        assert len(result.articles) == 2
        assert result.articles[0].title == "Entry 1"
        assert result.articles[0].content == "<p>Content 1</p>"
        assert result.articles[1].content == "<p>Summary 2</p>"
        assert result.source_title == "Test Feed"

    @patch("src.fetchers.rss_fetcher.feedparser.parse")
    def test_bozo_with_no_entries(self, mock_parse, rss_source):
        """测试 bozo 且无条目时返回失败"""
        mock_parse.return_value = MagicMock(
            bozo=True,
            entries=[],
            bozo_exception="Parse error",
        )

        fetcher = RSSFetcher(rss_source)
        result = fetcher.fetch()

        assert result.success is False
        assert "Failed to parse" in result.error

    @patch("src.fetchers.rss_fetcher.feedparser.parse")
    def test_delete_filters_articles(self, mock_parse):
        """测试 delete 关键词过滤文章"""
        source = ContentSource(
            type="rss", src="https://example.com/rss",
            delete="广告",
        )
        mock_feed = MagicMock()
        mock_feed.bozo = False
        mock_feed.feed = {}
        mock_feed.entries = [
            _make_feedparser_dict({
                "title": "正常文章",
                "content": [_make_feedparser_dict({"value": "<p>OK</p>"})],
                "tags": [],
            }),
            _make_feedparser_dict({
                "title": "这是广告",
                "content": [_make_feedparser_dict({"value": "<p>AD</p>"})],
                "tags": [],
            }),
        ]
        mock_parse.return_value = mock_feed

        fetcher = RSSFetcher(source)
        result = fetcher.fetch()

        assert len(result.articles) == 1
        assert result.articles[0].title == "正常文章"

    @patch("src.fetchers.rss_fetcher.feedparser.parse")
    def test_fallback_summary_fields(self, mock_parse, rss_source):
        """测试 content → summary → description 回退"""
        mock_feed = MagicMock()
        mock_feed.bozo = False
        mock_feed.feed = {}
        mock_feed.entries = [
            _make_feedparser_dict({
                "title": "No Content",
                "description": "<p>Desc</p>",
                "tags": [],
            }),
        ]
        mock_parse.return_value = mock_feed

        fetcher = RSSFetcher(rss_source)
        result = fetcher.fetch()

        assert result.articles[0].content == "<p>Desc</p>"

    @patch("src.fetchers.rss_fetcher.feedparser.parse")
    def test_rss_global_limit(self, mock_parse):
        """测试 RSS 全局抓取上限限制（默认 15 条）"""
        source = ContentSource(type="rss", src="https://example.com/rss")

        # 生成 80 个条目（超过默认的 15 条限制）
        entries = []
        for i in range(80):
            entries.append(_make_feedparser_dict({
                "title": f"Entry {i}",
                "content": [_make_feedparser_dict({"value": f"<p>Content {i}</p>"})],
                "tags": [],
            }))

        mock_feed = MagicMock()
        mock_feed.bozo = False
        mock_feed.feed = {}
        mock_feed.entries = entries
        mock_parse.return_value = mock_feed

        fetcher = RSSFetcher(source, global_limit=15)
        result = fetcher.fetch()

        # 验证只返回 15 条
        assert len(result.articles) == 15
        # 验证返回的是前 15 条
        assert result.articles[0].title == "Entry 0"
        assert result.articles[14].title == "Entry 14"

    @patch("src.fetchers.rss_fetcher.feedparser.parse")
    def test_rss_metadata_limit_override(self, mock_parse):
        """测试通过 metadata.limit 覆盖默认限制"""
        source = ContentSource(
            type="rss",
            src="https://example.com/rss",
            metadata={"limit": 20}
        )

        # 生成 80 个条目
        entries = []
        for i in range(80):
            entries.append(_make_feedparser_dict({
                "title": f"Entry {i}",
                "content": [_make_feedparser_dict({"value": f"<p>Content {i}</p>"})],
                "tags": [],
            }))

        mock_feed = MagicMock()
        mock_feed.bozo = False
        mock_feed.feed = {}
        mock_feed.entries = entries
        mock_parse.return_value = mock_feed

        fetcher = RSSFetcher(source)
        result = fetcher.fetch()

        # 验证返回 20 条（metadata 中设置的限制）
        assert len(result.articles) == 20

    @patch("src.fetchers.rss_fetcher.feedparser.parse")
    def test_rss_fewer_entries_than_limit(self, mock_parse):
        """测试当条目数少于限制时返回全部"""
        source = ContentSource(type="rss", src="https://example.com/rss")

        # 生成 10 个条目（少于 15 条限制）
        entries = []
        for i in range(10):
            entries.append(_make_feedparser_dict({
                "title": f"Entry {i}",
                "content": [_make_feedparser_dict({"value": f"<p>Content {i}</p>"})],
                "tags": [],
            }))

        mock_feed = MagicMock()
        mock_feed.bozo = False
        mock_feed.feed = {}
        mock_feed.entries = entries
        mock_parse.return_value = mock_feed

        fetcher = RSSFetcher(source, global_limit=15)
        result = fetcher.fetch()

        # 验证返回全部 10 条
        assert len(result.articles) == 10


class TestTrendingFetcher:
    """TrendingFetcher 测试"""

    @patch.dict("os.environ", {"OPENROUTER_API_KEY": "test-key"})
    @patch("src.fetchers.trending_fetcher.httpx.Client")
    def test_trending_title_extraction_plain_text(self, mock_client_cls):
        """测试 TrendingFetcher 能够将纯文本首行作为标题提取"""
        source = ContentSource(type="trending", src="AI trends", goal="Analyze AI")
        
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.json.return_value = {
            "choices": [{
                "message": {
                    "content": "人工智能最新发展趋势报告\n\n- 趋势1\n- 趋势2"
                }
            }]
        }
        mock_client = MagicMock()
        mock_client.post.return_value = mock_response
        mock_client.__enter__.return_value = mock_client
        mock_client_cls.return_value = mock_client

        fetcher = TrendingFetcher(source)
        result = fetcher.fetch()

        assert result.success is True
        assert len(result.articles) == 1
        assert result.articles[0].title == "人工智能最新发展趋势报告"
        assert "人工智能最新发展趋势报告" not in result.articles[0].content

    @patch.dict("os.environ", {"OPENROUTER_API_KEY": "test-key"})
    @patch("src.fetchers.trending_fetcher.httpx.Client")
    def test_trending_title_extraction_markdown_and_bold(self, mock_client_cls):
        """测试 TrendingFetcher 能够处理 Markdown 标题和加粗首行"""
        source = ContentSource(type="trending", src="AI trends", goal="Analyze AI")
        
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.json.return_value = {
            "choices": [{
                "message": {
                    "content": "**大模型演进分析**\n\n正文内容..."
                }
            }]
        }
        mock_client = MagicMock()
        mock_client.post.return_value = mock_response
        mock_client.__enter__.return_value = mock_client
        mock_client_cls.return_value = mock_client

        fetcher = TrendingFetcher(source)
        result = fetcher.fetch()

        assert result.success is True
        assert len(result.articles) == 1
        assert result.articles[0].title == "大模型演进分析"



# =========================================================================
# WebFetcher 测试
# =========================================================================

class TestWebFetcher:
    """WebFetcher 测试（mock httpx）"""

    @patch("src.fetchers.web_fetcher.trafilatura.extract")
    @patch.object(WebFetcher, "_make_request")
    def test_extract_content(self, mock_request, mock_extract, web_source):
        """测试网页正文提取"""
        mock_response = MagicMock()
        mock_response.text = "<html><body><article><p>正文</p></article></body></html>"
        mock_request.return_value = mock_response
        mock_extract.return_value = "<p>正文</p>" + "x" * 300

        fetcher = WebFetcher(web_source)
        result = fetcher.fetch()

        assert result.success is True
        assert len(result.articles) == 1
        assert result.articles[0].content == "<p>正文</p>" + "x" * 300

    @patch("src.fetchers.web_fetcher.trafilatura.extract")
    @patch.object(WebFetcher, "_make_request")
    def test_trafilatura_fails_empty_content(self, mock_request, mock_extract, web_source):
        """trafilatura 失败时，内容为空，不生成文章"""
        mock_response = MagicMock()
        mock_response.text = "<html><body><article><p>内容</p></article></body></html>"
        mock_request.return_value = mock_response
        mock_extract.return_value = None  # trafilatura 失败

        fetcher = WebFetcher(web_source)
        result = fetcher.fetch()

        assert result.success is False
        assert len(result.articles) == 0

    @patch.object(WebFetcher, "_make_request")
    def test_extract_title_from_h1(self, mock_request):
        """测试从 <h1> 提取标题"""
        source = ContentSource(type="web", src="https://example.com")
        mock_response = MagicMock()
        mock_response.text = "<html><body><h1>文章标题</h1><article><p>内容</p></article></body></html>"
        mock_request.return_value = mock_response

        with patch("src.fetchers.web_fetcher.trafilatura.extract", return_value="<p>内容</p>"):
            fetcher = WebFetcher(source)
            result = fetcher.fetch()
            assert result.articles[0].title == "文章标题"

    @patch.object(WebFetcher, "_make_request")
    def test_title_fallback_to_config(self, mock_request):
        """测试标题回退到配置中的 title"""
        source = ContentSource(type="web", src="https://example.com", title="自定义标题")
        mock_response = MagicMock()
        mock_response.text = "<html><body><p>无标题的页面</p></body></html>"
        mock_request.return_value = mock_response

        with patch("src.fetchers.web_fetcher.trafilatura.extract", return_value="<p>内容</p>"):
            fetcher = WebFetcher(source)
            result = fetcher.fetch()
            # 没有 <title>/<h1>/og:title 时回退到 source.title
            assert result.articles[0].title == "自定义标题"

    @patch.object(WebFetcher, "_make_request")
    def test_images_from_raw_html(self, mock_request):
        """图片从原始 HTML 提取，不依赖 trafilatura 的输出"""
        source = ContentSource(type="web", src="https://example.com/article")
        mock_response = MagicMock()
        # raw HTML 有图片
        mock_response.text = (
            "<html><body><article>"
            "<h1>Article</h1>"
            "<img src='https://example.com/photo.jpg'/>"
            "<p>Some content here.</p>"
            "</article></body></html>"
        )
        mock_request.return_value = mock_response

        # trafilatura 返回的正文不含图片
        with patch(
            "src.fetchers.web_fetcher.trafilatura.extract",
            return_value="<p>Some content here.</p>",
        ):
            fetcher = WebFetcher(source)
            result = fetcher.fetch()

            assert result.success is True
            # 内容用 trafilatura 的（不含 <img>）
            assert result.articles[0].content == "<p>Some content here.</p>"
            # 图片从原始 HTML 取回
            assert "https://example.com/photo.jpg" in result.articles[0].images


# =========================================================================
# MailFetcher 测试
# =========================================================================

class TestMailFetcher:
    """MailFetcher 测试（mock httpx + API key）"""

    @patch.dict("os.environ", {"TESTMAIL_APP_API_KEY": "test_key_123"})
    @patch.object(MailFetcher, "_make_request")
    def test_fetch_emails(self, mock_request, mail_source):
        """测试邮件抓取"""
        mock_response = MagicMock()
        mock_response.json.return_value = {
            "result": "success",
            "emails": [
                {
                    "subject": "邮件 1",
                    "from": "sender@example.com",
                    "to": "test@testmail.app",
                    "timestamp": "2024-01-01T00:00:00Z",
                    "html": "<p>邮件内容</p>",
                    "attachments": [],
                }
            ],
        }
        mock_request.return_value = mock_response

        fetcher = MailFetcher(mail_source)
        result = fetcher.fetch()

        assert result.success is True
        assert len(result.articles) == 1
        assert result.articles[0].title == "邮件 1"
        assert result.articles[0].author == "sender@example.com"

    @patch.dict("os.environ", {"TESTMAIL_APP_API_KEY": "test_key_123"})
    @patch.object(MailFetcher, "_make_request")
    def test_api_error(self, mock_request, mail_source):
        """测试 API 返回错误"""
        mock_response = MagicMock()
        mock_response.json.return_value = {
            "result": "error",
            "message": "Invalid API key",
        }
        mock_request.return_value = mock_response

        fetcher = MailFetcher(mail_source)
        result = fetcher.fetch()

        assert result.success is False
        assert "Invalid API key" in result.error

    @patch.dict("os.environ", {}, clear=True)
    def test_no_api_key(self, mail_source, monkeypatch):
        """测试未配置 API key 时跳过"""
        monkeypatch.delenv("TESTMAIL_APP_API_KEY", raising=False)

        fetcher = MailFetcher(mail_source)
        result = fetcher.fetch()

        assert result.success is False
        assert "not configured" in result.error

    @patch.dict("os.environ", {"TESTMAIL_APP_API_KEY": "test_key_123"})
    @patch.object(MailFetcher, "_make_request")
    def test_namespace_url_encoded(self, mock_request):
        """测试 namespace.tag 格式被正确拆分"""
        source = ContentSource(
            type="mail", src="my.namespace",
            title="Test",
        )
        mock_response = MagicMock()
        mock_response.json.return_value = {"result": "success", "emails": []}
        mock_request.return_value = mock_response

        fetcher = MailFetcher(source)
        result = fetcher.fetch()

        # 验证 namespace 和 tag 被正确拆分
        call_args = mock_request.call_args
        api_url = call_args[0][0]
        assert "namespace=my" in api_url
        assert "tag=namespace" in api_url

    @patch.dict("os.environ", {"TESTMAIL_APP_API_KEY": "test_key_123"})
    @patch.object(MailFetcher, "_make_request")
    def test_metadata_query_params(self, mock_request):
        """测试 metadata 参数正确构建到请求 URL 中"""
        source = ContentSource(
            type="mail", src="testns",
            metadata={"tag": "daily", "limit": 10, "timestamp_from": 1718300000000},
        )
        mock_response = MagicMock()
        mock_response.json.return_value = {"result": "success", "emails": []}
        mock_request.return_value = mock_response

        fetcher = MailFetcher(source)
        result = fetcher.fetch()

        api_url = mock_request.call_args[0][0]
        assert "tag=daily" in api_url
        assert "limit=10" in api_url
        assert "timestamp_from=1718300000000" in api_url

    @patch.dict("os.environ", {"TESTMAIL_APP_API_KEY": "test_key_123"})
    def test_extract_images_skips_social_and_tracking(self):
        """邮件头社交图标与 1x1 跟踪像素不应进入 article.images"""
        source = ContentSource(type="mail", src="ns.tag")
        fetcher = MailFetcher(source)
        html = """
        <html><body>
          <img alt="share on facebook" width="18"
               src="https://media.example.com/static_assets/header/facebook.png"
               style="width:18px;height:18px">
          <img alt="share on twitter" width="18"
               src="https://media.example.com/static_assets/header/x.png">
          <img src="https://track.example.com/o/pixel.gif" width="1" height="1">
          <img src="https://cdn.example.com/article-hero.jpg" width="630" alt="hero">
        </body></html>
        """
        images = fetcher._extract_images(html)
        assert images == ["https://cdn.example.com/article-hero.jpg"]

    @patch.dict("os.environ", {"TESTMAIL_APP_API_KEY": "test_key_123"})
    def test_parse_email_filters_social_from_image_list(self):
        """_parse_email 提取的 images 不应以社交图标为首图"""
        source = ContentSource(type="mail", src="ns.tag")
        fetcher = MailFetcher(source)
        email = {
            "subject": "Newsletter",
            "from": "news@example.com",
            "to": "me@testmail.app",
            "timestamp": "2024-01-01T00:00:00Z",
            "html": """
            <html><body>
              <img alt="share on facebook" width="18"
                   src="https://media.beehiiv.com/static_assets/header/facebook.png">
              <img src="https://cdn.example.com/real-content.png" width="630">
              <p>Hello</p>
            </body></html>
            """,
            "attachments": [],
        }
        article = fetcher._parse_email(email)
        assert article.images
        assert "facebook.png" not in article.images[0]
        assert any("real-content.png" in u for u in article.images)


# =========================================================================
# TrendingFetcher 测试
# =========================================================================

class TestTrendingFetcher:
    """TrendingFetcher 测试（mock httpx + API key）"""

    @patch.dict("os.environ", {"OPENROUTER_API_KEY": "test_key_456", "TAVILY_API_KEY": "tavily_key_123"})
    @patch("httpx.Client")
    def test_fetch_analysis(self, mock_client_cls, trending_source):
        """测试 LLM 分析请求（带搜索）"""
        mock_client = MagicMock()
        mock_client.__enter__ = MagicMock(return_value=mock_client)
        mock_client.__exit__ = MagicMock(return_value=False)
        
        # 定义按顺序的响应：第一个是 Tavily 搜索，第二个是 OpenRouter LLM
        mock_search_response = MagicMock()
        mock_search_response.status_code = 200
        mock_search_response.json.return_value = {
            "results": [{"title": "Search 1", "content": "Search content 1"}]
        }
        
        mock_llm_response = MagicMock()
        mock_llm_response.status_code = 200
        mock_llm_response.json.return_value = {
            "choices": [
                {
                    "message": {
                        "content": "# AI 趋势\n\n根据搜索内容: Search content 1"
                    }
                }
            ]
        }
        
        # 按调用顺序配置 side_effect
        mock_client.post.side_effect = [mock_search_response, mock_llm_response]
        mock_client_cls.return_value = mock_client

        fetcher = TrendingFetcher(trending_source)
        result = fetcher.fetch()

        assert result.success is True
        
        # 验证发送给 LLM 的 payload 包含搜索结果
        llm_call = mock_client.post.call_args_list[1]
        payload = llm_call.kwargs["json"]
        user_message = payload["messages"][1]["content"]
        assert "Search content 1" in user_message
        
        assert len(result.articles) == 1
        assert "has_search_context" in result.articles[0].metadata
        assert result.articles[0].metadata["has_search_context"] is True
        assert "Search content 1" in result.articles[0].content
        # 作者应使用实际调用的 LLM 模型名称
        assert result.articles[0].author == "openai/gpt-4o"
        assert result.articles[0].metadata["model"] == "openai/gpt-4o"


    @patch.dict("os.environ", {}, clear=True)
    def test_no_api_key(self, trending_source, monkeypatch):
        """测试未配置 API key"""
        monkeypatch.delenv("OPENROUTER_API_KEY", raising=False)

        fetcher = TrendingFetcher(trending_source)
        result = fetcher.fetch()

        assert result.success is False
        assert "not configured" in result.error

    @patch.dict("os.environ", {"OPENROUTER_API_KEY": "test_key_456"})
    def test_title_default(self, monkeypatch):
        """测试 trending 默认标题"""
        source = ContentSource(
            type="trending", src="AI 趋势",
            goal="分析 AI",
        )
        with patch("src.fetchers.trending_fetcher.TrendingFetcher._call_llm_api", return_value=("<p>内容</p>", "test-model", None)):
            fetcher = TrendingFetcher(source)
            result = fetcher.fetch()
            assert result.articles[0].title == "热点分析: AI 趋势"
            assert result.articles[0].author == "test-model"

    @patch.dict("os.environ", {"OPENROUTER_API_KEY": "test_key_456"})
    @patch("httpx.Client")
    def test_trending_fetcher_title_extraction(self, mock_client_cls):
        """测试 TrendingFetcher 自动从首行 # 或 ## 提取标题并从正文中去除"""
        # Case 1: # 开头
        mock_client = MagicMock()
        mock_client.__enter__ = MagicMock(return_value=mock_client)
        mock_client.__exit__ = MagicMock(return_value=False)
        
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.json.return_value = {
            "choices": [
                {
                    "message": {
                        "content": "# Extracted Title 1\n\nThis is the main content body."
                    }
                }
            ]
        }
        mock_client.post.return_value = mock_response
        mock_client_cls.return_value = mock_client

        source = ContentSource(type="trending", src="AI 趋势", goal="分析 AI")
        fetcher = TrendingFetcher(source)
        result = fetcher.fetch()
        
        assert result.success is True
        assert result.articles[0].title == "Extracted Title 1"
        assert "<h1>Extracted Title 1</h1>" not in result.articles[0].content
        assert "This is the main content body." in result.articles[0].content

        # Case 2: ## 开头
        mock_response.json.return_value = {
            "choices": [
                {
                    "message": {
                        "content": "## Extracted Title 2\n\nThis is the second content body."
                    }
                }
            ]
        }
        result = fetcher.fetch()
        assert result.success is True
        assert result.articles[0].title == "Extracted Title 2"
        assert "<h2>Extracted Title 2</h2>" not in result.articles[0].content
        assert "This is the second content body." in result.articles[0].content

        # Case 3: ### 开头 (现在应提取为标题并从正文中去除)
        mock_response.json.return_value = {
            "choices": [
                {
                    "message": {
                        "content": "### Header 3\n\nThis is the third content body."
                    }
                }
            ]
        }
        result = fetcher.fetch()
        assert result.success is True
        assert result.articles[0].title == "Header 3"  # 现在应提取为标题
        assert "<h3>Header 3</h3>" not in result.articles[0].content # 并从正文中去除
        assert "This is the third content body." in result.articles[0].content

        # Case 4: 带自定义标题 (自定义标题仅作为大章节标题，不覆盖从 AI 回复中提取的文章标题)
        source_with_title = ContentSource(type="trending", src="AI 趋势", goal="分析 AI", title="Custom Title Override")
        fetcher_with_title = TrendingFetcher(source_with_title)
        mock_response.json.return_value = {
            "choices": [
                {
                    "message": {
                        "content": "# Extracted Title 4\n\nContent details."
                    }
                }
            ]
        }
        result = fetcher_with_title.fetch()
        assert result.success is True
        assert result.articles[0].title == "Extracted Title 4"  # 优先使用 AI 回复提取出的文章标题，不被 source.title 覆盖
        assert "<h1>Extracted Title 4</h1>" not in result.articles[0].content  # 但第一行仍应从正文中去除
        assert "Content details." in result.articles[0].content

        # Case 5: 带自定义标题但 AI 未能提取出文章标题
        source_no_extracted = ContentSource(type="trending", src="AI 趋势", goal="分析 AI", title="Custom Section Title")
        fetcher_no_extracted = TrendingFetcher(source_no_extracted)
        with patch("src.fetchers.trending_fetcher.TrendingFetcher._call_llm_api", return_value=("<p>内容</p>", "test-model", None)):
            result = fetcher_no_extracted.fetch()
            assert result.success is True
            assert result.articles[0].title == "热点分析: AI 趋势"

    @patch.dict("os.environ", {"OPENROUTER_API_KEY": "test_key_456"})
    def test_format_as_html_paragraphs(self, trending_source):
        """测试文本转 HTML 的段落处理"""
        fetcher = TrendingFetcher(trending_source)
        text = "第一段内容\n\n第二段内容\n\n第三段内容"
        html = fetcher._format_as_html(text)
        assert "<p>第一段内容</p>" in html
        assert "<p>第二段内容</p>" in html
        assert "<p>第三段内容</p>" in html

    @patch.dict("os.environ", {"OPENROUTER_API_KEY": "test_key_456"})
    def test_format_as_html_headings(self, trending_source):
        """测试文本转 HTML 的标题处理"""
        fetcher = TrendingFetcher(trending_source)
        text = "# 一级标题\n\n内容\n\n## 二级标题\n\n更多内容"
        html = fetcher._format_as_html(text)
        assert "<h1>一级标题</h1>" in html
        assert "<h2>二级标题</h2>" in html

    @patch.dict("os.environ", {"OPENROUTER_API_KEY": "test_key_456"})
    def test_format_as_html_list(self, trending_source):
        """测试文本转 HTML 的列表处理"""
        fetcher = TrendingFetcher(trending_source)
        text = "- 项目一\n- 项目二\n- 项目三"
        html = fetcher._format_as_html(text)
        assert "<ul>" in html
        assert "<li>项目一</li>" in html
        assert "<li>项目二</li>" in html
        assert "</ul>" in html

    @patch.dict("os.environ", {"OPENROUTER_API_KEY": "test_key_456"})
    def test_get_target_language(self):
        """测试 _get_target_language 功能"""
        from src.config import ContentSource
        
        # 1. 测试 metadata.language 指定语言
        source_cn = ContentSource(
            type="trending", src="AI 趋势", goal="分析 AI",
            metadata={"language": "Chinese"}
        )
        fetcher_cn = TrendingFetcher(source_cn)
        assert fetcher_cn._get_target_language() == "Chinese"

        source_en = ContentSource(
            type="trending", src="AI 趋势", goal="分析 AI",
            metadata={"language": "English"}
        )
        fetcher_en = TrendingFetcher(source_en)
        assert fetcher_en._get_target_language() == "English"

        # 2. 测试根据时区自动识别 (mock astimezone)
        source_auto = ContentSource(
            type="trending", src="AI 趋势", goal="分析 AI",
            metadata={"language": "auto"}
        )
        fetcher_auto = TrendingFetcher(source_auto)

        # Mock tzname and utcoffset to simulate China Standard Time (CST with positive offset)
        mock_dt = MagicMock()
        mock_dt.tzname.return_value = "CST"
        mock_dt.utcoffset.return_value.total_seconds.return_value = 28800.0
        
        with patch("src.fetchers.trending_fetcher.datetime") as mock_datetime:
            mock_datetime.now.return_value.astimezone.return_value = mock_dt
            assert fetcher_auto._get_target_language() == "Chinese"

        # Mock tzname and utcoffset to simulate US Central Standard Time (CST with negative offset)
        mock_dt = MagicMock()
        mock_dt.tzname.return_value = "CST"
        mock_dt.utcoffset.return_value.total_seconds.return_value = -21600.0
        
        with patch("src.fetchers.trending_fetcher.datetime") as mock_datetime:
            mock_datetime.now.return_value.astimezone.return_value = mock_dt
            assert fetcher_auto._get_target_language() == "English"

        # Mock other standard English timezones
        for tz in ["EST", "GMT", "UTC"]:
            mock_dt = MagicMock()
            mock_dt.tzname.return_value = tz
            mock_dt.utcoffset.return_value = None  # standard UTC might not have offset or can be mocked
            with patch("src.fetchers.trending_fetcher.datetime") as mock_datetime:
                mock_datetime.now.return_value.astimezone.return_value = mock_dt
                assert fetcher_auto._get_target_language() == "English"

        # Mock other timezones that default to Chinese
        mock_dt = MagicMock()
        mock_dt.tzname.return_value = "Asia/Shanghai"
        mock_dt.utcoffset.return_value.total_seconds.return_value = 28800.0
        with patch("src.fetchers.trending_fetcher.datetime") as mock_datetime:
            mock_datetime.now.return_value.astimezone.return_value = mock_dt
            assert fetcher_auto._get_target_language() == "Chinese"


# =========================================================================
# Plugin Registry / Dynamic Loading Tests
# =========================================================================

class TestFetcherPlugins:
    """测试抓取器插件机制"""

    def test_built_in_fetchers_registered(self):
        """测试内置抓取器是否成功注册"""
        assert get_fetcher_class("mail") is MailFetcher
        assert get_fetcher_class("rss") is RSSFetcher
        assert get_fetcher_class("web") is WebFetcher
        assert get_fetcher_class("trending") is TrendingFetcher
        assert get_fetcher_class("nonexistent") is None

    def test_custom_fetcher_auto_registration(self):
        """测试自定义抓取器是否能通过 subclass 自动注册"""
        class DummyCustomFetcher(BaseFetcher):
            type_name = "dummy_custom"

            def fetch(self):
                return FetchResult(source=self.source, articles=[])

        assert get_fetcher_class("dummy_custom") is DummyCustomFetcher

        # 清理注册表，避免影响其他测试
        from src.fetchers.base import _registry
        if "dummy_custom" in _registry:
            del _registry["dummy_custom"]

