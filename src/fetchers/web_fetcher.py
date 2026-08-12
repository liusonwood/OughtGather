"""
网页抓取器模块
抓取单个网页并提取正文
"""

from typing import List, Optional, Any
from bs4 import BeautifulSoup
import trafilatura

from src.fetchers.base import BaseFetcher, FetchResult, Article
from src.utils.logger import get_logger


class WebFetcher(BaseFetcher):
    """网页抓取器"""

    type_name = "web"
    dedup_enabled = False
    src_placeholder = "网页 URL"
    config_schema = {}

    @classmethod
    def get_default_source_title(cls, source: Any, articles: List[Article], source_title: Optional[str] = None) -> str:
        if articles:
            return articles[0].title
        return source.src

    def fetch(self) -> FetchResult:
        """
        执行网页抓取

        Returns:
            FetchResult: 抓取结果
        """
        result = FetchResult(source=self.source, articles=[])

        try:
            # 下载网页
            response = self._make_request(self.source.src)
            html = response.text

            # 提取标题
            title = self._extract_title(html)

            # 提取正文
            content = self._extract_content(html)

            if not content:
                result.success = False
                result.error = "Failed to extract content from webpage"
                return result

            # 从原始 HTML 提取图片：先从 og:image/twitter:image 等 meta 标签获取封面图，
            # 再从正文 <img> 标签补充（避免 trafilatura 丢失 lead image）
            og_images = self._extract_og_image(html, base_url=self.source.src)
            body_images = self._extract_images(html, base_url=self.source.src)
            seen = set(og_images)
            images = og_images + [u for u in body_images if u not in seen]

            # 创建文章对象
            article = Article(
                title=title,
                content=content,
                url=self.source.src,
                images=images,
            )

            # 检查是否应该删除
            if not self._should_delete(article.title):
                result.articles.append(article)

            return result

        except Exception as e:
            self.logger.error(f"Web fetch failed: {e}")
            result.success = False
            result.error = str(e)
            return result

    def _extract_title(self, html: str) -> str:
        """
        从 HTML 中提取标题

        Args:
            html: HTML 内容

        Returns:
            str: 标题
        """
        from src.utils.helpers import HTML_PARSING_LOCK
        with HTML_PARSING_LOCK:
            soup = BeautifulSoup(html, 'lxml')

        # 尝试多个可能的标题位置
        title = None

        # 1. <title> 标签
        if soup.title and soup.title.string:
            title = soup.title.string.strip()

        # 2. <h1> 标签
        if not title:
            h1 = soup.find('h1')
            if h1:
                title = h1.get_text(strip=True)

        # 3. Open Graph 标题
        if not title:
            og_title = soup.find('meta', property='og:title')
            if og_title:
                title = og_title.get('content', '')

        # 4. 使用自定义标题或 URL
        if not title:
            title = self.source.title or self.source.src

        return title

    def _extract_content(self, html: str) -> str:
        """
        从 HTML 中提取正文

        Args:
            html: HTML 内容

        Returns:
            str: 正文 HTML
        """
        content = trafilatura.extract(
            html,
            include_comments=False,
            include_tables=True,
            include_images=True,
            include_links=True,
            include_formatting=True,
            output_format="html",
        )

        if content:
            # trafilatura 在 output_format="html" 时会将 <img> 转换为
            # <graphic>（HTML5 元素），导致下游的 ContentProcessor 和
            # EPUBGenerator 找不到 <img> 标签而丢失所有图片。
            content = self._restore_img_tags(content)

        return content or ""
