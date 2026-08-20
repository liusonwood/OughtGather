from typing import List, Optional
import feedparser
import os

from src.config import ContentSource
from src.fetchers.base import BaseFetcher, FetchResult, Article
from src.utils.logger import get_logger
from src.utils.helpers import format_date

class TelegramFetcher(BaseFetcher):
    """
    Telegram 频道抓取器 (基于 RSSHub)
    支持直接输入频道 ID，通过 RSSHub 转换为 RSS 订阅
    """

    type_name = "telegram"
    src_placeholder = "Telegram 频道 ID, 例如: durov"
    
    # 默认公用 RSSHub 节点池，用于故障转移 (Failover)
    DEFAULT_NODES = [
        "https://rsshub.rssforever.com",
        "https://rsshub.app",
        "https://rsshub.outv.im",
        "https://rsshub.m-f.space"
    ]

    config_schema = {
        "metadata.rsshub_host": {
            "type": "text",
            "label": "RSSHub 实例地址",
            "placeholder": "rsshub.rssforever.com",
            "hint": "默认使用 rsshub.rssforever.com"
        },
        "metadata.limit": {
            "type": "number",
            "label": "抓取条目数",
            "placeholder": "15"
        },
        "metadata.route_params": {
            "type": "text",
            "label": "额外路由参数",
            "placeholder": "showEmoji=1",
            "hint": "RSSHub Telegram 路由的额外参数"
        }
    }

    def fetch(self) -> FetchResult:
        """
        执行 Telegram 抓取，支持多节点轮询 failover
        """
        result = FetchResult(source=self.source, articles=[])
        
        try:
            channel_src = self.source.src
            if not channel_src or not channel_src.strip():
                result.success = False
                result.error = "Telegram channel ID cannot be empty"
                return result

            channel_id = channel_src.strip()
            # 如果用户输入了完整的 URL 或带 @ 的 ID，进行简单处理
            channel_id = channel_id.split('/')[-1].replace('@', '')
            if not channel_id:
                result.success = False
                result.error = "Invalid Telegram channel ID"
                return result

            # 1. 构造待重试的 RSSHub 节点列表
            metadata = self.source.metadata or {}
            custom_host = metadata.get("rsshub_host")
            
            candidate_hosts = []
            if custom_host:
                candidate_hosts.append(custom_host)
            
            for d_host in self.DEFAULT_NODES:
                if d_host not in candidate_hosts:
                    candidate_hosts.append(d_host)

            # 2. 规范化节点 URL
            normalized_hosts = []
            for host in candidate_hosts:
                host_str = host.strip().rstrip('/')
                if not host_str:
                    continue
                if not host_str.startswith(('http://', 'https://')):
                    host_str = 'https://' + host_str
                normalized_hosts.append(host_str)

            if not normalized_hosts:
                result.success = False
                result.error = "No valid RSSHub hosts available"
                return result

            # 3. 轮询节点抓取
            feed = None
            last_error = None
            rss_url_used = ""

            for host in normalized_hosts:
                rss_url = f"{host}/telegram/channel/{channel_id}"
                
                # 添加额外参数
                route_params = metadata.get("route_params")
                if route_params:
                    # 确保 route_params 不带首部 ? 
                    route_params_str = route_params.strip().lstrip('?')
                    if route_params_str:
                        rss_url += f"?{route_params_str}"

                try:
                    self.logger.info(f"Fetching Telegram channel via node {host}: {rss_url}")
                    response = self._make_request(rss_url)
                    parsed_feed = feedparser.parse(response.text)

                    # 检查解析错误
                    if not parsed_feed.entries and parsed_feed.bozo:
                        raise Exception(f"RSS parsing error on node: {parsed_feed.bozo_exception}")

                    feed = parsed_feed
                    rss_url_used = rss_url
                    break  # 成功抓取并解析，退出节点循环
                except Exception as e:
                    self.logger.warning(f"Failed fetching via {host}: {e}")
                    last_error = e

            if feed is None:
                raise Exception(f"All RSSHub nodes failed. Last error: {last_error}")

            # 设置源标题（频道名称）
            result.source_title = feed.feed.get("title", f"Telegram: {channel_id}")

            # 4. 限制条目数量
            limit_val = metadata.get("limit") or self.global_limit or 15
            try:
                limit = int(limit_val)
            except (ValueError, TypeError):
                limit = 15
                
            entries = feed.entries[:limit]

            # 5. 解析条目
            for entry in entries:
                try:
                    article = self._parse_entry(entry)
                    if article and not self._should_delete(article.title):
                        result.articles.append(article)
                except Exception as e:
                    self.logger.error(f"Failed to parse Telegram entry: {e}")
                    result.add_error(f"Entry parsing failed: {e}")

            return result

        except Exception as e:
            self.logger.error(f"Telegram fetch failed: {e}")
            result.success = False
            result.error = str(e)
            return result

    def _parse_entry(self, entry: dict) -> Optional[Article]:
        """
        解析单个 Telegram 消息条目
        """
        # Telegram 消息通常没有独立的标题，RSSHub 会截取内容作为标题
        title = entry.get("title", "Telegram Message")
        link = entry.get("link", "")
        author = entry.get("author", "")
        published = format_date(entry.get("published", ""))

        # 提取内容：Telegram 的 RSSHub 输出通常在 summary 或 description 中
        content = ""
        if "content" in entry and len(entry.content) > 0:
            content = entry.content[0].get("value", "")
        else:
            content = entry.get("summary") or entry.get("description", "")

        if not content:
            return None

        # 提取图片：Telegram 消息中的图片通常直接嵌入在 HTML 中
        # 使用基类提供的 _extract_images
        images = self._extract_images(content, base_url=link)

        return Article(
            title=title,
            content=content,
            url=link,
            author=author,
            published_date=published,
            images=images,
            metadata={
                "source_type": "telegram",
                "original_link": entry.get("link")
            }
        )
