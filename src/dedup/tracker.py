"""按内容源维护抓取 URL 快照的去重追踪器。"""

import os
import tempfile
import threading
from typing import Dict, Iterable, Set

from src.utils.helpers import generate_content_id
from src.utils.logger import get_logger


class DedupTracker:
    """记录每个内容源最近一次成功抓取到的 URL 集合。

    设计与文件格式见 docs/DEDUP.md。
    """

    def __init__(self, data_file: str = "data/fetched_urls.txt"):
        self.data_file = data_file
        self.logger = get_logger()
        self.source_ids: Dict[str, Set[str]] = {}
        self._pending_snapshots: Dict[str, Set[str]] = {}
        self.fetched_ids: Set[str] = set()
        self.new_ids: Set[str] = set()
        self._session_new_ids: Set[str] = set()
        self._lock = threading.Lock()
        self._load()

    @staticmethod
    def make_source_key(source) -> str:
        return source if isinstance(source, str) else f"{source.type}:{source.src}"

    def _refresh_fetched_ids(self):
        self.fetched_ids = set().union(*self.source_ids.values()) if self.source_ids else set()

    def _load(self):
        if not os.path.exists(self.data_file):
            self.logger.info(f"No existing dedup file found at {self.data_file}")
            return
        try:
            loaded = 0
            with open(self.data_file, "r", encoding="utf-8") as f:
                for line in f:
                    line = line.rstrip("\n")
                    if not line.strip():
                        continue
                    if "\t" not in line:
                        raise ValueError("dedup file contains an unsupported legacy record")
                    source_key, content_id = line.split("\t", 1)
                    if source_key and content_id:
                        self.source_ids.setdefault(source_key, set()).add(content_id)
                        loaded += 1
            with self._lock:
                self._refresh_fetched_ids()
            self.logger.info(f"Loaded {loaded} source-scoped content IDs")
        except Exception as e:
            self.logger.error(f"Failed to load dedup file: {e}")

    def is_fetched(self, url: str, source_key: str) -> bool:
        if not url:
            return False
        with self._lock:
            return generate_content_id(url) in self.source_ids.get(source_key, set())

    def mark_as_fetched(self, url: str, source_key: str):
        if not url:
            return
        content_id = generate_content_id(url)
        with self._lock:
            ids = self.source_ids.setdefault(source_key, set())
            if content_id not in ids:
                ids.add(content_id)
                self.fetched_ids.add(content_id)
                self.new_ids.add(content_id)
                self._session_new_ids.add(content_id)
                self.logger.debug(
                    f"Marked as fetched: source={source_key}, url={url}, hash={content_id}"
                )

    def stage_source_snapshot(self, source_key: str, urls: Iterable[str]):
        """暂存非空源快照，实际替换在 save() 时完成。

        参见 docs/DEDUP.md 的“生命周期”章节。
        """
        ids = {generate_content_id(url) for url in urls if url}
        if ids:
            with self._lock:
                self._pending_snapshots[source_key] = ids

    def save(self):
        with self._lock:
            if not self._pending_snapshots and not self.new_ids:
                self.logger.info("No new content to save")
                return
            for source_key, ids in self._pending_snapshots.items():
                self._session_new_ids.update(ids - self.source_ids.get(source_key, set()))
                self.source_ids[source_key] = set(ids)
            self._pending_snapshots.clear()
            self._refresh_fetched_ids()
            snapshot = {key: set(ids) for key, ids in self.source_ids.items() if ids}

        try:
            directory = os.path.dirname(self.data_file) or "."
            os.makedirs(directory, exist_ok=True)
            fd, temp_path = tempfile.mkstemp(prefix=".fetched_urls.", dir=directory, text=True)
            try:
                with os.fdopen(fd, "w", encoding="utf-8") as f:
                    for source_key, ids in snapshot.items():
                        for content_id in sorted(ids):
                            f.write(f"{source_key}\t{content_id}\n")
                os.replace(temp_path, self.data_file)
            finally:
                if os.path.exists(temp_path):
                    os.unlink(temp_path)
            with self._lock:
                self.new_ids.clear()
            self.logger.info(f"Saved {sum(len(ids) for ids in snapshot.values())} source-scoped content IDs")
        except Exception as e:
            self.logger.error(f"Failed to save dedup file: {e}")

    def clear(self):
        with self._lock:
            self.source_ids.clear()
            self._pending_snapshots.clear()
            self.fetched_ids.clear()
            self.new_ids.clear()
            self._session_new_ids.clear()
            if os.path.exists(self.data_file):
                try:
                    with open(self.data_file, "w", encoding="utf-8") as f:
                        f.write("")
                    self.logger.info(f"Cleared dedup file at {self.data_file}")
                except Exception as e:
                    self.logger.error(f"Failed to clear dedup file: {e}")

    def get_stats(self) -> dict:
        with self._lock:
            return {
                "total_fetched": len(self.fetched_ids),
                "new_fetched": len(self._session_new_ids),
            }

    def clear_new_ids(self):
        with self._lock:
            self.new_ids.clear()
            self._session_new_ids.clear()
