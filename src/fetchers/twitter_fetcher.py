from typing import Dict, Any, Optional, List
from urllib.parse import urlparse
from bs4 import BeautifulSoup

from src.config import ContentSource
from src.fetchers.base import BaseFetcher, FetchResult, Article


class TwitterFetcher(BaseFetcher):
    """
    X (Twitter) 抓取器插件 (支持多 Nitter/xcancel 节点自动容灾轮询)
    默认优先使用 xcancel.com，若该节点出现异常将自动无缝切换至备用镜像节点抓取。
    """

    type_name = "twitter"
    src_placeholder = "输入 X 用户名、x.com 链接或 xcancel.com RSS 链接 (例如 WolframResearch 或 https://xcancel.com/WolframResearch/rss)"
    config_schema = {
        "metadata.nitter_instance": {
            "type": "text",
            "label": "首选 Nitter / xcancel 节点域名",
            "placeholder": "https://xcancel.com (留空则按内置默认节点自动重试切换)"
        },
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

    # 默认节点轮询池（按优先级排列，前面的节点失败时自动切换后面的备用节点）
    DEFAULT_NODES = [
        "https://xcancel.com",
        "https://nitter.poast.org",
        "https://nitter.privacydev.net",
        "https://nitter.kylrth.com"
    ]

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
        5. https://xcancel.com/WolframResearch/rss
        """
        src = src.strip()
        if src.startswith("http://") or src.startswith("https://"):
            parsed = urlparse(src)
            path_parts = [p for p in parsed.path.split("/") if p]
            if path_parts:
                if path_parts[-1].lower() == "rss" and len(path_parts) >= 2:
                    return path_parts[-2].lstrip("@")
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
        custom_instance = metadata.get("nitter_instance", "").strip().rstrip("/")

        # 1. 构建候选节点列表（首选用户指定的节点，然后加入内置备用节点列表）
        candidate_nodes: List[str] = []
        if custom_instance:
            if not custom_instance.startswith("http"):
                custom_instance = f"https://{custom_instance}"
            candidate_nodes.append(custom_instance)

        for default_node in self.DEFAULT_NODES:
            if default_node not in candidate_nodes:
                candidate_nodes.append(default_node)

        exclude_replies = bool(metadata.get("exclude_replies", False))
        exclude_rts = bool(metadata.get("exclude_rts", False))

        # 伪装请求头（绕过反爬虫判定）
        rss_headers = {
            "User-Agent": "FeedParser/6.0.10 (https://github.com/kurtmckee/feedparser)",
            "Accept": "application/rss+xml, application/xml, text/xml, */*"
        }

        raw_xml = None
        used_instance = None
        last_error = None

        # 2. 轮询节点池，直到找到可用的节点
        for instance in candidate_nodes:
            rss_url = f"{instance}/{username}/rss"
            try:
                self.logger.info(f"正在尝试节点 [{instance}] 抓取账号 [@{username}] 的最新推文...")
                response = self._make_request(rss_url, headers=rss_headers, timeout=15)
                content = response.text

                # 校验节点返回数据是否为有效 XML 且未弹出阻断拦截
                if "<rss" in content.lower() and "only works inside an rss client" not in content.lower():
                    raw_xml = content
                    used_instance = instance
                    self.logger.info(f"节点 [{instance}] 请求成功！")
                    break
                else:
                    self.logger.warning(f"节点 [{instance}] 未返回有效 RSS 数据，尝试自动切换至下一个备用节点...")
                    last_error = f"节点 [{instance}] 返回响应不符合 RSS 规范"
            except Exception as e:
                self.logger.warning(f"节点 [{instance}] 访问失败 ({e})，尝试自动切换至下一个备用节点...")
                last_error = f"节点 [{instance}] 请求异常: {str(e)}"

        # 若所有备用节点均告失败，抛出错误记录
        if not raw_xml or not used_instance:
            result.success = False
            result.error = f"所有候选 Nitter/xcancel 节点均抓取失败。最后错误: {last_error}"
            return result

        # 3. 解析抓取成功的 XML 数据
        try:
            soup = BeautifulSoup(raw_xml, "xml")
            channel = soup.find("channel")
            if channel:
                channel_title = channel.find("title")
                result.source_title = channel_title.get_text(strip=True) if channel_title else f"X (@{username})"

            items = soup.find_all("item")
            metadata = self.source.metadata or {}
            limit = int(metadata.get("limit", self.global_limit or 15))

            for item in items:
                if limit and len(result.articles) >= limit:
                    break

                title_elem = item.find("title")
                desc_elem = item.find("description")
                link_elem = item.find("link")
                date_elem = item.find("pubDate")
                creator_elem = item.find("dc:creator") or item.find("author")

                raw_title = title_elem.get_text(strip=True) if title_elem else ""
                content_html = desc_elem.get_text() if desc_elem else ""
                nitter_link = link_elem.get_text(strip=True) if link_elem else ""
                pub_date = date_elem.get_text(strip=True) if date_elem else None
                author = creator_elem.get_text(strip=True) if creator_elem else f"@{username}"

                # 4. 过滤条件：排除回复 (Replies)
                if exclude_replies:
                    if raw_title.startswith("R to @"):
                        continue

                # 5. 过滤条件：排除转推 (Retweets)
                if exclude_rts:
                    if raw_title.startswith("RT by @"):
                        continue

                # 6. 将节点链接转换为 x.com 官方原文链接（如果是转推，则指向原推作者而非当前用户名）
                tweet_username = author.lstrip("@") if author else username
                if "/status/" in nitter_link:
                    status_id = nitter_link.split("/status/")[-1].split("#")[0]
                    canonical_url = f"https://x.com/{tweet_username}/status/{status_id}"
                else:
                    canonical_url = f"https://x.com/{tweet_username}"

                # 7. 提取推文中的图片资源
                images = self._extract_images(content_html, base_url=used_instance)

                # 8. 生成干净纯文本标题
                text_content = BeautifulSoup(content_html, "lxml").get_text(strip=True)
                formatted_title = text_content[:80] + ("..." if len(text_content) > 80 else "")
                if not formatted_title:
                    formatted_title = f"X 推文由 @{username} 发布"

                # 9. 基于删除关键词进行屏蔽过滤
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
                        "instance_used": used_instance,
                        "username": username,
                        "rss_url": f"{used_instance}/{username}/rss"
                    }
                )

                result.articles.append(article)

            self.logger.info(f"成功获取 {len(result.articles)} 条来自 @{username} 的推文 (使用节点: {used_instance})")
            return result

        except Exception as e:
            self.logger.error(f"解析推文 XML 数据失败: {e}")
            result.success = False
            result.error = f"XML 解析错误: {str(e)}"
            return result
