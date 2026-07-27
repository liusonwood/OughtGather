import pytest
from unittest.mock import MagicMock, patch
from src.config import ContentSource
from src.fetchers.twitter_fetcher import TwitterFetcher
from src.fetchers.base import FetchResult

# Mock RSS XML content
MOCK_RSS_XML = """<?xml version="1.0" encoding="UTF-8"?>
<rss xmlns:atom="http://www.w3.org/2005/Atom" xmlns:dc="http://purl.org/dc/elements/1.1/" version="2.0">
  <channel>
    <title>Wolfram Research (@WolframResearch)</title>
    <link>https://nitter.privacydev.net/WolframResearch</link>
    <description>Twitter feed for Wolfram Research</description>
    <language>en-us</language>
    <item>
      <title>RT by @WolframResearch: Check out this awesome post about physics! #science</title>
      <description><![CDATA[Check out this awesome post about physics! <a href="https://nitter.privacydev.net/WolframResearch">#science</a>]]></description>
      <link>https://nitter.privacydev.net/WolframResearch/status/1111111111111111111#m</link>
      <guid>https://nitter.privacydev.net/WolframResearch/status/1111111111111111111#m</guid>
      <pubDate>Mon, 27 Jul 2026 10:00:00 GMT</pubDate>
      <dc:creator>@SomeoneElse</dc:creator>
    </item>
    <item>
      <title>R to @some_user: We are working on a fix for that issue. Stay tuned!</title>
      <description><![CDATA[We are working on a fix for that issue. <a href="https://nitter.privacydev.net/some_user">@some_user</a>]]></description>
      <link>https://nitter.privacydev.net/WolframResearch/status/2222222222222222222#m</link>
      <guid>https://nitter.privacydev.net/WolframResearch/status/2222222222222222222#m</guid>
      <pubDate>Mon, 27 Jul 2026 11:00:00 GMT</pubDate>
      <dc:creator>@WolframResearch</dc:creator>
    </item>
    <item>
      <title>This is a normal tweet! Check our blog for the latest update. It is extremely long and will definitely exceed eighty characters in length to test the truncation logic of the TwitterFetcher.</title>
      <description><![CDATA[This is a normal tweet! Check our blog for <img src="/pic/1.jpg" /> the latest update. <p>It is extremely long and will definitely exceed eighty characters in length to test the truncation logic of the TwitterFetcher.</p>]]></description>
      <link>https://nitter.privacydev.net/WolframResearch/status/3333333333333333333#m</link>
      <guid>https://nitter.privacydev.net/WolframResearch/status/3333333333333333333#m</guid>
      <pubDate>Mon, 27 Jul 2026 12:00:00 GMT</pubDate>
      <dc:creator>@WolframResearch</dc:creator>
    </item>
    <item>
      <title></title>
      <description><![CDATA[]]></description>
      <link>https://nitter.privacydev.net/WolframResearch/status/4444444444444444444#m</link>
      <guid>https://nitter.privacydev.net/WolframResearch/status/4444444444444444444#m</guid>
      <pubDate>Mon, 27 Jul 2026 13:00:00 GMT</pubDate>
      <dc:creator>@WolframResearch</dc:creator>
    </item>
  </channel>
</rss>
"""


