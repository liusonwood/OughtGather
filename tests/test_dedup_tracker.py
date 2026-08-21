"""DedupTracker 的 source 快照语义测试。"""

import concurrent.futures
import os
from unittest.mock import MagicMock, patch

from src.config import ContentSource
from src.dedup.tracker import DedupTracker
from src.fetchers.base import Article, BaseFetcher, FetchResult
from src.fetchers.rss_fetcher import RSSFetcher
from src.fetchers.trending_fetcher import TrendingFetcher
from src.fetchers.weather_fetcher import WeatherFetcher
from src.fetchers.web_fetcher import WebFetcher
from src.main import main, process_results


def url(number):
    return f"https://example.com/article/{number}"


def test_new_tracker_empty(tmp_dir):
    tracker = DedupTracker(os.path.join(tmp_dir, "fetched_urls.txt"))
    assert tracker.fetched_ids == set()
    assert tracker.new_ids == set()


def test_mark_and_query_are_source_scoped(tmp_dir):
    tracker = DedupTracker(os.path.join(tmp_dir, "fetched_urls.txt"))
    tracker.mark_as_fetched(url(1), "rss:feed-a")

    assert tracker.is_fetched(url(1), "rss:feed-a")
    assert not tracker.is_fetched(url(1), "rss:feed-b")


def test_snapshot_replaces_previous_ids_for_same_source(tmp_dir):
    tracker = DedupTracker(os.path.join(tmp_dir, "fetched_urls.txt"))
    source_key = "rss:feed-a"
    tracker.stage_source_snapshot(source_key, [url(1), url(2)])
    tracker.save()
    tracker.stage_source_snapshot(source_key, [url(2), url(3)])
    tracker.save()

    assert not tracker.is_fetched(url(1), source_key)
    assert tracker.is_fetched(url(2), source_key)
    assert tracker.is_fetched(url(3), source_key)
    stats = tracker.get_stats()
    assert stats["snapshot_added"] == 3
    assert stats["snapshot_removed"] == 1


def test_empty_snapshot_preserves_previous_ids(tmp_dir):
    tracker = DedupTracker(os.path.join(tmp_dir, "fetched_urls.txt"))
    source_key = "rss:feed-a"
    tracker.stage_source_snapshot(source_key, [url(1)])
    tracker.save()
    tracker.stage_source_snapshot(source_key, [])
    tracker.save()

    assert tracker.is_fetched(url(1), source_key)


def test_save_and_reload_preserves_source_isolation(tmp_dir):
    data_file = os.path.join(tmp_dir, "fetched_urls.txt")
    tracker = DedupTracker(data_file)
    tracker.stage_source_snapshot("rss:feed-a", [url(1)])
    tracker.stage_source_snapshot("mail:box", [url(1), url(2)])
    tracker.save()

    lines = [line.strip() for line in open(data_file, encoding="utf-8") if line.strip()]
    assert all("\t" in line for line in lines)

    reloaded = DedupTracker(data_file)
    assert reloaded.is_fetched(url(1), "rss:feed-a")
    assert reloaded.is_fetched(url(2), "mail:box")
    assert not reloaded.is_fetched(url(2), "rss:feed-a")


def test_empty_save_does_not_create_file(tmp_dir):
    data_file = os.path.join(tmp_dir, "fetched_urls.txt")
    DedupTracker(data_file).save()
    assert not os.path.exists(data_file)


def test_clear_removes_all_source_snapshots(tmp_dir):
    data_file = os.path.join(tmp_dir, "fetched_urls.txt")
    tracker = DedupTracker(data_file)
    tracker.stage_source_snapshot("rss:feed-a", [url(1)])
    tracker.save()
    tracker.clear()

    assert not tracker.is_fetched(url(1), "rss:feed-a")
    assert tracker.fetched_ids == set()


def test_concurrent_mark_and_save_is_safe(tmp_dir):
    tracker = DedupTracker(os.path.join(tmp_dir, "fetched_urls.txt"))

    def worker(number):
        tracker.mark_as_fetched(url(number), "rss:feed-a")
        assert tracker.is_fetched(url(number), "rss:feed-a")

    with concurrent.futures.ThreadPoolExecutor(max_workers=10) as executor:
        list(executor.map(worker, range(100)))
    tracker.save()

    assert tracker.get_stats()["total_fetched"] == 100


