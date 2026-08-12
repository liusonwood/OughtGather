"""
去重追踪器测试
测试 DedupTracker 的加载、标记、保存、清理和统计行为
"""

import os
import pytest

from src.dedup.tracker import DedupTracker
from src.utils.helpers import generate_content_id


# =========================================================================
# 基本功能测试
# =========================================================================

class TestDedupTrackerBasic:
    """DedupTracker 基本功能测试"""

    def test_new_tracker_empty(self, tmp_dir):
        """新建 tracker 时 fetched_ids 为空"""
        data_file = os.path.join(tmp_dir, "fetched_urls.txt")
        tracker = DedupTracker(data_file)
        assert tracker.fetched_ids == set()
        assert tracker.new_ids == set()

    def test_mark_as_fetched(self, tmp_dir):
        """标记为已抓取后 is_fetched 返回 True"""
        data_file = os.path.join(tmp_dir, "fetched_urls.txt")
        tracker = DedupTracker(data_file)

        assert tracker.is_fetched("https://example.com", "标题") is False

        tracker.mark_as_fetched("https://example.com", "标题")

        assert tracker.is_fetched("https://example.com", "标题") is True

    def test_mark_same_url_different_title(self, tmp_dir):
        """仅 URL 决定去重：相同 URL 不同标题视为已抓取"""
        data_file = os.path.join(tmp_dir, "fetched_urls.txt")
        tracker = DedupTracker(data_file)

        tracker.mark_as_fetched("https://example.com", "标题A")
        assert tracker.is_fetched("https://example.com", "标题A") is True
        assert tracker.is_fetched("https://example.com", "标题B") is True

    def test_mark_same_url_no_title(self, tmp_dir):
        """URL 相同且都不带标题视为相同内容"""
        data_file = os.path.join(tmp_dir, "fetched_urls.txt")
        tracker = DedupTracker(data_file)

        tracker.mark_as_fetched("https://example.com")
        assert tracker.is_fetched("https://example.com") is True

    def test_new_ids_tracked(self, tmp_dir):
        """mark_as_fetched 记录 URL 哈希到 new_ids"""
        data_file = os.path.join(tmp_dir, "fetched_urls.txt")
        tracker = DedupTracker(data_file)

        tracker.mark_as_fetched("https://example.com/a", "A")
        tracker.mark_as_fetched("https://example.com/b", "B")

        # 每篇文章产生 1 条 URL 哈希
        assert len(tracker.new_ids) == 2

    def test_mark_already_fetched_not_in_new_ids(self, tmp_dir):
        """重复标记已抓取的 URL 不会增加 new_ids"""
        data_file = os.path.join(tmp_dir, "fetched_urls.txt")
        tracker = DedupTracker(data_file)

        tracker.mark_as_fetched("https://example.com", "标题")
        tracker.mark_as_fetched("https://example.com", "标题")  # 重复

        assert len(tracker.new_ids) == 1

    def test_clear(self, tmp_dir):
        """clear 方法清空文件与内存缓存"""
        data_file = os.path.join(tmp_dir, "fetched_urls.txt")
        tracker = DedupTracker(data_file)
        tracker.mark_as_fetched("https://example.com/a")
        tracker.save()

        assert tracker.is_fetched("https://example.com/a") is True
        tracker.clear()
        assert tracker.is_fetched("https://example.com/a") is False
        assert len(tracker.fetched_ids) == 0
        assert len(tracker.new_ids) == 0


# =========================================================================
# 持久化测试
# =========================================================================

