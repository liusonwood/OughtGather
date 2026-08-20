"""
基础抓取器模块
定义统一的抓取接口和基础功能
"""

import re
import time
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import List, Optional, Dict, Any
import httpx
import trafilatura

from src.config import ContentSource
from src.utils.logger import get_logger


@dataclass
class Article:
    """文章数据结构"""
    title: str
    content: str  # HTML 格式
    url: str
    author: Optional[str] = None
    published_date: Optional[str] = None
    images: List[str] = field(default_factory=list)
    metadata: Dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> Dict[str, Any]:
        """转换为字典"""
        return {
            "title": self.title,
            "content": self.content,
            "url": self.url,
            "author": self.author,
            "published_date": self.published_date,
            "images": self.images,
            "metadata": self.metadata
        }


@dataclass
class FetchResult:
    """抓取结果数据结构"""
    source: ContentSource
    articles: List[Article]
    success: bool = True
    error: Optional[str] = None
    error_count: int = 0
    source_title: Optional[str] = None  # 内容源的显示名称（如 RSS feed 标题）

    def add_error(self, error_msg: str):
        """添加错误信息"""
        if self.error:
            self.error += f"; {error_msg}"
        else:
            self.error = error_msg
        self.error_count += 1


_registry = {}


def get_fetcher_class(type_name: str) -> Optional[Any]:
    """
    根据类型名称获取注册的抓取器类

    Args:
        type_name: 抓取器类型名称

    Returns:
        Type[BaseFetcher] | None: 对应的抓取器类，如果未找到则返回 None
    """
    return _registry.get(type_name)


