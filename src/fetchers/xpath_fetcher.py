from typing import List, Optional, Any, Dict
from urllib.parse import urljoin
from lxml import html as lxml_html
from bs4 import BeautifulSoup
import trafilatura

from src.config import ContentSource
from src.fetchers.base import BaseFetcher, FetchResult, Article
from src.utils.helpers import get_now

class XPathListAutoFetcher(BaseFetcher):
    """
    智能列表提取与自动解析抓取器。
    
    1. 访问列表页，通过配置的 list_xpath 提取详情页链接。
    2. 继承并复用 BaseFetcher 的 _fetch_full_text 等辅助方法自动抓取和还原正文 HTML。
    3. 利用 trafilatura.extract_metadata 自动分析文章元数据，并配合 BeautifulSoup 提供兜底解析。
    """
    
    type_name = "xpath_list_auto"
    supports_two_phase = True
    src_placeholder = "请输入列表页的 URL"
    
    config_schema = {
        "metadata.list_xpath": {
            "type": "text",
            "label": "列表页链接 XPath",
            "placeholder": "例如: //div[@class='news-list']//a/@href"
        }
    }
    
    required_secrets = {}

    def __init__(self, source: ContentSource, global_limit: int = 15, max_retries: int = 3):
        super().__init__(source, global_limit=global_limit, max_retries=max_retries)

    def fetch(self) -> FetchResult:
        result = FetchResult(source=self.source, articles=[])
        
        try:
            metadata = self.source.metadata or {}
            list_xpath = metadata.get("list_xpath")
            
            if not list_xpath:
                raise ValueError("未配置 'list_xpath'，无法提取详情页链接。")

            list_url = self.source.src
            self.logger.info(f"开始访问列表页: {list_url}")
            
            # 1. 访问并解析列表页面
            response = self._make_request(list_url, browser=True)
            from src.utils.helpers import HTML_PARSING_LOCK
            with HTML_PARSING_LOCK:
                tree = lxml_html.fromstring(response.content)
            
            # 2. 提取、规范化并去重候选链接
            raw_links = tree.xpath(list_xpath)
            unique_links = []
            for link in raw_links:
                href = ""
                if isinstance(link, str):
                    href = link.strip()
                elif hasattr(link, "get"):
                    href = link.get("href", "").strip()
                elif hasattr(link, "text"):
                    href = link.text.strip()
                
                if href:
                    # 使用基类提供的 _resolve_url 解析绝对路径
                    full_url = self._resolve_url(href, list_url)
                    if full_url not in unique_links:
                        unique_links.append(full_url)
            
            self.logger.info(f"共发现 {len(unique_links)} 个候选链接。")
            
            # 根据全局限额截取抓取数量
            target_links = unique_links[:self.global_limit]
            
            # 3. 遍历详情链接并进行智能抓取
            for link in target_links:
                try:
                    self.logger.info(f"正在分析详情页: {link}")
                    
                    # 使用基类提供的 _fetch_full_text 获取正文 HTML 和原始 HTML
                    content_html, raw_html = self._fetch_full_text(link)
                    
                    title = ""
                    author = None
                    pub_date = None
                    
                    # 提取元数据 (标题、作者、发布时间)
                    if raw_html:
                        try:
                            from src.utils.helpers import HTML_PARSING_LOCK
                            with HTML_PARSING_LOCK:
                                meta = trafilatura.extract_metadata(raw_html, default_url=link)
                            if meta:
                                title = meta.title
                                author = meta.author
                                pub_date = meta.date
                        except Exception as meta_err:
                            self.logger.warning(f"使用 trafilatura 提取元数据失败 [{link}]: {meta_err}")
                    
                    # 降级策略 A：若元数据未能成功提取标题，采用 BeautifulSoup 兜底提取
                    if not title and raw_html:
                        from src.utils.helpers import HTML_PARSING_LOCK
                        with HTML_PARSING_LOCK:
                            soup = BeautifulSoup(raw_html, "lxml")
                        h1_node = soup.find("h1")
                        title = h1_node.get_text().strip() if h1_node else ""
                        if not title:
                            title_node = soup.find("title")
                            title = title_node.get_text().strip() if title_node else "Untitled"
                    
                    # 降级策略 B：若基类 _fetch_full_text 未能通过 trafilatura 抽取到正文
                    if not content_html and raw_html:
                        from src.utils.helpers import HTML_PARSING_LOCK
                        with HTML_PARSING_LOCK:
                            soup = BeautifulSoup(raw_html, "lxml")
                        possible_containers = [
                            soup.find("article"),
                            soup.find("div", class_="article"),
                            soup.find("div", class_="content"),
                            soup.find("div", class_="entry-content"),
                            soup.find("div", id="content"),
                            soup.find("main")
                        ]
                        for container in possible_containers:
                            if container:
                                content_html = str(container)
                                break
                        # 若仍没有，降级使用整个 body 
                        if not content_html and soup.body:
                            content_html = str(soup.body)
                    
                    # 填充发布日期：若没有抓取到时间，采用系统的北京时间兜底
                    if not pub_date:
                        pub_date = get_now().strftime("%Y-%m-%d %H:%M:%S")
                    
                    # 结合提取封面图（og:image等）与正文中的图片
                    og_images = self._extract_og_image(raw_html, link) if raw_html else []
                    body_images = self._extract_images(content_html, link) if content_html else []
                    
                    # 合并去重，保证封面图（如果有的话）排在前面
                    all_images = og_images.copy()
                    for img in body_images:
                        if img not in all_images:
                            all_images.append(img)
                    
                    # 组装 Article 数据对象
                    article = Article(
                        title=title or "Untitled",
                        content=content_html or "",
                        url=link,
                        author=author,
                        published_date=pub_date,
                        images=all_images
                    )
                    
                    # 使用基类提供的 _should_delete 检查标题屏蔽词
                    if not self._should_delete(article.title):
                        result.articles.append(article)
                    else:
                        self.logger.info(f"文章标题 '{article.title}' 匹配到屏蔽规则，已被过滤。")
                        
                except Exception as detail_err:
                    self.logger.error(f"提取详情页数据失败 [{link}]: {detail_err}")
                    result.error_count += 1
                    
            return result
            
        except Exception as e:
            self.logger.error(f"自动抓取运行失败: {e}")
            result.success = False
            result.error = str(e)
            return result

    # ------------------------------------------------------------------
    # 两阶段接口实现
    # ------------------------------------------------------------------

    def fetch_list(self) -> Optional[List[dict]]:
        """
        【阶段一】访问列表页并提取候选链接，不抓取任何详情页内容。

        Returns:
            list of dict with key: url
            失败时返回 None 以触发回退逻辑。
        """
        try:
            metadata = self.source.metadata or {}
            list_xpath = metadata.get("list_xpath")

            if not list_xpath:
                raise ValueError("未配置 'list_xpath'，无法提取详情页链接。")

            list_url = self.source.src
            self.logger.info(f"[阶段一] 访问列表页: {list_url}")

            response = self._make_request(list_url, browser=True)
            from src.utils.helpers import HTML_PARSING_LOCK
            with HTML_PARSING_LOCK:
                tree = lxml_html.fromstring(response.content)

            raw_links = tree.xpath(list_xpath)
            unique_links = []
            seen = set()
            for link in raw_links:
                href = ""
                if isinstance(link, str):
                    href = link.strip()
                elif hasattr(link, "get"):
                    href = link.get("href", "").strip()
                elif hasattr(link, "text"):
                    href = link.text.strip()

                if href:
                    full_url = self._resolve_url(href, list_url)
                    if full_url not in seen:
                        seen.add(full_url)
                        unique_links.append(full_url)

            self.logger.info(f"[阶段一] 共发现 {len(unique_links)} 个候选链接")

            return [{"url": url} for url in unique_links]

        except Exception as e:
            self.logger.error(f"[阶段一] fetch_list 失败: {e}")
            return None

    def fetch_items(self, candidates: List[dict]) -> "FetchResult":
        """
        【阶段二】对去重过滤后的候选链接抓取详情页全文。

        Args:
            candidates: fetch_list() 返回并经去重过滤的候选条目列表。
        """
        result = FetchResult(source=self.source, articles=[])

        if not candidates:
            self.logger.info("[阶段二] 无新候选链接，跳过详情页抓取")
            return result

        self.logger.info(f"[阶段二] 开始抓取 {len(candidates)} 个新详情页")

        for cand in candidates:
            link = cand["url"]
            try:
                self.logger.info(f"[阶段二] 抓取详情页: {link}")
                content_html, raw_html = self._fetch_full_text(link)

                title = ""
                author = None
                pub_date = None

                if raw_html:
                    try:
                        from src.utils.helpers import HTML_PARSING_LOCK
                        with HTML_PARSING_LOCK:
                            meta = trafilatura.extract_metadata(raw_html, default_url=link)
                        if meta:
                            title = meta.title
                            author = meta.author
                            pub_date = meta.date
                    except Exception as meta_err:
                        self.logger.warning(f"提取元数据失败 [{link}]: {meta_err}")

                if not title and raw_html:
                    from src.utils.helpers import HTML_PARSING_LOCK
                    with HTML_PARSING_LOCK:
                        soup = BeautifulSoup(raw_html, "lxml")
                    h1_node = soup.find("h1")
                    title = h1_node.get_text().strip() if h1_node else ""
                    if not title:
                        title_node = soup.find("title")
                        title = title_node.get_text().strip() if title_node else "Untitled"

                if not content_html and raw_html:
                    from src.utils.helpers import HTML_PARSING_LOCK
                    with HTML_PARSING_LOCK:
                        soup = BeautifulSoup(raw_html, "lxml")
                    possible_containers = [
                        soup.find("article"),
                        soup.find("div", class_="article"),
                        soup.find("div", class_="content"),
                        soup.find("div", class_="entry-content"),
                        soup.find("div", id="content"),
                        soup.find("main")
                    ]
                    for container in possible_containers:
                        if container:
                            content_html = str(container)
                            break
                    if not content_html and soup.body:
                        content_html = str(soup.body)

                if not pub_date:
                    pub_date = get_now().strftime("%Y-%m-%d %H:%M:%S")

                og_images = self._extract_og_image(raw_html, link) if raw_html else []
                body_images = self._extract_images(content_html, link) if content_html else []
                all_images = og_images.copy()
                for img in body_images:
                    if img not in all_images:
                        all_images.append(img)

                article = Article(
                    title=title or "Untitled",
                    content=content_html or "",
                    url=link,
                    author=author,
                    published_date=pub_date,
                    images=all_images
                )

                if not self._should_delete(article.title):
                    result.articles.append(article)
                else:
                    self.logger.info(f"文章标题 '{article.title}' 匹配屏蔽规则，已过滤。")

            except Exception as detail_err:
                self.logger.error(f"提取详情页失败 [{link}]: {detail_err}")
                result.error_count += 1

        if result.articles:
            result.success = True

        return result