class TestDedupTrackerPersistence:
    """DedupTracker 持久化测试"""

    def test_save_and_reload(self, tmp_dir):
        """保存后重新加载能恢复记录"""
        data_file = os.path.join(tmp_dir, "fetched_urls.txt")

        # 第一次：标记并保存
        tracker1 = DedupTracker(data_file)
        tracker1.mark_as_fetched("https://example.com/a", "A")
        tracker1.mark_as_fetched("https://example.com/b", "B")
        tracker1.save()

        # 第二次：重新加载
        tracker2 = DedupTracker(data_file)
        assert tracker2.is_fetched("https://example.com/a", "A") is True
        assert tracker2.is_fetched("https://example.com/b", "B") is True
        assert tracker2.is_fetched("https://example.com/c", "C") is False

    def test_save_clears_new_ids(self, tmp_dir):
        """save 后 self.new_ids 被清空，防止重复保存"""
        data_file = os.path.join(tmp_dir, "fetched_urls.txt")
        tracker = DedupTracker(data_file)

        tracker.mark_as_fetched("https://example.com/a")
        assert len(tracker.new_ids) == 1

        tracker.save()
        assert len(tracker.new_ids) == 0

    def test_save_appends_not_overwrites(self, tmp_dir):
        """save 是追加模式，不覆盖已有记录"""
        data_file = os.path.join(tmp_dir, "fetched_urls.txt")

        # 第一次保存
        tracker1 = DedupTracker(data_file)
        tracker1.mark_as_fetched("https://example.com/a", "A")
        tracker1.save()

        # 第二次保存
        tracker2 = DedupTracker(data_file)
        tracker2.mark_as_fetched("https://example.com/b", "B")
        tracker2.save()

        # 验证两条记录都存在
        tracker3 = DedupTracker(data_file)
        assert tracker3.is_fetched("https://example.com/a", "A") is True
        assert tracker3.is_fetched("https://example.com/b", "B") is True

    def test_save_no_new_ids_is_noop(self, tmp_dir):
        """没有新记录时 save 不写入文件"""
        data_file = os.path.join(tmp_dir, "fetched_urls.txt")
        tracker = DedupTracker(data_file)
        tracker.save()
        assert not os.path.exists(data_file)

    def test_creates_directory_if_missing(self, tmp_dir):
        """保存时自动创建目录"""
        data_file = os.path.join(tmp_dir, "subdir", "fetched_urls.txt")
        tracker = DedupTracker(data_file)
        tracker.mark_as_fetched("https://example.com", "标题")
        tracker.save()
        assert os.path.exists(data_file)

    def test_load_missing_file(self, tmp_dir):
        """加载不存在的文件不报错"""
        data_file = os.path.join(tmp_dir, "nonexistent.txt")
        tracker = DedupTracker(data_file)
        assert len(tracker.fetched_ids) == 0

    def test_concurrent_mark_and_save(self, tmp_dir):
        """并发 mark_as_fetched、is_fetched 与 save 的线程安全性测试"""
        import concurrent.futures
        data_file = os.path.join(tmp_dir, "fetched_urls.txt")
        tracker = DedupTracker(data_file)

        def worker(i):
            url = f"https://example.com/item_{i}"
            tracker.mark_as_fetched(url)
            assert tracker.is_fetched(url) is True
            if i % 10 == 0:
                tracker.save()

        with concurrent.futures.ThreadPoolExecutor(max_workers=10) as executor:
            futures = [executor.submit(worker, i) for i in range(100)]
            for f in futures:
                f.result()

        tracker.save()
        stats = tracker.get_stats()
        assert stats["total_fetched"] == 100


# =========================================================================
# 统计与清理测试
# =========================================================================

class TestDedupTrackerStats:
    """DedupTracker 统计与清理测试"""

    def test_get_stats(self, tmp_dir):
        """get_stats 返回正确统计"""
        data_file = os.path.join(tmp_dir, "fetched_urls.txt")
        tracker = DedupTracker(data_file)

        tracker.mark_as_fetched("https://example.com/a", "A")
        tracker.mark_as_fetched("https://example.com/b", "B")

        stats = tracker.get_stats()
        assert stats["total_fetched"] == 2
        assert stats["new_fetched"] == 2

    def test_get_stats_after_reload(self, tmp_dir):
        """重新加载后 new_fetched 为 0"""
        data_file = os.path.join(tmp_dir, "fetched_urls.txt")

        tracker1 = DedupTracker(data_file)
        tracker1.mark_as_fetched("https://example.com", "标题")
        tracker1.save()

        tracker2 = DedupTracker(data_file)
        stats = tracker2.get_stats()
        assert stats["total_fetched"] == 1
        assert stats["new_fetched"] == 0

    def test_clear_new_ids(self, tmp_dir):
        """clear_new_ids 清空 new_ids 但保留 fetched_ids"""
        data_file = os.path.join(tmp_dir, "fetched_urls.txt")
        tracker = DedupTracker(data_file)

        tracker.mark_as_fetched("https://example.com", "标题")
        assert len(tracker.new_ids) == 1

        tracker.clear_new_ids()
        assert len(tracker.new_ids) == 0
        assert len(tracker.fetched_ids) == 1


