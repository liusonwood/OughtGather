import pytest
from unittest.mock import MagicMock, patch
from src.config import ContentSource
from src.fetchers.telegram_fetcher import TelegramFetcher
from src.fetchers.base import FetchResult, Article

# 模拟 Telegram RSSHub XML 内容
MOCK_TELEGRAM_XML = """<?xml version="1.0" encoding="UTF-8"?>
<rss version="2.0">
  <channel>
    <title>Durov's Channel</title>
    <link>https://t.me/durov</link>
    <description>Official channel of Pavel Durov</description>
    <item>
      <title>Normal message with some text</title>
      <description><![CDATA[This is a normal message <img src="photo/1.jpg" /> content from Pavel Durov.]]></description>
      <link>https://t.me/durov/100</link>
      <guid>https://t.me/durov/100</guid>
      <pubDate>Mon, 27 Jul 2026 10:00:00 GMT</pubDate>
      <author>Pavel Durov</author>
    </item>
    <item>
      <title>Another message with content tag</title>
      <content:encoded xmlns:content="http://purl.org/rss/1.0/modules/content/"><![CDATA[This content uses the content tag directly. <img src="https://example.com/logo.png" />]]></content:encoded>
      <link>https://t.me/durov/101</link>
      <pubDate>Mon, 27 Jul 2026 11:00:00 GMT</pubDate>
    </item>
    <item>
      <title>Deleted Message</title>
      <description><![CDATA[This contains spam or delete keyword.]]></description>
      <link>https://t.me/durov/102</link>
      <pubDate>Mon, 27 Jul 2026 12:00:00 GMT</pubDate>
    </item>
    <item>
      <title>Empty Content Message</title>
      <link>https://t.me/durov/103</link>
      <pubDate>Mon, 27 Jul 2026 13:00:00 GMT</pubDate>
    </item>
  </channel>
</rss>
"""

