import os
from typing import List, Optional

from src.config import ContentSource
from src.fetchers.base import BaseFetcher, FetchResult, Article

class RaindropFetcher(BaseFetcher):
    """Raindrop.io Fetcher"""
    
    type_name = "raindropio"
    supports_two_phase = True
    src_placeholder = "Enter Raindropio collection ID (e.g., 1234567, or 0 for Unsorted)"
    config_schema = {}
    required_secrets = {
        "RAINDROPIO_API_KEY": "Raindrop.io 的 API 访问密钥。"
    }

    def __init__(self, source: ContentSource, global_limit: int = 15, max_retries: int = 3):
        super().__init__(source, global_limit=global_limit, max_retries=max_retries)
        api_key = os.environ.get("RAINDROPIO_API_KEY")
        if not api_key:
            raise ValueError(
                "Required secret 'RAINDROPIO_API_KEY' is not set. "
                "Please add it to GitHub Secrets or environment variables."
            )
        self.api_key = api_key

    def fetch(self) -> FetchResult:
        """
        Execute fetch operation from Raindrop.io.
        """
        result = FetchResult(source=self.source, articles=[])
        
        try:
            # Use source.src as collection ID
            collection_id = self.source.src
            
            # Raindrop API URL
            url = f"https://api.raindrop.io/rest/v1/raindrops/{collection_id}"
            
            # API Request
            headers = {
                "Authorization": f"Bearer {self.api_key}",
                "Content-Type": "application/json"
            }
            
            # Using base fetcher's request method
            response = self._make_request(url, headers=headers)
            data = response.json()
            
            if not data.get("result"):
                raise Exception(f"Raindropio API error: {data.get('message', 'Unknown error')}")
                
            raindrops = data.get("items", [])
            
            # Process articles
            for item in raindrops[:self.global_limit]:
                title = item.get("title")
                url = item.get("link")
                excerpt = item.get("excerpt", "")
                
                # Always attempt full text extraction
                content = None
                if url:
                    content, _ = self._fetch_full_text(url)
                
                if not content:
                    # Fallback to excerpt
                    content = f"<p>{excerpt}</p>"
                
                # Check for images
                images = []
                if item.get("cover"):
                    images.append(item.get("cover"))
                    
                article = Article(
                    title=title,
                    content=content,
                    url=url,
                    images=images
                )
                
                if not self._should_delete(article.title):
                    result.articles.append(article)

            return result

        except Exception as e:
            self.logger.error(f"Raindropio fetch failed: {e}")
            result.success = False
            result.error = str(e)
            return result

    # ------------------------------------------------------------------
    # 两阶段接口实现
    # ------------------------------------------------------------------

    def fetch_list(self) -> Optional[List[dict]]:
        """
        【阶段一】调用 Raindrop.io API 获取书签列表，不抓取任何全文。

        Returns:
            list of dict with keys: url, title, excerpt, cover
            失败时返回 None 以触发回退逻辑。
        """
        try:
            collection_id = self.source.src
            url = f"https://api.raindrop.io/rest/v1/raindrops/{collection_id}"
            headers = {
                "Authorization": f"Bearer {self.api_key}",
                "Content-Type": "application/json"
            }

            response = self._make_request(url, headers=headers)
            data = response.json()

            if not data.get("result"):
                raise Exception(f"Raindropio API error: {data.get('message', 'Unknown error')}")

            raindrops = data.get("items", [])
            self.logger.info(
                f"[fetch_list] Raindrop API 返回 {len(raindrops)} 条书签"
            )

            candidates = []
            for item in raindrops:
                candidates.append({
                    "url": item.get("link", ""),
                    "title": item.get("title", ""),
                    "excerpt": item.get("excerpt", ""),
                    "cover": item.get("cover", ""),
                })

            return candidates

        except Exception as e:
            self.logger.error(f"[fetch_list] Raindropio fetch_list failed: {e}")
            return None

    def fetch_items(self, candidates: List[dict]) -> "FetchResult":
        """
        【阶段二】对去重过滤后的书签执行全文抓取，返回 FetchResult。

        Args:
            candidates: fetch_list() 返回并经去重过滤的候选条目列表。
        """
        result = FetchResult(source=self.source, articles=[])

        if not candidates:
            self.logger.info("[fetch_items] 无新书签，跳过全文抓取")
            return result

        self.logger.info(f"[fetch_items] 开始抓取 {len(candidates)} 个新书签")

        for cand in candidates:
            url = cand.get("url", "")
            title = cand.get("title", "")
            excerpt = cand.get("excerpt", "")
            cover = cand.get("cover", "")

            content = None
            if url:
                content, _ = self._fetch_full_text(url)

            if not content:
                content = f"<p>{excerpt}</p>"

            images = [cover] if cover else []

            article = Article(
                title=title,
                content=content,
                url=url,
                images=images
            )

            if not self._should_delete(article.title):
                result.articles.append(article)

        if result.articles:
            result.success = True

        return result