class TestTwitterFetcher:
    """TwitterFetcher 单元测试"""

    @pytest.mark.parametrize(
        "input_src,expected_username",
        [
            ("WolframResearch", "WolframResearch"),
            (" @WolframResearch ", "WolframResearch"),
            ("https://x.com/WolframResearch", "WolframResearch"),
            ("https://twitter.com/WolframResearch", "WolframResearch"),
            ("https://xcancel.com/WolframResearch/rss", "WolframResearch"),
            ("https://twitter.com/WolframResearch/status/12345678", "WolframResearch"),
            ("https://x.com", ""),
            ("", ""),
        ],
    )
    def test_extract_username(self, input_src, expected_username):
        """测试从各种形式 of src 中正确提取 X/Twitter 用户名"""
        source = ContentSource(type="twitter", src="WolframResearch")
        fetcher = TwitterFetcher(source)
        assert fetcher._extract_username(input_src) == expected_username

    def test_fetch_invalid_username(self):
        """测试用户名无效时，fetch 应该失败"""
        source = ContentSource(type="twitter", src="https://x.com")
        fetcher = TwitterFetcher(source)
        result = fetcher.fetch()
        assert result.success is False
        assert "src 无法识别出有效的 X/Twitter 用户名" in result.error

    @patch.object(TwitterFetcher, "_make_request")
    def test_fetch_all_nodes_fail(self, mock_make_request):
        """测试所有候选 Nitter/xcancel 节点都抓取失败的情况"""
        # 模拟所有请求均抛出异常
        mock_make_request.side_effect = Exception("Connection refused")

        source = ContentSource(type="twitter", src="WolframResearch")
        fetcher = TwitterFetcher(source)
        result = fetcher.fetch()

        assert result.success is False
        assert "所有候选 Nitter/xcancel 节点均抓取失败" in result.error
        assert "Connection refused" in result.error

    @patch.object(TwitterFetcher, "_make_request")
    def test_fetch_custom_instance_priority_and_failover(self, mock_make_request):
        """测试自定义节点优先抓取，且在首个节点失败时自动无缝切换到备用节点"""
        # 1. 模拟第一个自定义节点访问报错
        # 2. 模拟第二个节点返回不合规 HTML
        # 3. 模拟第三个节点成功返回 XML
        resp_fail_format = MagicMock()
        resp_fail_format.text = "<html>only works inside an rss client</html>"

        resp_success = MagicMock()
        resp_success.text = MOCK_RSS_XML

        mock_make_request.side_effect = [
            Exception("Custom instance down"),  # 自定义节点报错
            resp_fail_format,                  # 第一个默认节点不合规
            resp_success                       # 第二个默认节点成功
        ]

        # 自定义节点无 https 前缀，验证自动拼接和尾部斜杠清理
        source = ContentSource(
            type="twitter",
            src="WolframResearch",
            metadata={"nitter_instance": "my-nitter.com/"}
        )
        fetcher = TwitterFetcher(source)
        result = fetcher.fetch()

        assert result.success is True
        assert len(result.articles) > 0
        # 验证调用详情：
        # 第一个请求应该是自定义节点 my-nitter.com
        assert mock_make_request.call_args_list[0][0][0] == "https://my-nitter.com/WolframResearch/rss"
        # 最后的 article metadata 应该记录了真正抓取成功的节点
        assert result.articles[0].metadata["instance_used"] in fetcher.DEFAULT_NODES

    @patch.object(TwitterFetcher, "_make_request")
    def test_fetch_filtering_and_parsing(self, mock_make_request):
        """测试推文解析、排除回复、排除转推、URL 转换、图片提取以及标题截断和兜底"""
        resp_success = MagicMock()
        resp_success.text = MOCK_RSS_XML
        mock_make_request.return_value = resp_success

        # 默认不排除回复和转推
        source = ContentSource(
            type="twitter",
            src="WolframResearch",
            metadata={
                "exclude_replies": False,
                "exclude_rts": False
            }
        )
        fetcher = TwitterFetcher(source)
        result = fetcher.fetch()

        assert result.success is True
        assert result.source_title == "Wolfram Research (@WolframResearch)"
        assert len(result.articles) == 4

        # 验证第一个推文（转推）：
        rt_article = result.articles[0]
        assert rt_article.author == "@SomeoneElse"
        assert rt_article.url == "https://x.com/SomeoneElse/status/1111111111111111111"
        assert "Check out this awesome post" in rt_article.title

        # 验证第二个推文（回复）：
        reply_article = result.articles[1]
        assert reply_article.author == "@WolframResearch"
        assert reply_article.url == "https://x.com/WolframResearch/status/2222222222222222222"

        # 验证第三个推文（普通长文）：
        normal_article = result.articles[2]
        assert len(normal_article.title) <= 83  # 80 chars + "..."
        assert normal_article.title.endswith("...")
        # 图片相对地址转换为绝对地址
        assert normal_article.images == [f"{fetcher.DEFAULT_NODES[0]}/pic/1.jpg"]

        # 验证第四个推文（空正文，自动兜底标题）：
        empty_article = result.articles[3]
        assert empty_article.title == "X 推文由 @WolframResearch 发布"

    @patch.object(TwitterFetcher, "_make_request")
    def test_exclude_replies_and_rts(self, mock_make_request):
        """测试开启 exclude_replies 和 exclude_rts 时的过滤效果"""
        resp_success = MagicMock()
        resp_success.text = MOCK_RSS_XML
        mock_make_request.return_value = resp_success

        source = ContentSource(
            type="twitter",
            src="WolframResearch",
            metadata={
                "exclude_replies": True,
                "exclude_rts": True
            }
        )
        fetcher = TwitterFetcher(source)
        result = fetcher.fetch()

        assert result.success is True
        # 原本4条，排除了1条RT和1条Reply，应当剩余2条
        assert len(result.articles) == 2
        for article in result.articles:
            assert not article.title.startswith("RT by @")
            assert not article.title.startswith("R to @")

    @patch.object(TwitterFetcher, "_make_request")
    def test_global_limit(self, mock_make_request):
        """测试全局条数限制"""
        resp_success = MagicMock()
        resp_success.text = MOCK_RSS_XML
        mock_make_request.return_value = resp_success

        # 设置 global_limit 为 1
        source = ContentSource(type="twitter", src="WolframResearch")
        fetcher = TwitterFetcher(source, global_limit=1)
        result = fetcher.fetch()

        assert result.success is True
        assert len(result.articles) == 1

    @patch.object(TwitterFetcher, "_make_request")
    def test_delete_keywords_filtering(self, mock_make_request):
        """测试 delete 过滤关键字功能"""
        resp_success = MagicMock()
        resp_success.text = MOCK_RSS_XML
        mock_make_request.return_value = resp_success

        # 配置过滤含有 "physics" 的推文（转推命中）
        source = ContentSource(
            type="twitter",
            src="WolframResearch",
            delete="physics"
        )
        fetcher = TwitterFetcher(source)
        result = fetcher.fetch()

        assert result.success is True
        # 原本4条，排除了含 "physics" 的推文，剩下3条
        assert len(result.articles) == 3
        for article in result.articles:
            assert "physics" not in article.title

    @patch.object(TwitterFetcher, "_make_request")
    def test_metadata_limit_override(self, mock_make_request):
        """测试 metadata.limit 覆盖 global_limit"""
        resp_success = MagicMock()
        resp_success.text = MOCK_RSS_XML
        mock_make_request.return_value = resp_success

        source = ContentSource(
            type="twitter",
            src="WolframResearch",
            metadata={"limit": 2}
        )
        fetcher = TwitterFetcher(source, global_limit=15)
        result = fetcher.fetch()

        assert result.success is True
        assert len(result.articles) == 2

    @patch.object(TwitterFetcher, "_make_request")
    def test_xml_parse_failure(self, mock_make_request):
        """测试 XML 损坏导致 BeautifulSoup 解析报错时的异常处理"""
        resp_corrupted = MagicMock()
        resp_corrupted.text = "<rss><channel><item>不完整闭合"
        mock_make_request.return_value = resp_corrupted

        source = ContentSource(type="twitter", src="WolframResearch")
        fetcher = TwitterFetcher(source)
        result = fetcher.fetch()

        # xml 解析容错性高，BeautifulSoup xml parser 可能仍然返回成功（但没有 channel 或 items），
        # 或者在更极端的情况下报错。不管怎样，我们通过 mock 让 soup.find 报错来模拟。
        with patch("src.fetchers.twitter_fetcher.BeautifulSoup", side_effect=Exception("Parsing failed")):
            result = fetcher.fetch()
            assert result.success is False
            assert "XML 解析错误" in result.error
