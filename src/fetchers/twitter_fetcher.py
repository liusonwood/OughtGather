from typing import Dict, Any, Optional, List
from urllib.parse import urlparse

from src.config import ContentSource
from src.fetchers.base import BaseFetcher, FetchResult, Article


class TwitterFetcher(BaseFetcher):
    """
    X (Twitter) 抓取器插件 (基于 FxTwitter API v2 稳定抓取)
    """

    type_name = "twitter"
    src_placeholder = "输入 X 用户名、x.com 链接 (例如 WolframResearch 或 https://x.com/WolframResearch)"
    config_schema = {
        "metadata.exclude_replies": {
            "type": "select",
            "label": "排除回复推文 (Replies)",
            "options": [
                {"label": "否 (保留回复)", "value": False},
                {"label": "是 (仅保留独立推文)", "value": True}
            ]
        },
        "metadata.exclude_rts": {
            "type": "select",
            "label": "排除转推 (Retweets)",
            "options": [
                {"label": "否 (保留转推)", "value": False},
                {"label": "是 (仅保留原推)", "value": True}
            ]
        }
    }
    required_secrets: Dict[str, str] = {}

    def __init__(self, source: ContentSource, global_limit: int = 15, max_retries: int = 3):
        super().__init__(source, global_limit=global_limit, max_retries=max_retries)

    def _extract_username(self, src: str) -> str:
        """
        从输入的 src 中提取 Twitter/X 用户名
        支持格式：
        1. WolframResearch
        2. @WolframResearch
        3. https://x.com/WolframResearch
        4. https://twitter.com/WolframResearch
        """
        src = src.strip()
        if src.startswith("http://") or src.startswith("https://"):
            parsed = urlparse(src)
            path_parts = [p for p in parsed.path.split("/") if p]
            if path_parts:
                return path_parts[0].lstrip("@")
            return ""
        return src.lstrip("@")

    def fetch(self) -> FetchResult:
        result = FetchResult(source=self.source, articles=[])
        username = self._extract_username(self.source.src)

        if not username:
            result.success = False
            result.error = "配置的 src 无法识别出有效的 X/Twitter 用户名"
            return result

        metadata = self.source.metadata or {}
        exclude_replies = bool(metadata.get("exclude_replies", False))
        exclude_rts = bool(metadata.get("exclude_rts", False))

        try:
            self.logger.info(f"正在尝试使用 FxTwitter API 抓取账号 [@{username}] 的最新推文...")
            api_url = f"https://api.fxtwitter.com/2/profile/{username}/statuses"
            api_headers = {
                "Accept": "application/json"
            }
            response = self._make_request(api_url, headers=api_headers, timeout=15)
            api_data = response.json()
            
            if api_data.get("code") == 200 and isinstance(api_data.get("results"), list):
                tweets = api_data["results"]
                limit = int(metadata.get("limit", self.global_limit or 15))
                result.source_title = f"X (@{username})"
                
                for tweet in tweets:
                    if limit and len(result.articles) >= limit:
                        break
                        
                    # 过滤条件：排除回复 (Replies)
                    if exclude_replies and tweet.get("replying_to") is not None:
                        continue
                        
                    # 过滤条件：排除转推 (Retweets)
                    if exclude_rts and tweet.get("reposted_by") is not None:
                        continue
                        
                    tweet_id = tweet.get("id", "")
                    canonical_url = tweet.get("url") or f"https://x.com/{username}/status/{tweet_id}"
                    text = tweet.get("text", "")
                    pub_date = tweet.get("created_at")
                    
                    author_info = tweet.get("author", {})
                    author_name = author_info.get("name") or username
                    author_handle = author_info.get("screen_name") or username
                    author = f"@{author_handle}"
                    
                    # 提取图片
                    images = []
                    media_info = tweet.get("media", {})
                    for photo in media_info.get("photos", []):
                        if "url" in photo:
                            images.append(photo["url"])
                            
                    # 构建 HTML 描述
                    text_html = text.replace('\n', '<br />')
                    content_html = f"<p>{text_html}</p>"
                    for img_url in images:
                        content_html += f'<p><img src="{img_url}" /></p>'
                        
                    # 生成干净纯文本标题
                    formatted_title = text.replace('\n', ' ')[:80] + ("..." if len(text) > 80 else "")
                    if not formatted_title:
                        formatted_title = f"X 推文由 @{username} 发布"
                        
                    # 基于删除关键词进行屏蔽过滤
                    if self._should_delete(formatted_title):
                        self.logger.debug(f"命中删除关键词，跳过推文: {formatted_title}")
                        continue
                        
                    article = Article(
                        title=formatted_title,
                        content=content_html,
                        url=canonical_url,
                        author=author,
                        published_date=pub_date,
                        images=images,
                        metadata={
                            "instance_used": "api.fxtwitter.com",
                            "username": username,
                            "tweet_id": tweet_id
                        }
                    )
                    result.articles.append(article)
                    
                self.logger.info(f"成功获取 {len(result.articles)} 条来自 @{username} 的推文")
                result.success = True
                return result
            else:
                result.success = False
                result.error = f"FxTwitter API 返回响应异常: code={api_data.get('code')}, message={api_data.get('message')}"
                return result
        except Exception as e:
            self.logger.error(f"FxTwitter API 抓取推文失败: {e}")
            result.success = False
            result.error = f"API 抓取错误: {str(e)}"
            return result