class TestTelegramFetcher:
    """TelegramFetcher 单元测试"""

    def test_empty_channel_id(self):
        """测试频道 ID 为空时的处理"""
        source = ContentSource(type="telegram", src="  ")
        fetcher = TelegramFetcher(source)
        result = fetcher.fetch()
        assert result.success is False
        assert "cannot be empty" in result.error

    def test_invalid_channel_id(self):
        """测试无效的频道 ID 提取"""
        source = ContentSource(type="telegram", src="https://t.me/@")
        fetcher = TelegramFetcher(source)
        result = fetcher.fetch()
        assert result.success is False
        assert "Invalid Telegram channel ID" in result.error

    @patch.object(TelegramFetcher, "_make_request")
    def test_fetch_all_nodes_fail(self, mock_make_request):
        """测试所有候选 RSSHub 节点均抓取失败"""
        mock_make_request.side_effect = Exception("Connection timeout")

        source = ContentSource(type="telegram", src="durov")
        fetcher = TelegramFetcher(source)
        result = fetcher.fetch()

        assert result.success is False
        assert "All RSSHub nodes failed" in result.error
        assert "Connection timeout" in result.error

    @patch.object(TelegramFetcher, "_make_request")
    def test_no_valid_hosts(self, mock_make_request):
        """测试没有任何有效的 RSSHub 节点可用时的处理"""
        source = ContentSource(type="telegram", src="durov", metadata={"rsshub_host": ""})
        fetcher = TelegramFetcher(source)
        # 临时清空默认节点列表
        with patch.object(TelegramFetcher, "DEFAULT_NODES", []):
            result = fetcher.fetch()
            assert result.success is False
            assert "No valid RSSHub hosts available" in result.error

    @patch.object(TelegramFetcher, "_make_request")
    def test_fetch_successful_custom_host(self, mock_make_request):
        """测试自定义节点成功抓取，并验证解析细节"""
        mock_response = MagicMock()
        mock_response.text = MOCK_TELEGRAM_XML
        mock_make_request.return_value = mock_response

        # 配置自定义主机（不带 https 前缀且带尾斜杠，测试规范化逻辑）
        source = ContentSource(
            type="telegram", 
            src="@durov", 
            metadata={
                "rsshub_host": "rsshub.custom.org/",
                "route_params": "?showEmoji=1"
            }
        )
        fetcher = TelegramFetcher(source)
        result = fetcher.fetch()

        assert result.success is True
        assert result.source_title == "Durov's Channel"
        # 应该解析出 3 篇文章 (Normal, Another, Deleted; Empty 被过滤，因为没有 content/summary)
        assert len(result.articles) == 3
        
        # 验证第一篇
        art1 = result.articles[0]
        assert art1.title == "Normal message with some text"
        assert "Pavel Durov" in art1.content
        assert art1.url == "https://t.me/durov/100"
        assert art1.author == "Pavel Durov"
        assert len(art1.images) == 1
        # 验证相对路径图片解析
        assert art1.images[0] == "https://t.me/durov/photo/1.jpg"

        # 验证第二篇 (content 优先)
        art2 = result.articles[1]
        assert art2.title == "Another message with content tag"
        assert "content tag directly" in art2.content
        assert len(art2.images) == 1
        assert art2.images[0] == "https://example.com/logo.png"

        # 验证 _make_request 参数
        mock_make_request.assert_called_once()
        args, kwargs = mock_make_request.call_args
        assert "https://rsshub.custom.org/telegram/channel/durov?showEmoji=1" in args[0]

    @patch.object(TelegramFetcher, "_make_request")
    def test_fetch_failover_success(self, mock_make_request):
        """测试首个节点失败时，自动无缝 failover 到后续节点"""
        mock_fail = MagicMock()
        mock_fail.side_effect = Exception("Node 1 blocked")
        
        mock_ok = MagicMock()
        mock_ok.text = MOCK_TELEGRAM_XML

        # 模拟：前两个节点失败，第三个节点成功
        mock_make_request.side_effect = [
            Exception("Node 1 Timeout"),
            Exception("Node 2 HTTP 502"),
            mock_ok
        ]

        source = ContentSource(
            type="telegram",
            src="https://t.me/durov",
            metadata={"rsshub_host": "rsshub.bad-node.com"}
        )
        fetcher = TelegramFetcher(source)
        result = fetcher.fetch()

        assert result.success is True
        assert len(result.articles) == 3
        assert mock_make_request.call_count == 3

    @patch.object(TelegramFetcher, "_make_request")
    def test_feed_parse_bozo_error(self, mock_make_request):
        """测试 Feed 存在 bozo 异常解析错误的处理"""
        mock_response = MagicMock()
        mock_response.text = "<invalid_xml>incomplete"
        mock_make_request.return_value = mock_response

        source = ContentSource(type="telegram", src="durov")
        fetcher = TelegramFetcher(source)
        result = fetcher.fetch()

        assert result.success is False
        assert "All RSSHub nodes failed" in result.error

    @patch.object(TelegramFetcher, "_make_request")
    def test_limit_validation(self, mock_make_request):
        """测试抓取限制 (metadata.limit / global_limit / fallback)"""
        mock_response = MagicMock()
        mock_response.text = MOCK_TELEGRAM_XML
        mock_make_request.return_value = mock_response

        # 1. 限制为 1 个
        source = ContentSource(type="telegram", src="durov", metadata={"limit": "1"})
        fetcher = TelegramFetcher(source)
        result = fetcher.fetch()
        assert len(result.articles) == 1

        # 2. limit 类型错误，回退到 15 (而 MOCK_TELEGRAM_XML 里最多就 3 篇有效文章)
        source = ContentSource(type="telegram", src="durov", metadata={"limit": "invalid"})
        fetcher = TelegramFetcher(source)
        result = fetcher.fetch()
        assert len(result.articles) == 3

        # 3. 使用 global_limit
        source = ContentSource(type="telegram", src="durov")
        fetcher = TelegramFetcher(source)
        fetcher.global_limit = 2
        result = fetcher.fetch()
        assert len(result.articles) == 2

    @patch.object(TelegramFetcher, "_make_request")
    def test_delete_rule_filtering(self, mock_make_request):
        """测试删除规则对文章进行过滤"""
        mock_response = MagicMock()
        mock_response.text = MOCK_TELEGRAM_XML
        mock_make_request.return_value = mock_response

        source = ContentSource(type="telegram", src="durov", delete="Deleted Message")
        fetcher = TelegramFetcher(source)
        result = fetcher.fetch()

        assert result.success is True
        # 过滤掉了 "Deleted Message"，剩下 2 篇
        assert len(result.articles) == 2
        assert "Deleted Message" not in [a.title for a in result.articles]

    @patch.object(TelegramFetcher, "_make_request")
    def test_parse_entry_exception_logged(self, mock_make_request):
        """测试单个条目解析抛出异常时能被捕获并记录，而不导致整体流程中断"""
        mock_response = MagicMock()
        mock_response.text = MOCK_TELEGRAM_XML
        mock_make_request.return_value = mock_response

        source = ContentSource(type="telegram", src="durov")
        fetcher = TelegramFetcher(source)

        # 模拟 _parse_entry 在处理第二个条目时报错
        original_parse = fetcher._parse_entry
        call_count = 0

        def side_effect_parse(entry):
            nonlocal call_count
            call_count += 1
            if call_count == 2:
                raise ValueError("Unexpected tag format")
            return original_parse(entry)

        with patch.object(fetcher, "_parse_entry", side_effect=side_effect_parse):
            result = fetcher.fetch()
            assert result.success is True
            # 本来 3 篇，第二篇报错，剩下 2 篇
            assert len(result.articles) == 2
            assert result.error_count == 1
            assert "Entry parsing failed: Unexpected tag format" in result.error

    @patch.object(TelegramFetcher, "_make_request")
    def test_normalization_skips_empty_host(self, mock_make_request):
        """测试主机列表规范化时正确跳过空字符串 (增加覆盖率)"""
        mock_ok = MagicMock()
        mock_ok.text = MOCK_TELEGRAM_XML
        mock_make_request.return_value = mock_ok

        # metadata 中有空主机名，且默认列表中也有被处理成空的情况（模拟）
        source = ContentSource(type="telegram", src="durov", metadata={"rsshub_host": "  "})
        fetcher = TelegramFetcher(source)
        
        # 故意注入一个空节点到默认列表里测试
        with patch.object(TelegramFetcher, "DEFAULT_NODES", ["  ", "https://rsshub.app"]):
            result = fetcher.fetch()
            assert result.success is True
            # 应该跳过了空节点，使用了 https://rsshub.app
            mock_make_request.assert_called_with(
                "https://rsshub.app/telegram/channel/durov",
            )