class BaseFetcher(ABC):
    """基础抓取器抽象类"""

    type_name: str = ""
    src_placeholder: str = ""
    config_schema: dict = {}
    required_secrets: Dict[str, str] = {}
    custom_css: str = ""
    supports_two_phase: bool = False  # 子类设为 True 表示支持两阶段抓取接口
    dedup_enabled: bool = True  # 子类可设为 False 表示禁用去重（如 Weather, Trending, Web）

    def __init_subclass__(cls, **kwargs):
        super().__init_subclass__(**kwargs)
        if hasattr(cls, "type_name") and cls.type_name:
            _registry[cls.type_name] = cls

    @classmethod
    def validate_source(cls, source: Any):
        """
        验证或修饰特定类型的 ContentSource 实例。
        子类可重写该方法以提供特化的验证和配置默认值填充。
        """
        pass

    @classmethod
    def get_default_source_title(cls, source: Any, articles: List[Article], source_title: Optional[str] = None) -> str:
        """
        根据抓取器类型获取默认的章节标题。
        默认返回 source.src。子类可提供特化的命名逻辑。
        """
        return source.src


    def __init__(self, source: ContentSource, global_limit: int = 15, max_retries: int = 2):
        """
        初始化抓取器

        Args:
            source: 内容源配置
            global_limit: 全局抓取数量限制
            max_retries: 最大重试次数
        """
        self.source = source
        self.global_limit = global_limit
        self.max_retries = max_retries
        self.logger = get_logger()
        self._client = None
        self._scraper = None

    def __del__(self):
        try:
            if hasattr(self, '_client') and self._client and not self._client.is_closed:
                self._client.close()
        except Exception:
            pass

    def get_limit(self) -> int:
        """
        获取当前源的抓取限制条目数（优先取 source.limit / metadata.limit，其次取全局 global_limit）。
        """
        metadata = self.source.metadata or {}
        src_limit = getattr(self.source, "limit", None)
        if src_limit is not None and str(src_limit).isdigit():
            return int(src_limit)
        if "limit" in metadata and metadata["limit"] is not None and str(metadata["limit"]).isdigit():
            return int(metadata["limit"])
        return int(self.global_limit)

    @abstractmethod
    def fetch(self) -> FetchResult:
        """
        执行抓取

        Returns:
            FetchResult: 抓取结果
        """
        pass

    def fetch_list(self) -> Optional[List[Dict[str, Any]]]:
        """
        【两阶段接口·阶段一】仅获取候选文章的轻量元数据列表，不抓取全文。

        支持两阶段抓取的子类应重写此方法，返回候选条目列表，每个条目至少含：
            - ``url``   (str)  文章链接（必填，用于去重查询）
            - ``title`` (str)  文章标题（可选，辅助去重）
        其余字段由各子类自行扩展。

        Returns:
            List[Dict[str, Any]] | None:
                候选列表；若该 fetcher 不支持两阶段，返回 None 以触发回退逻辑。
        """
        return None

    def fetch_items(self, candidates: List[Dict[str, Any]]) -> FetchResult:
        """
        【两阶段接口·阶段二】对去重过滤后的候选列表执行全文抓取，返回完整结果。

        ``supports_two_phase = True`` 的子类必须实现此方法。

        Args:
            candidates: 经去重过滤后的候选条目列表（格式同 fetch_list 返回值）。

        Returns:
            FetchResult: 抓取结果。
        """
        raise NotImplementedError(
            f"{self.__class__.__name__} 声明了 supports_two_phase=True，"
            f"但未实现 fetch_items() 方法。"
        )

    def fetch_with_retry(self) -> FetchResult:
        """
        带重试机制的抓取
        """
        last_error = None

        for attempt in range(self.max_retries):
            try:
                self.logger.info(
                    f"Fetching {self.source.type} (attempt {attempt + 1}/{self.max_retries}): "
                    f"{self.source.src}"
                )

                result = self.fetch()

                if result.success:
                    self.logger.info(
                        f"Successfully fetched {len(result.articles)} articles from {self.source.src}"
                    )
                    return result
                else:
                    last_error = result.error
                    self.logger.warning(
                        f"Attempt {attempt + 1} failed: {last_error}"
                    )

            except Exception as e:
                last_error = str(e)
                self.logger.error(
                    f"Attempt {attempt + 1} failed with exception: {e}"
                )

            # 如果不是最后一次尝试，等待后重试
            if attempt < self.max_retries - 1:
                # 自定义重试间隔：第1次失败后0.5s，第2次失败后1.5s
                retry_intervals = [0.5, 1.5]
                wait_time = retry_intervals[attempt] if attempt < len(retry_intervals) else 1.5
                self.logger.info(f"Waiting {wait_time}s before retry...")
                time.sleep(wait_time)

        # 所有重试都失败
        self.logger.error(
            f"All {self.max_retries} attempts failed for {self.source.src}"
        )

        return FetchResult(
            source=self.source,
            articles=[],
            success=False,
            error=f"Failed after {self.max_retries} attempts: {last_error}"
        )

    DEFAULT_TIMEOUT = 10
    DEFAULT_HEADERS = {"User-Agent": "OughtGather/1.0"}

    def _make_request(
        self,
        url: str,
        method: str = "GET",
        headers: Optional[Dict[str, str]] = None,
        timeout: int = DEFAULT_TIMEOUT,
        json: Optional[Any] = None,
        data: Optional[Any] = None,
        params: Optional[Dict[str, Any]] = None,
        raise_for_status: bool = True,
    ) -> httpx.Response:
        """
        发送 HTTP 请求。所有 fetcher 的网络访问都应走此方法，以便统一
        User-Agent 和连接复用。

        Args:
            url: 请求 URL
            method: HTTP 方法
            headers: 请求头（覆盖默认值）
            timeout: 超时时间（秒）
            json: JSON 请求体（用于 POST/PUT 等）
            data: 表单或原始请求体
            params: URL 查询参数
            raise_for_status: 是否在 4xx/5xx 时抛出异常

        Returns:
            httpx.Response
        """
        default_headers = dict(self.DEFAULT_HEADERS)
        if headers:
            default_headers.update(headers)

        if not hasattr(self, '_client') or self._client is None or self._client.is_closed:
            limits = httpx.Limits(max_keepalive_connections=10, max_connections=20)
            self._client = httpx.Client(timeout=timeout, follow_redirects=True, limits=limits)

        response = self._client.request(
            method,
            url,
            headers=default_headers,
            timeout=timeout,
            json=json,
            data=data,
            params=params,
        )
        response.read()  # 确保读取响应体

        if raise_for_status:
            response.raise_for_status()
        return response

    def _resolve_url(self, url: str, base_url: Optional[str] = None) -> str:
        """
        解析 URL（处理相对路径）

        Args:
            url: 图片 URL
            base_url: 基础 URL

        Returns:
            str: 完整的 URL
        """
        from urllib.parse import urljoin
        if not base_url:
            if url.startswith('//'):
                return 'https:' + url
            return url
        return urljoin(base_url, url)

    def _extract_images(self, html: str, base_url: Optional[str] = None) -> List[str]:
        """
        从 HTML 中提取图片 URL

        Args:
            html: HTML 内容
            base_url: 基础 URL（用于解析相对路径）

        Returns:
            List[str]: 图片 URL 列表
        """
        if not html:
            return []

        from bs4 import BeautifulSoup
        from src.utils.helpers import HTML_PARSING_LOCK
        with HTML_PARSING_LOCK:
            soup = BeautifulSoup(html, 'lxml')
        images = []
        
        # 排除关键词
        exclude_keywords = ['avatar', 'logo', 'icon', 'button', 'loading', 'spacer', 'ad_']

        for img in soup.find_all('img'):
            # 1. 尝试多个候选属性
            src = None
            
            # 检查 srcset
            srcset = img.get('data-srcset') or img.get('srcset')
            if srcset:
                # 解析 srcset: "url1 300w, url2 600w"
                candidates = []
                for part in srcset.split(','):
                    parts = part.strip().split()
                    if parts:
                        url = parts[0]
                        if not any(ext in url.lower() for ext in ['.gif', '.svg']) and not url.lower().startswith('data:'):
                            candidates.append(url)
                if candidates:
                    src = candidates[-1] # 假设最后一个是最大的
            
            # 检查懒加载属性
            if not src:
                for attr in ['data-src', 'data-original', 'data-actualsrc', 'data-lazy-src', 'file', 'zoom-target', 'original']:
                    val = img.get(attr)
                    if val and not any(ext in val.lower() for ext in ['.gif', '.svg']):
                        src = val
                        break
            
            # 最后用 src
            if not src:
                src = img.get('src')
                
            if not src:
                continue
                
            # 2. 基础过滤
            if src.lower().startswith('data:') or any(ext in src.lower() for ext in ['.gif', '.svg']):
                continue
            
            # 排除明显的占位图/图标
            if any(kw in src.lower() for kw in exclude_keywords):
                # 除非它是唯一的图片或非常大，否则跳过
                pass 
                
            # 3. 解析为绝对路径
            full_url = self._resolve_url(src, base_url or self.source.src)
            if full_url not in images:
                images.append(full_url)

        return images

    def _extract_og_image(self, html: str, base_url: Optional[str] = None) -> List[str]:
        """
        从 HTML 的 <head> meta 标签中提取封面图 URL。

        适用于现代 SPA/新闻网站（如 Scientific American），这类网站的文章
        主图往往只存在于 og:image/twitter:image/<link rel="image_src"> 等
        meta 标签中，而不会出现在 trafilatura 提取的正文 HTML 里。

        Args:
            html: 原始完整 HTML
            base_url: 基础 URL（用于解析相对路径）

        Returns:
            List[str]: 封面图 URL 列表（去重），顺序：og:image > twitter:image > image_src
        """
        if not html:
            return []

        from bs4 import BeautifulSoup
        from src.utils.helpers import HTML_PARSING_LOCK
        with HTML_PARSING_LOCK:
            soup = BeautifulSoup(html, 'lxml')
        seen: set = set()
        result: List[str] = []

        def _add(url: str):
            if not url or url.startswith('data:'):
                return
            full = self._resolve_url(url, base_url)
            if full not in seen:
                seen.add(full)
                result.append(full)

        # og:image
        og = soup.find('meta', property='og:image')
        if og:
            _add(og.get('content', ''))

        # twitter:image
        tw = soup.find('meta', attrs={'name': 'twitter:image'})
        if tw:
            _add(tw.get('content', ''))

        # <link rel="image_src">
        link = soup.find('link', rel=lambda v: v and 'image_src' in v)
        if link:
            _add(link.get('href', '') or link.get('src', ''))

        if result:
            self.logger.debug(f"Extracted og:image candidates: {result}")
        return result

    @staticmethod
    def _restore_img_tags(html: str) -> str:
        """
        将 trafilatura 输出的 <graphic> 标签还原为 <img> 标签。

        trafilatura 在 output_format="html" 模式下会把 <img> 转换为
        <graphic>（EPUB/HTML5 标准元素），但下游的图片处理流程只识别 <img>。

        使用正则替换，避免 lxml 在解析时按 HTML 规则把 <p> 内的 <pre>
        自动拆段（<p>text <pre>code</pre> more</p> → </p><pre>），
        否则后续把单行 <pre> 转回 <code> 后会留下 </p><code>。
        """
        if not html:
            return html

        html = re.sub(r'<\s*graphic\b', '<img', html, flags=re.IGNORECASE)
        html = re.sub(r'</\s*graphic\s*>', '', html, flags=re.IGNORECASE)

        # trafilatura 会包一层 html/body；保持与原先 BeautifulSoup.decode_contents() 一致
        html = re.sub(r'(?is)^\s*<html[^>]*>\s*<body[^>]*>\s*', '', html, count=1)
        html = re.sub(r'(?is)\s*</body>\s*</html>\s*$', '', html, count=1)
        return html

    def _fetch_full_text(self, url: str) -> tuple:
        """
        抓取完整正文

        Args:
            url: 文章 URL

        Returns:
            tuple: (正文 HTML, 原始页面 HTML)。trafilatura 失败时正文为空字符串。
        """
        if not url:
            return "", ""

        try:
            response = self._make_request(url)
            raw_html = response.text

            # 使用 trafilatura 提取正文
            from src.utils.helpers import HTML_PARSING_LOCK
            with HTML_PARSING_LOCK:
                content = trafilatura.extract(
                    raw_html,
                    include_comments=False,
                    include_tables=True,
                    include_images=True,
                    include_links=True,
                    include_formatting=True,
                    output_format="html"
                )

            if content:
                # trafilatura 在 output_format="html" 时会将 <img> 转换为
                # <graphic>（HTML5 元素），导致下游的 ContentProcessor 和
                # EPUBGenerator 找不到 <img> 标签而丢失所有图片。
                # 这里将 <graphic src="..."> 转换回 <img src="...">。
                content = self._restore_img_tags(content)

            if not content:
                self.logger.warning(f"trafilatura failed to extract content from {url}")

            return content or "", raw_html

        except Exception as e:
            self.logger.error(f"Failed to fetch full text from {url}: {e}")
            return "", ""

    def _should_delete(self, title: str) -> bool:
        """
        检查是否应该删除该文章（基于 delete 配置）

        Args:
            title: 文章标题

        Returns:
            bool: 是否应该删除
        """
        if not self.source.delete:
            return False

        # 检查标题是否包含删除关键词
        keywords = self.source.delete.split(',')
        return any(keyword.strip() in title for keyword in keywords)