# =========================================================================
# 自动清理测试
# =========================================================================

class TestDedupTrackerCleanup:
    """DedupTracker 超过上限自动清理测试"""

    def test_no_cleanup_when_under_max(self, tmp_dir, monkeypatch):
        """未达到上限时不触发清理"""
        data_file = os.path.join(tmp_dir, "fetched_urls.txt")
        monkeypatch.setattr(DedupTracker, 'MAX_RECORDS', 5)

        tracker = DedupTracker(data_file)
        for i in range(2):
            tracker.mark_as_fetched(f"https://example.com/{i}", f"T{i}")
        tracker.save()

        with open(data_file) as f:
            lines = [l.strip() for l in f if l.strip()]
        assert len(lines) == 2

    def test_no_cleanup_at_exact_max(self, tmp_dir, monkeypatch):
        """恰好等于上限时不触发清理"""
        data_file = os.path.join(tmp_dir, "fetched_urls.txt")
        monkeypatch.setattr(DedupTracker, 'MAX_RECORDS', 3)

        tracker = DedupTracker(data_file)
        for i in range(3):
            tracker.mark_as_fetched(f"https://example.com/{i}")
        tracker.save()

        with open(data_file) as f:
            lines = [l.strip() for l in f if l.strip()]
        assert len(lines) == 3

    def test_cleanup_when_exceeds_max(self, tmp_dir, monkeypatch):
        """超过上限时自动清理，保留最新的记录"""
        data_file = os.path.join(tmp_dir, "fetched_urls.txt")
        monkeypatch.setattr(DedupTracker, 'MAX_RECORDS', 5)

        # 预先写入 5 条旧记录
        with open(data_file, 'w') as f:
            for i in range(5):
                f.write(f"old_{i}\n")

        tracker = DedupTracker(data_file)
        assert len(tracker.fetched_ids) == 5

        # 新增 2 篇 → 2 条新哈希，总数 7 > 5，应触发清理
        for i in range(2):
            tracker.mark_as_fetched(f"https://example.com/new_{i}", f"N{i}")
        tracker.save()

        with open(data_file) as f:
            lines = [l.strip() for l in f if l.strip()]
        assert len(lines) == 5
        assert "old_0" not in lines
        assert "old_1" not in lines
        assert "old_3" in lines
        assert "old_4" in lines

        assert len(tracker.fetched_ids) == 5
        assert "old_0" not in tracker.fetched_ids
        assert "old_4" in tracker.fetched_ids

    def test_cleanup_keeps_newest_in_order(self, tmp_dir, monkeypatch):
        """清理后文件中记录保持原有顺序（最新记录在末尾）"""
        data_file = os.path.join(tmp_dir, "fetched_urls.txt")
        monkeypatch.setattr(DedupTracker, 'MAX_RECORDS', 3)

        with open(data_file, 'w') as f:
            f.write("aaa\nbbb\nccc\n")

        tracker = DedupTracker(data_file)
        tracker.mark_as_fetched("https://example.com/x", "X")
        tracker.save()

        with open(data_file) as f:
            lines = [l.strip() for l in f if l.strip()]

        # 追加后为 [aaa, bbb, ccc, url_hash_X] (4 条)，
        # 保留末尾 3 条：bbb, ccc, url_hash_X
        assert len(lines) == 3
        assert lines[0] == "bbb"
        assert "aaa" not in lines