class TestFetcherDedupEnabledProperty:
    def test_default_dedup_enabled(self):
        assert BaseFetcher.dedup_enabled is True
        assert RSSFetcher.dedup_enabled is True

    def test_disabled_dedup_fetchers(self):
        assert WeatherFetcher.dedup_enabled is False
        assert TrendingFetcher.dedup_enabled is False
        assert WebFetcher.dedup_enabled is False


class TestProcessResultsWithDedupToggle:
    @patch("src.main.ContentProcessor")
    def test_process_results_skips_mark_when_dedup_disabled(self, mock_cp_cls):
        source = ContentSource(type="weather", src="北京")
        article = Article(
            title="北京天气",
            content="北京天气预报正文内容，长度足够且有效。",
            url="https://example.com/weather",
        )
        result = FetchResult(source=source, articles=[article], success=True)
        mock_processor = MagicMock()
        mock_processor.process.side_effect = lambda a: a
        mock_cp_cls.return_value = mock_processor

        tracker = MagicMock()
        tracker.is_fetched.return_value = True
        out = process_results([result], tracker)

        assert len(out[0].articles) == 1
        tracker.is_fetched.assert_not_called()
        tracker.mark_as_fetched.assert_not_called()


class TestFreshStartAndSnapshotCandidates:
    @patch("src.main.load_config")
    @patch("src.main.DedupTracker")
    @patch("src.main.get_fetcher")
    def test_fresh_start_stages_all_candidates(
        self, mock_get_fetcher, mock_tracker_cls, mock_load_config
    ):
        source = ContentSource(type="rss", src="https://example.com/rss")
        mock_config = MagicMock(body=[source])
        mock_load_config.return_value = mock_config
        mock_tracker = MagicMock()
        mock_tracker_cls.return_value = mock_tracker

        fetcher = MagicMock(dedup_enabled=True, supports_two_phase=True)
        fetcher.fetch_list.return_value = [
            {"url": "https://example.com/1"},
            {"url": "https://example.com/2"},
        ]
        mock_get_fetcher.return_value = fetcher

        main(["--fresh-start"])

        mock_tracker.clear.assert_called_once()
        mock_tracker.stage_source_snapshot.assert_called_once_with(
            mock_tracker.make_source_key.return_value,
            ["https://example.com/1", "https://example.com/2"],
        )
        mock_tracker.save.assert_called_once()
        fetcher.fetch_items.assert_not_called()

    @patch("src.main.load_config")
    @patch("src.main.DedupTracker")
    @patch("src.main.get_fetcher")
    @patch("src.main.process_results")
    @patch("src.main.has_new_content")
    def test_limit_does_not_remove_candidates_from_snapshot(
        self,
        mock_has_new,
        mock_process,
        mock_get_fetcher,
        mock_tracker_cls,
        mock_load_config,
    ):
        source = ContentSource(type="rss", src="https://example.com/rss")
        mock_config = MagicMock(body=[source], limit=2)
        mock_load_config.return_value = mock_config
        mock_tracker = MagicMock()
        mock_tracker.is_fetched.return_value = False
        mock_tracker_cls.return_value = mock_tracker

        candidates = [{"url": f"https://example.com/{i}"} for i in range(4)]
        fetcher = MagicMock(dedup_enabled=True, supports_two_phase=True)
        fetcher.get_limit.return_value = 2
        fetcher.fetch_list.return_value = candidates
        fetcher.fetch_items.return_value = FetchResult(
            source=source, articles=[], success=True
        )
        mock_get_fetcher.return_value = fetcher
        mock_process.return_value = []
        mock_has_new.return_value = False

        main([])

        fetcher.fetch_items.assert_called_once_with(candidates[:2])
        mock_tracker.stage_source_snapshot.assert_called_once_with(
            mock_tracker.make_source_key.return_value,
            [candidate["url"] for candidate in candidates],
        )
        mock_tracker.mark_as_fetched.assert_not_called()
        mock_tracker.save.assert_called_once()
