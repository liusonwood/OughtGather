import os
import re
from typing import List, Optional
from urllib.parse import quote
from bs4 import BeautifulSoup

from src.config import ContentSource
from src.fetchers.base import BaseFetcher, FetchResult, Article
from src.utils.logger import get_logger
from src.utils.helpers import format_date


class MailFetcher(BaseFetcher):
    """邮件抓取器"""

    type_name = "mail"
    src_placeholder = "namespace 或 namespace.tag, 例如: abcde.test"
    config_schema = {
        "metadata.tag": {"type": "text", "label": "tag"},
        "metadata.tag_prefix": {"type": "text", "label": "tag_prefix"},
        "metadata.timestamp_from": {"type": "number", "label": "timestamp_from", "placeholder": "毫秒时间戳"},
        "metadata.timestamp_to": {"type": "number", "label": "timestamp_to", "placeholder": "毫秒时间戳"},
        "metadata.limit": {"type": "number", "label": "limit"},
        "metadata.offset": {"type": "number", "label": "offset"}
    }
    required_secrets = {
        "TESTMAIL_APP_API_KEY": "从 testmail.app 获取的 API Key，用于邮件抓取。"
    }

    def __init__(self, source: ContentSource, global_limit: int = 15, max_retries: int = 3):
        """
        初始化邮件抓取器

        Args:
            source: 内容源配置
            global_limit: 全局抓取数量限制
            max_retries: 最大重试次数
        """
        super().__init__(source, global_limit=global_limit, max_retries=max_retries)
        api_key = os.environ.get("TESTMAIL_APP_API_KEY")
        self.config = {"api_key": api_key} if api_key else None

        if not self.config:
            self.logger.warning(
                "TESTMAIL_APP_API_KEY not configured. Mail fetching will be skipped."
            )

    def fetch(self) -> FetchResult:
        """
        执行邮件抓取

        Returns:
            FetchResult: 抓取结果
        """
        result = FetchResult(source=self.source, articles=[])

        # 检查配置
        if not self.config:
            result.success = False
            result.error = "TESTMAIL_APP_API_KEY not configured"
            return result

        try:
            # 调用 testmail.app API
            # API 文档: https://testmail.app/docs/#using-cypress-json-api
            # src 格式: "namespace" 或 "namespace.tag"
            # 如果有 "."，第一部分是 namespace，第二部分是 tag
            src_clean = self.source.src.replace(' ', '')
            if '.' in src_clean:
                namespace, tag = src_clean.split('.', 1)
            else:
                namespace, tag = src_clean, None

            namespace_encoded = quote(namespace, safe='')
            api_url = (
                f"https://api.testmail.app/api/json"
                f"?apikey={self.config['api_key']}"
                f"&namespace={namespace_encoded}"
            )

            # 添加可选的查询参数（tag 可以从 src 或 metadata 中获取）
            api_url += self._build_query_params(tag)

            response = self._make_request(api_url)
            data = response.json()

            # 检查 API 响应
            if data.get("result") != "success":
                error_msg = data.get("message", "Unknown API error")
                result.success = False
                result.error = f"API error: {error_msg}"
                return result

            # 解析邮件列表
            emails = data.get("emails", [])
            self.logger.info(f"Found {len(emails)} emails in namespace '{self.source.src}'")

            for email in emails:
                try:
                    article = self._parse_email(email)
                    if article and not self._should_delete(article.title):
                        result.articles.append(article)
                except Exception as e:
                    self.logger.error(f"Failed to parse email: {e}")
                    result.add_error(f"Failed to parse email: {e}")

            return result

        except Exception as e:
            self.logger.error(f"Mail fetch failed: {e}")
            result.success = False
            result.error = str(e)
            return result

    def _parse_email(self, email: dict) -> Article:
        """
        解析单个邮件

        Args:
            email: 邮件数据（JSON 格式）

        Returns:
            Article: 文章对象
        """
        # 提取邮件信息
        subject = email.get("subject", "No Subject")
        from_addr = email.get("from", "")
        timestamp = format_date(email.get("timestamp", ""))

        # 提取 HTML 内容
        html_content = email.get("html", "")

        # 如果没有 HTML，使用纯文本
        if not html_content:
            text_content = email.get("text", "")
            html_content = f"<p>{text_content}</p>"

        # 提取图片
        images = self._extract_images(html_content)

        # 应用内容处理规则
        html_content = self._apply_content_rules(html_content)

        # 清洗 HTML，确保能被 ebooklib 正确解析为 XHTML
        html_content = self._sanitize_html(html_content)

        return Article(
            title=subject,
            content=html_content,
            url=f"mailto:{from_addr}",
            author=from_addr,
            published_date=timestamp,
            images=images,
            metadata={
                "to": email.get("to", ""),
                "attachments": email.get("attachments", [])
            }
        )

    # 与 ContentProcessor 对齐：邮件头/尾社交分享图标关键词
    _SOCIAL_IMAGE_HINTS = (
        'share on', 'facebook', 'twitter', 'linkedin', 'instagram',
        'threads', 'whatsapp', 'telegram', 'weibo', 'wechat',
        'pinterest', 'reddit', 'tiktok', 'youtube',
        'static_assets/header/', '/x.png', 'x_light', 'social',
    )

    def _extract_images(self, html: str) -> List[str]:
        """
        从 HTML 中提取图片 URL，并跳过社交分享图标与跟踪像素。

        邮件 HTML 开头常见 Facebook/X/LinkedIn 等 18px 分享图标；
        若不过滤，会成为 article.images 首图并被 ContentProcessor 当作 lead image 插入。

        Args:
            html: HTML 内容

        Returns:
            List[str]: 图片 URL 列表
        """
        if not html:
            return []

        from src.utils.helpers import HTML_PARSING_LOCK
        with HTML_PARSING_LOCK:
            soup = BeautifulSoup(html, 'lxml')
        images = []

        for img in soup.find_all('img'):
            src = img.get('src')
            if not src or src.startswith('data:image'):
                continue
            if self._is_decorative_mail_image(img):
                continue
            images.append(src)

        return images

    def _is_decorative_mail_image(self, img) -> bool:
        """判断邮件中的社交图标 / 跟踪像素等装饰图。"""
        sizes = []
        for attr in ('width', 'height'):
            val = img.get(attr)
            if val is None:
                continue
            raw = str(val).strip().lower().replace('px', '')
            if raw.isdigit():
                sizes.append(int(raw))

        style = (img.get('style') or '').lower()
        for match in re.findall(r'(?:max-)?(?:width|height)\s*:\s*(\d+(?:\.\d+)?)px', style):
            try:
                sizes.append(int(float(match)))
            except ValueError:
                pass

        size = min(sizes) if sizes else None
        alt = (img.get('alt') or '').lower()
        src = (img.get('src') or '').lower()
        combined = f'{alt} {src}'

        # 跟踪像素
        if size is not None and size <= 2:
            return True

        is_small = size is not None and size <= 32
        if not is_small:
            return False

        if img.find_parent('a'):
            return True

        if any(hint in combined for hint in self._SOCIAL_IMAGE_HINTS):
            return True

        return False

    def _apply_content_rules(self, html: str) -> str:
        """
        应用内容处理规则（chop、exclude）

        Args:
            html: HTML 内容

        Returns:
            str: 处理后的 HTML
        """
        if not html:
            return html

        # TODO: 实现 chop 和 exclude 规则
        # 这些规则将在 content_processor 中统一处理

        return html

    def _sanitize_html(self, html: str) -> str:
        """
        清洗 HTML，确保能被 ebooklib 正确解析为 XHTML

        使用 BeautifulSoup 解析并重新序列化，修复以下问题：
        - 未闭合的标签
        - 未转义的 & 字符
        - 非法的 XML 属性名

        Args:
            html: HTML 内容

        Returns:
            str: 清洗后的 HTML
        """
        if not html:
            return html

        try:
            # 优先使用 lxml，因为它对 XHTML 的支持更好
            from src.utils.helpers import HTML_PARSING_LOCK
            with HTML_PARSING_LOCK:
                soup = BeautifulSoup(html, 'lxml')

            # 移除所有不合法的属性名
            for tag in soup.find_all(True):
                attrs_to_remove = []
                for attr in tag.attrs:
                    # XML 属性名规范：
                    # 1. 必须以字母、下划线或冒号开头
                    # 2. 后续字符可以是字母、数字、点、减号、下划线或冒号
                    # 3. 不能包含空格和其他特殊字符
                    if not re.match(r'^[a-zA-Z_:][a-zA-Z0-9._\-:]*$', attr):
                        attrs_to_remove.append(attr)
                    # 此外，XHTML 推荐属性名使用小写
                    elif attr != attr.lower():
                        # 如果有大写，转换为小写（BeautifulSoup 默认会转，这里是保险）
                        val = tag.attrs[attr]
                        attrs_to_remove.append(attr)
                        tag.attrs[attr.lower()] = val
                        
                for attr in attrs_to_remove:
                    if attr in tag.attrs:
                        del tag[attr]

            # 仅返回 body 内部的内容片段
            if soup.body:
                return soup.body.decode_contents()
            return str(soup)

        except Exception as e:
            self.logger.warning(f"Failed to sanitize HTML: {e}")
            return html

    def _build_query_params(self, tag_from_src: Optional[str] = None) -> str:
        """
        构建可选的查询参数

        支持通过 source.metadata 配置以下参数：
        - tag: 按标签过滤
        - tag_prefix: 按标签前缀过滤
        - timestamp_from: 起始时间戳（毫秒）
        - timestamp_to: 结束时间戳（毫秒）
        - limit: 返回邮件数量限制（默认 10，最大 100）
        - offset: 偏移量（默认 0，最大 9899）

        Args:
            tag_from_src: 从 src 字段解析出的 tag（如 "namespace.tag" 中的 "tag"）

        Returns:
            str: 查询参数字符串
        """
        params = []

        # 从 metadata 中读取可选参数
        metadata = self.source.metadata if hasattr(self.source, 'metadata') else {}

        if not metadata:
            # 默认只返回最新的邮件（使用全局限制）
            if tag_from_src:
                params.append(f"tag={quote(tag_from_src, safe='')}")
            params.append(f"limit={self.global_limit}")
            return "&" + "&".join(params) if params else ""

        # 标签过滤（metadata 中的 tag 优先于 src 中的 tag）
        if "tag" in metadata:
            params.append(f"tag={quote(str(metadata['tag']), safe='')}")
        elif tag_from_src:
            params.append(f"tag={quote(tag_from_src, safe='')}")

        if "tag_prefix" in metadata:
            params.append(f"tag_prefix={quote(str(metadata['tag_prefix']), safe='')}")

        # 时间范围过滤
        if "timestamp_from" in metadata:
            params.append(f"timestamp_from={metadata['timestamp_from']}")

        if "timestamp_to" in metadata:
            params.append(f"timestamp_to={metadata['timestamp_to']}")

        # 数量和偏移
        limit = min(metadata.get("limit", self.global_limit), 100)  # 最大 100
        params.append(f"limit={limit}")

        if "offset" in metadata:
            params.append(f"offset={metadata['offset']}")

        return "&" + "&".join(params) if params else ""
