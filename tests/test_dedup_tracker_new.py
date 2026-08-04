"""
重构后去重模块针对性测试
涵盖：dedup_enabled 控制、两阶段限额丢弃自动 mark、--fresh-start 行为
"""

import pytest
from unittest.mock import MagicMock, patch

from src.config import ContentSource
from src.dedup.tracker import DedupTracker
from src.fetchers.base import BaseFetcher, FetchResult, Article
from src.fetchers.weather_fetcher import WeatherFetcher
from src.fetchers.trending_fetcher import TrendingFetcher
from src.fetchers.web_fetcher import WebFetcher
from src.fetchers.rss_fetcher import RSSFetcher
from src.main import main, process_results


class TestFetcherDedupEnabledProperty:
    """测试抓取器类的 dedup_enabled 属性配置"""

    def test_default_dedup_enabled(self):
        """BaseFetcher 及其通用子类（如 RSSFetcher）默认启用去重"""
        assert BaseFetcher.dedup_enabled is True
        assert RSSFetcher.dedup_enabled is True

    def test_disabled_dedup_fetchers(self):
        """Weather, Trending, Web 抓取器显式禁用去重"""
        assert WeatherFetcher.dedup_enabled is False
        assert TrendingFetcher.dedup_enabled is False
        assert WebFetcher.dedup_enabled is False


class TestProcessResultsWithDedupToggle:
    """测试 process_results 在 dedup_enabled 控制下的行为"""

    @patch("src.main.ContentProcessor")
    def test_process_results_skips_mark_when_dedup_disabled(self, mock_cp_cls):
        """对于 dedup_enabled=False 的源，不进行 is_fetched 检查也不 mark"""
        source = ContentSource(type="weather", src="北京")
        article = Article(
            title="北京天气",
            content="北京天气预报正文内容，长度足够且有效。",
            url="https://example.com/weather"
        )
        result = FetchResult(source=source, articles=[article], success=True)

        mock_processor = MagicMock()
        mock_processor.process.side_effect = lambda a: a
        mock_cp_cls.return_value = mock_processor

        tracker = MagicMock()
        tracker.is_fetched.return_value = True  # 即使已存在记录

        out = process_results([result], tracker)

        # 仍保留文章，不检查 is_fetched，不 mark
        assert len(out[0].articles) == 1
        tracker.is_fetched.assert_not_called()
        tracker.mark_as_fetched.assert_not_called()


class TestFreshStartAndLimitSkipped:
    """测试 Fresh Start 和两阶段限额丢弃自动标记功能"""

    @patch("src.main.load_config")
    @patch("src.main.DedupTracker")
    @patch("src.main.get_fetcher")
    def test_fresh_start_flow(self, mock_get_fetcher, mock_tracker_cls, mock_load_config):
        """--fresh-start 清空记录、拉取候选/单阶段并全量 mark，且不推送"""
        source_rss = ContentSource(type="rss", src="https://example.com/rss")
        source_weather = ContentSource(type="weather", src="北京")
        mock_config = MagicMock()
        mock_config.body = [source_rss, source_weather]
        mock_load_config.return_value = mock_config

        mock_tracker = MagicMock()
        mock_tracker_cls.return_value = mock_tracker

        # RSS 两阶段
        mock_rss_fetcher = MagicMock()
        mock_rss_fetcher.dedup_enabled = True
        mock_rss_fetcher.supports_two_phase = True
        mock_rss_fetcher.fetch_list.return_value = [
            {"url": "https://example.com/1"},
            {"url": "https://example.com/2"}
        ]

        # Weather 禁用去重
        mock_weather_fetcher = MagicMock()
        mock_weather_fetcher.dedup_enabled = False

        def get_fetcher_side_effect(source, global_limit=15):
            if source == source_rss:
                return mock_rss_fetcher
            return mock_weather_fetcher

        mock_get_fetcher.side_effect = get_fetcher_side_effect

        # 执行 main(["--fresh-start"])
        main(["--fresh-start"])

        # 验证 tracker 被 clear，且记录了 2 个 URL
        mock_tracker.clear.assert_called_once()
        mock_tracker.mark_as_fetched.assert_any_call("https://example.com/1")
        mock_tracker.mark_as_fetched.assert_any_call("https://example.com/2")
        mock_tracker.save.assert_called_once()
        mock_rss_fetcher.fetch_items.assert_not_called()

    @patch("src.main.load_config")
    @patch("src.main.DedupTracker")
    @patch("src.main.get_fetcher")
    @patch("src.main.process_results")
    @patch("src.main.has_new_content")
    def test_limit_skipped_candidates_marked(
        self, mock_has_new, mock_process, mock_get_fetcher, mock_tracker_cls, mock_load_config
    ):
        """两阶段抓取中超出 limit 截断被丢弃的候选 URL 应自动 mark"""
        source = ContentSource(type="rss", src="https://example.com/rss")
        mock_config = MagicMock()
        mock_config.body = [source]
        mock_config.limit = 2
        mock_load_config.return_value = mock_config

        mock_tracker = MagicMock()
        mock_tracker.is_fetched.return_value = False
        mock_tracker_cls.return_value = mock_tracker

        mock_rss_fetcher = MagicMock()
        mock_rss_fetcher.dedup_enabled = True
        mock_rss_fetcher.supports_two_phase = True
        mock_rss_fetcher.get_limit.return_value = 2
        # 提供 4 个候选 URL
        candidates = [{"url": f"https://example.com/{i}"} for i in range(4)]
        mock_rss_fetcher.fetch_list.return_value = candidates
        mock_rss_fetcher.fetch_items.return_value = FetchResult(source=source, articles=[], success=True)
        mock_get_fetcher.return_value = mock_rss_fetcher

        mock_process.return_value = []
        mock_has_new.return_value = False

        main([])

        # 前 2 个进入 fetch_items
        mock_rss_fetcher.fetch_items.assert_called_once_with(candidates[:2])
        # 后 2 个（限额弃用）立刻被 mark
        mock_tracker.mark_as_fetched.assert_any_call("https://example.com/2")
        mock_tracker.mark_as_fetched.assert_any_call("https://example.com/3")
        mock_tracker.save.assert_called_once()
