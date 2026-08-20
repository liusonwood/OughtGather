"""
去重追踪器模块
负责记录已抓取的内容，避免重复抓取
"""

import os
import threading
from typing import Set, Optional
from src.utils.logger import get_logger
from src.utils.helpers import generate_content_id


class DedupTracker:
    """去重追踪器"""

    MAX_RECORDS = 50000  # 记录数上限，超过后自动清理旧记录

    def __init__(self, data_file: str = "data/fetched_urls.txt"):
        """
        初始化去重追踪器

        Args:
            data_file: 数据存储文件路径
        """
        self.data_file = data_file
        self.logger = get_logger()
        self.fetched_ids: Set[str] = set()
        self.new_ids: Set[str] = set()
        self._session_new_ids: Set[str] = set()
        self._lock = threading.Lock()

        # 加载已有记录
        self._load()

    def _load(self):
        """加载已抓取的内容 ID"""
        if not os.path.exists(self.data_file):
            self.logger.info(f"No existing dedup file found at {self.data_file}")
            return

        try:
            with open(self.data_file, 'r', encoding='utf-8') as f:
                loaded = {line.strip() for line in f if line.strip()}
            with self._lock:
                self.fetched_ids.update(loaded)

            self.logger.info(f"Loaded {len(loaded)} fetched content IDs")

        except Exception as e:
            self.logger.error(f"Failed to load dedup file: {e}")

    def is_fetched(self, url: str, *args, **kwargs) -> bool:
        """
        检查 URL 是否已抓取（仅依赖标准化 URL 的 MD5 哈希）。
        """
        if not url:
            return False
        url_hash = generate_content_id(url)
        with self._lock:
            return url_hash in self.fetched_ids

    def mark_as_fetched(self, url: str, *args, **kwargs):
        """
        标记 URL 为已抓取。
        """
        if not url:
            return
        url_hash = generate_content_id(url)

        with self._lock:
            if url_hash not in self.fetched_ids:
                self.fetched_ids.add(url_hash)
                self.new_ids.add(url_hash)
                self._session_new_ids.add(url_hash)
                self.logger.debug(f"Marked as fetched: url={url}, hash={url_hash}")

    def save(self):
        """保存新的抓取记录"""
        with self._lock:
            if not self.new_ids:
                self.logger.info("No new content to save")
                return
            ids_to_save = set(self.new_ids)

        try:
            # 确保目录存在
            os.makedirs(os.path.dirname(self.data_file), exist_ok=True)

            # 追加新记录
            with open(self.data_file, 'a', encoding='utf-8') as f:
                for content_id in ids_to_save:
                    f.write(f"{content_id}\n")

            self.logger.info(f"Saved {len(ids_to_save)} new content IDs")

            with self._lock:
                self.new_ids.difference_update(ids_to_save)

            # 超过上限时自动清理旧记录
            self._cleanup_if_needed()

        except Exception as e:
            self.logger.error(f"Failed to save dedup file: {e}")

    def clear(self):
        """清空去重日志文件及内存中的缓存"""
        with self._lock:
            self.fetched_ids.clear()
            self.new_ids.clear()
            self._session_new_ids.clear()
            if os.path.exists(self.data_file):
                try:
                    with open(self.data_file, 'w', encoding='utf-8') as f:
                        f.write("")
                    self.logger.info(f"Cleared dedup file at {self.data_file}")
                except Exception as e:
                    self.logger.error(f"Failed to clear dedup file: {e}")

    def _cleanup_if_needed(self):
        """超过 MAX_RECORDS 条时，只保留最新的记录（文件末尾）"""
        try:
            if not os.path.exists(self.data_file):
                return

            with open(self.data_file, 'r', encoding='utf-8') as f:
                lines = [line.strip() for line in f if line.strip()]

            if len(lines) <= self.MAX_RECORDS:
                return

            # 保留最新的记录（文件末尾的 MAX_RECORDS 条）
            kept = lines[-self.MAX_RECORDS:]
            with open(self.data_file, 'w', encoding='utf-8') as f:
                for line in kept:
                    f.write(f"{line}\n")

            removed = len(lines) - len(kept)
            # 同步内存中的 set，避免后续判断与文件不一致；保留尚未落盘的 new_ids
            with self._lock:
                self.fetched_ids = set(kept).union(self.new_ids)
            self.logger.info(f"Dedup cleanup: removed {removed} old records, kept {len(kept)}")

        except Exception as e:
            self.logger.error(f"Failed to cleanup dedup file: {e}")

    def get_stats(self) -> dict:
        """
        获取统计信息

        Returns:
            dict: 统计信息
        """
        with self._lock:
            return {
                "total_fetched": len(self.fetched_ids),
                "new_fetched": len(self._session_new_ids)
            }

    def clear_new_ids(self):
        """清除新记录标记"""
        with self._lock:
            self.new_ids.clear()
            self._session_new_ids.clear()

