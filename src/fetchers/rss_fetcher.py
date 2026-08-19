"""
RSS 抓取器模块
解析 RSS/Atom 内容源
"""

from typing import List, Optional, Any
import feedparser

from src.config import ContentSource
from src.fetchers.base import BaseFetcher, FetchResult, Article
from src.utils.helpers import format_date


class RSSFetcher(BaseFetcher):
    """RSS 抓取器"""

    type_name = "rss"
    supports_two_phase = True
    src_placeholder = "RSS/Atom URL, 例如: https://hnrss.org/frontpage"
    config_schema = {
        "metadata.full_text": {
            "type": "select",
            "label": "全文提取",
            "options": ["", "N", "Y"],
            "hint": "抓取 RSS 页面正文"
        },
        "metadata.limit": {
            "type": "number",
            "label": "限制条目数 (limit)",
            "placeholder": "留空使用全局限制"
        }
    }
    MAX_ENTRIES = 50  # 每个 RSS 源最多抓取的条目数，可通过 metadata.limit 覆盖

    @classmethod
    def get_default_source_title(cls, source: Any, articles: List[Article], source_title: Optional[str] = None) -> str:
        return source_title or source.src

    def fetch(self) -> FetchResult:
        """
        执行 RSS 抓取

        Returns:
            FetchResult: 抓取结果
        """
        result = FetchResult(source=self.source, articles=[])

        try:
            # 通过 BaseFetcher._make_request 下载后再解析，复用统一 UA / 连接池
            feed = self._parse_feed()

            # 检查解析结果
            # 改进：即使有格式错误，只要有条目就继续处理
            if feed.bozo:
                self.logger.warning(
                    f"RSS feed has format issues (bozo): {feed.bozo_exception}"
                )
            
            # 如果没有任何条目且有严重错误，则失败
            if not feed.entries:
                result.success = False
                error_msg = str(feed.bozo_exception) if feed.bozo else "No entries found"
                result.error = f"Failed to parse RSS feed: {error_msg}"
                self.logger.error(result.error)
                return result

            # 提取 feed 标题作为章节显示名称
            result.source_title = feed.feed.get("title", "")

            self.logger.info(f"Found {len(feed.entries)} entries in RSS feed")

            # 限制条目数量（默认使用全局限制，可通过 metadata.limit 覆盖）
            metadata = self.source.metadata or {}
            limit = min(int(metadata.get("limit", self.global_limit)), len(feed.entries))
            entries = feed.entries[:limit]

            if limit < len(feed.entries):
                self.logger.info(f"Limiting RSS entries to {limit} (feed has {len(feed.entries)})")

            # 遍历所有条目
            for entry in entries:
                try:
                    article = self._parse_entry(entry)
                    if article and not self._should_delete(article.title):
                        result.articles.append(article)
                except Exception as e:
                    self.logger.error(f"Failed to parse entry: {e}")
                    result.add_error(f"Failed to parse entry: {e}")

            # 只要成功解析了至少一些条目，就认为抓取成功
            if result.articles:
                result.success = True
            
            return result

        except Exception as e:
            self.logger.error(f"RSS fetch failed: {e}")
            result.success = False
            result.error = str(e)
            return result

    # ------------------------------------------------------------------
    # 两阶段接口实现
    # ------------------------------------------------------------------

    def fetch_list(self) -> Optional[List[dict]]:
        """
        【阶段一】解析 RSS feed，仅返回候选条目元数据列表（不抓全文）。

        Returns:
            list of dict with keys: url, title, author, published, _entry
            解析失败时返回 None 以触发回退逻辑。
        """
        try:
            feed = self._parse_feed()

            if feed.bozo:
                self.logger.warning(
                    f"RSS feed has format issues (bozo): {feed.bozo_exception}"
                )

            if not feed.entries:
                self.logger.error(
                    f"Failed to parse RSS feed or no entries: "
                    f"{feed.bozo_exception if feed.bozo else 'No entries found'}"
                )
                return None

            # 保存 feed 级别的标题供 fetch_items 使用
            self._cached_source_title = feed.feed.get("title", "")

            self.logger.info(
                f"[fetch_list] RSS feed 共 {len(feed.entries)} 条"
            )

            candidates = []
            for entry in feed.entries:
                url = entry.get("link", "")
                title = entry.get("title", "No Title")
                # 过滤掉明显应被删除的标题，减少后续不必要处理
                if self._should_delete(title):
                    continue
                candidates.append({
                    "url": url,
                    "title": title,
                    "author": entry.get("author", ""),
                    "published": entry.get("published", ""),
                    "_entry": entry,  # 保留原始 entry，供 fetch_items 使用摘要
                })

            return candidates

        except Exception as e:
            self.logger.error(f"[fetch_list] RSS fetch_list failed: {e}")
            return None

    def fetch_items(self, candidates: List[dict]) -> "FetchResult":
        """
        【阶段二】对去重过滤后的候选条目执行全文/摘要抓取，返回 FetchResult。

        Args:
            candidates: fetch_list() 返回并经去重过滤的条目列表。
        """
        result = FetchResult(source=self.source, articles=[])
        result.source_title = getattr(self, "_cached_source_title", "")

        if not candidates:
            self.logger.info("[fetch_items] 无新候选条目，跳过全文抓取")
            return result

        self.logger.info(f"[fetch_items] 开始抓取 {len(candidates)} 篇新文章")

        for cand in candidates:
            try:
                entry = cand.get("_entry", {})
                article = self._parse_entry(entry)
                if article:
                    result.articles.append(article)
            except Exception as e:
                self.logger.error(f"[fetch_items] 解析条目失败: {e}")
                result.add_error(f"Failed to parse entry: {e}")

        if result.articles:
            result.success = True

        return result

    def _parse_entry(self, entry: dict) -> Optional[Article]:
        """
        解析单个 RSS 条目

        Args:
            entry: RSS 条目（feedparser 解析结果）

        Returns:
            Article: 文章对象
        """
        # 提取基本信息
        title = entry.get("title", "No Title")
        link = entry.get("link", "")
        author = entry.get("author", "")
        published = format_date(entry.get("published", ""))

        # 提取内容
        metadata = self.source.metadata or {}
        full_text = metadata.get("full_text") or self.source.full_text
        if full_text == "Y":
            # 抓取完整正文（使用 trafilatura）
            content, raw_html = self._fetch_full_text(link)
            # 从原始 HTML 提取图片 URL（trafilatura 通常会剥离 <img>）
            body_images = self._extract_images(raw_html, base_url=link)
            # 额外从 og:image / twitter:image / <link rel="image_src"> 提取封面图，
            # 置于列表首位（SPA 类网站如 Scientific American 的 lead image
            # 可能不在 trafilatura 识别的正文区域内，依赖 meta 标签才能捕获）
            og_images = self._extract_og_image(raw_html, base_url=link)
            # 合并：og_images 在前，body_images 追加（去重）
            seen = set(og_images)
            images = og_images + [u for u in body_images if u not in seen]
        else:
            # 使用 RSS 摘要
            content = self._get_summary(entry)
            images = self._extract_images(content, base_url=link)

        if not content:
            self.logger.warning(f"No content for entry: {title}")
            return None

        return Article(
            title=title,
            content=content,
            url=link,
            author=author,
            published_date=published,
            images=images,
            metadata={
                "categories": entry.get("tags", []),
            }
        )

    def _get_summary(self, entry: dict) -> str:
        """
        从 RSS 条目中获取摘要

        Args:
            entry: RSS 条目

        Returns:
            str: 摘要 HTML
        """
        # 尝试多个可能的内容字段
        if "content" in entry and len(entry.content) > 0:
            return entry.content[0].get("value", "")

        if "summary" in entry:
            return entry.get("summary", "")

        if "description" in entry:
            return entry.get("description", "")

        return ""

    def _parse_feed(self):
        """
        通过基类 HTTP 客户端下载 RSS/Atom，再用 feedparser 解析。

        不直接把 URL 交给 feedparser，避免其内部 urllib 绕过统一的
        User-Agent、连接复用和反爬策略。
        """
        response = self._make_request(self.source.src, browser=True)
        return feedparser.parse(response.content)
