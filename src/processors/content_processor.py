"""
内容处理器模块
负责内容清洗、格式化和规则应用
"""

import html as html_module
import re
import warnings
from typing import Optional
from bs4 import BeautifulSoup, MarkupResemblesLocatorWarning

# 过滤掉 BeautifulSoup 的 "输入内容看起来像 URL 而非 HTML" 警告（因为我们在处理纯文本中的 Emoji 时，不可避免会解析 URL 标题或文本）
warnings.filterwarnings("ignore", category=MarkupResemblesLocatorWarning)

from src.config import ContentSource
from src.fetchers.base import Article
from src.utils.logger import get_logger


class ContentProcessor:
    """内容处理器"""

    def __init__(self, source: ContentSource):
        """
        初始化内容处理器

        Args:
            source: 内容源配置
        """
        self.source = source
        self.logger = get_logger()

    def process(self, article: Article) -> Article:
        """
        处理文章内容

        Args:
            article: 原始文章

        Returns:
            Article: 处理后的文章
        """
        # 1. 先清洗 HTML（把段落内的单行 <pre> 转成行内 <code>）。
        # 必须在任何 lxml/BeautifulSoup 解析之前完成：HTML 不允许 <p> 内嵌 <pre>，
        # 解析器会把 <p>text <pre>code</pre> more</p> 拆成 </p><pre>，再转回
        # <code> 就会留下 </p><code>。
        article.content = self._clean_html(article.content, base_url=article.url)

        # 0. 如果提取的图片列表中有首图（通常是封面图），且正文中没有包含该图片，
        # 则在正文最前方插入它，以便能够在电子书中下载并展示。
        if article.images:
            lead_image = article.images[0]
            soup = BeautifulSoup(article.content or '', 'lxml')
            has_lead_image = False
            for img in soup.find_all('img'):
                src = img.get('src') or img.get('data-src')
                if src and (src == lead_image or lead_image in src or src in lead_image):
                    has_lead_image = True
                    break
            
            if not has_lead_image:
                lead_img_tag = soup.new_tag('img', src=lead_image, alt="Lead Image")
                wrapper = soup.new_tag('p')
                wrapper.append(lead_img_tag)
                if not soup.body:
                    body = soup.new_tag('body')
                    if soup.html:
                        soup.html.append(body)
                    else:
                        soup.append(body)
                soup.body.insert(0, wrapper)
                article.content = soup.body.decode_contents()

        # 2. 应用 keep_link 规则
        if self.source.keep_link == "N":
            article.content = self._remove_links(article.content)

        # 3. 应用 exclude 规则
        if self.source.exclude:
            article.content = self._apply_exclude(article.content)

        # 4. 确保 HTML 格式正确
        article.content = self._ensure_valid_html(article.content)

        # 5. 包裹 Emoji
        article.content = self.wrap_emojis(article.content)

        return article

    @staticmethod
    def wrap_emojis(html: str) -> str:
        """
        使用正则表达式找出文本中的常见表情符号，并用 <span class="emoji"> 包裹。
        """
        # 匹配常见 Emoji 的 Unicode 范围（包含杂项符号、表情、交通、补充符号等）
        # 注意：对于超过 4 位的 Unicode 码点，必须使用 \U0001Fxxx 格式
        emoji_pattern = re.compile(
            r'('
            r'[\u2600-\u27BF]|'      # 杂项符号、装饰符号、丁坝符
            r'[\U0001F300-\U0001F5FF]|'    # 杂项符号和象形文字
            r'[\U0001F600-\U0001F64F]|'    # 表情 (Emoticons)
            r'[\U0001F680-\U0001F6FF]|'    # 交通和地图符号
            r'[\U0001F900-\U0001F9FF]|'    # 补充符号和象形文字
            r'[\U0001F1E6-\U0001F1FF]+'    # 国家/地区旗帜符号
            r')'
        )
        
        # 使用 BeautifulSoup 避免破坏标签结构
        soup = BeautifulSoup(html, 'lxml')
        
        # 只处理文本节点
        for text_node in soup.find_all(string=True):
            # 跳过已经在 span.emoji 中的节点
            if text_node.parent.name == 'span' and text_node.parent.get('class') == ['emoji']:
                continue
                
            if emoji_pattern.search(text_node):
                new_text = emoji_pattern.sub(r'<span class="emoji">\1</span>', str(text_node))
                # 重新解析含有 span 的字符串片段，并将所有内容替换回文本节点
                parsed_new = BeautifulSoup(new_text, 'lxml').body
                if parsed_new and parsed_new.contents:
                    text_node.replace_with(*parsed_new.contents)
                else:
                    text_node.replace_with(new_text)
                
        if soup.body:
            return soup.body.decode_contents()
        return str(soup)
    
    @staticmethod
    def get_unique_emojis(html: str) -> set:
        """提取 HTML 中所有独特的 Emoji 字符"""
        soup = BeautifulSoup(html, 'lxml')
        emojis = set()
        for span in soup.find_all('span', class_='emoji'):
            emojis.add(span.get_text())
        return emojis

    @staticmethod
    def replace_emojis_with_images(html: str) -> str:
        """将 HTML 中的 <span class="emoji"> 替换为 <img> 标签"""
        soup = BeautifulSoup(html, 'lxml')
        for span in soup.find_all('span', class_='emoji'):
            emoji_char = span.get_text()
            codepoint = "-".join(f"{ord(c):x}" for c in emoji_char)
            img_tag = soup.new_tag(
                'img',
                src=f"images/emoji_{codepoint}.png",
                alt=emoji_char,
                attrs={
                    'class': 'emoji',
                    'style': 'height: 1em; width: 1em; vertical-align: middle; display: inline-block; border: none;'
                }
            )
            span.replace_with(img_tag)
        
        if soup.body:
            return soup.body.decode_contents()
        return str(soup)

    @classmethod
    def render_text_with_emojis(cls, text: str) -> str:
        """Escape plain text and render any emoji in it as local image tags."""
        escaped_text = html_module.escape(text)
        return cls.replace_emojis_with_images(cls.wrap_emojis(escaped_text))

    @classmethod
    def get_emojis_from_text(cls, text: str) -> set:
        """Extract emoji from plain text using the same matching rules as rendering."""
        return cls.get_unique_emojis(cls.wrap_emojis(text))

    def _apply_exclude(self, html: str) -> str:
        """
        应用 exclude 规则，在 HTML 源码上操作，保留标签结构

        支持三种模式：
          start  — 删除从开头到关键词（含）之间的全部内容
          end    — 删除从关键词（含）到结尾的全部内容
          exact  — 在 HTML 源码中精确匹配并删除（可包含 HTML 标签/链接）

        Args:
            html: HTML 内容

        Returns:
            str: 处理后的 HTML
        """
        if not self.source.exclude:
            return html

        rules = self.source.exclude
        if not isinstance(rules, list):
            self.logger.error(f"exclude must be a list of rules, got {type(rules).__name__}")
            return html

        for rule in rules:
            if not isinstance(rule, dict):
                self.logger.warning(f"Skipping non-dict exclude rule: {rule}")
                continue

            rule_type = rule.get("type", "").strip()
            value = rule.get("value", "")

            if not value:
                self.logger.warning(f"Skipping exclude rule with empty value: {rule}")
                continue

            try:
                if rule_type == "start":
                    html = self._delete_from_start(html, value)
                elif rule_type == "end":
                    html = self._delete_from_end(html, value)
                elif rule_type == "exact":
                    html = self._delete_exact(html, value)
                else:
                    self.logger.warning(f"Unknown exclude rule type: '{rule_type}'")
            except Exception as e:
                self.logger.error(f"Failed to apply exclude rule {rule}: {e}")

        # 清理空标签
        html = self._cleanup_empty_tags(html)

        return html

    # ------------------------------------------------------------------
    # exclude 辅助方法
    # ------------------------------------------------------------------

    @staticmethod
    def _iter_text_nodes(html: str):
        """
        解析 HTML 并返回 (soup, 文本节点列表)

        文本节点按文档顺序排列，每个元素是 BeautifulSoup 的 NavigableString，
        对其 .string 赋值会直接反映到 DOM 树上。
        """
        from bs4 import NavigableString
        soup = BeautifulSoup(html, 'lxml')
        body = soup.body if soup.body else soup
        text_nodes = [n for n in body.find_all(string=True) if isinstance(n, NavigableString)]
        return soup, text_nodes

    def _delete_from_start(self, html: str, keyword: str) -> str:
        """删除从文档开头到 keyword（含 keyword 本身）之间的全部内容"""
        soup = BeautifulSoup(html, 'lxml')
        
        # 1. 寻找第一个包含 keyword 的文本节点
        target_node = None
        for node in soup.find_all(string=True):
            if keyword in node:
                target_node = node
                break
        
        if target_node:
            # 找到关键词所在位置
            text = str(target_node)
            idx = text.find(keyword)
            
            # 保留关键词之后的内容
            remaining_text = text[idx + len(keyword):]
            
            # 向上递归处理：删除当前节点及其所有父节点之前的兄弟节点
            curr = target_node
            while curr and curr.name != '[document]':
                # 获取当前节点的所有前序兄弟节点（包括元素、文本等）
                # 必须转换为列表，因为 extract() 会改变迭代器
                for prev in list(curr.previous_siblings):
                    prev.extract()
                curr = curr.parent
            
            # 更新目标文本节点的内容
            if remaining_text:
                target_node.replace_with(remaining_text)
            else:
                target_node.extract()
                
            return str(soup.body if soup.body else soup)

        # 2. 如果单节点没找到，尝试跨节点检查（仅做文本层面的检查，但不建议破坏结构）
        full_text = soup.get_text()
        if keyword in full_text:
            self.logger.warning(
                f"exclude 'start' keyword '{keyword}' spans multiple nodes. "
                "Structure preservation might be imperfect."
            )
            # 这里的策略：如果跨节点，我们至少不再退回到纯文本
            # 而是尝试定位到大致的元素位置，或者直接报错不处理以保护图片
            # 目前采用更安全的做法：如果不确定如何精确切割 DOM，则不执行删除，以保护图片
            # 除非是极简单的文档，否则跨节点切割 DOM 非常容易出错
            return html

        self.logger.debug(f"exclude 'start' keyword not found: '{keyword}'")
        return html

    def _delete_from_end(self, html: str, keyword: str) -> str:
        """删除从 keyword（含 keyword 本身）到文档结尾的全部内容"""
        soup = BeautifulSoup(html, 'lxml')
        
        # 1. 寻找最后一个包含 keyword 的文本节点（从后往前找）
        text_nodes = soup.find_all(string=True)
        target_node = None
        for node in reversed(text_nodes):
            if keyword in node:
                target_node = node
                break
        
        if target_node:
            # 找到关键词最后一次出现的位置
            text = str(target_node)
            idx = text.rfind(keyword)
            
            # 保留关键词之前的内容
            remaining_text = text[:idx]
            
            # 向上递归处理：删除当前节点及其所有父节点之后的兄弟节点
            curr = target_node
            while curr and curr.name != '[document]':
                # 获取当前节点的所有后续兄弟节点
                for nxt in list(curr.next_siblings):
                    nxt.extract()
                curr = curr.parent
            
            # 更新目标文本节点的内容
            if remaining_text:
                target_node.replace_with(remaining_text)
            else:
                target_node.extract()
                
            return str(soup.body if soup.body else soup)

        # 2. 跨节点检查
        full_text = soup.get_text()
        if keyword in full_text:
            self.logger.warning(
                f"exclude 'end' keyword '{keyword}' spans multiple nodes. "
                "Deletion skipped to preserve HTML structure and images."
            )
            return html

        self.logger.debug(f"exclude 'end' keyword not found: '{keyword}'")
        return html

    @staticmethod
    def _delete_exact(html: str, keyword: str) -> str:
        """在 HTML 源码中精确匹配 keyword 并删除所有出现（keyword 可含 HTML 标签）"""
        if keyword not in html:
            return html
        return html.replace(keyword, "")

    @staticmethod
    def _cleanup_empty_tags(html: str) -> str:
        """移除没有文本内容且无子标签的空标签，但保留 img, br, hr 等自闭合标签"""
        soup = BeautifulSoup(html, 'lxml')
        body = soup.body if soup.body else soup

        # 允许不包含内容或子标签的标签列表（自闭合标签或特殊标签）
        allowed_empty_tags = {'img', 'br', 'hr', 'td', 'th', 'iframe', 'video', 'audio'}

        # 逆序遍历，避免删除父标签后子标签引用失效
        for tag in reversed(body.find_all(True)):
            if tag.name in ('html', 'body', 'head') or tag.name in allowed_empty_tags:
                continue
            
            # 没有任何文本内容且没有子标签 → 视为真正可以删除的空标签
            if not tag.get_text(strip=True) and not tag.find_all(True):
                tag.extract()

        return str(soup.body if soup.body else soup)

    def _remove_links(self, html: str) -> str:
        """
        移除所有超链接，保留内部标签（如图片）

        Args:
            html: HTML 内容

        Returns:
            str: 处理后的 HTML
        """
        soup = BeautifulSoup(html, 'lxml')

        # 使用 unwrap() 移除 <a> 标签本身，但保留其子节点
        for link in soup.find_all('a'):
            link.unwrap()

        return str(soup)

    # 邮件/网页中社交分享图标常见标记（alt 或 src）
    _SOCIAL_IMAGE_HINTS = (
        'share on', 'facebook', 'twitter', 'linkedin', 'instagram',
        'threads', 'whatsapp', 'telegram', 'weibo', 'wechat',
        'pinterest', 'reddit', 'tiktok', 'youtube',
        'static_assets/header/', '/x.png', 'x_light', 'social',
    )

    def _declared_image_size_px(self, img_tag) -> Optional[int]:
        """
        从 width/height 属性或 style 中解析声明的最小渲染尺寸（px）。
        无法判断时返回 None。
        """
        sizes = []
        for attr in ('width', 'height'):
            val = img_tag.get(attr)
            if val is None:
                continue
            raw = str(val).strip().lower().replace('px', '')
            if raw.isdigit():
                sizes.append(int(raw))

        style = (img_tag.get('style') or '').lower()
        for match in re.findall(r'(?:max-)?(?:width|height)\s*:\s*(\d+(?:\.\d+)?)px', style):
            try:
                sizes.append(int(float(match)))
            except ValueError:
                continue

        return min(sizes) if sizes else None

    def _is_small_rendered_image(self, img_tag) -> bool:
        """
        判断是否为应剔除的装饰性小图（社交分享图标、跟踪像素等）。

        说明：
        邮件模版常写成 <a><table>...<img width=18></table></a>。
        lxml 会把 table 从 a 中拆出，导致 img 不再有 a 祖先，仅靠
        「在 a 内」的旧逻辑会漏掉 beehiiv 等 newsletter 的 Facebook/X 图标。
        因此同时依据：声明尺寸、父级 a、alt/src 社交关键词。
        """
        size = self._declared_image_size_px(img_tag)
        alt = (img_tag.get('alt') or '').lower()
        src = (img_tag.get('src') or '').lower()
        combined = f'{alt} {src}'

        # 跟踪像素 / 1×1 打开回执
        if size is not None and size <= 2:
            return True

        is_small = size is not None and size <= 32
        if not is_small:
            return False

        # 经典路径：链接着的小图标
        if img_tag.find_parent('a'):
            return True

        # lxml 拆掉 a>table 后，靠 alt/src 识别社交图标
        if any(hint in combined for hint in self._SOCIAL_IMAGE_HINTS):
            return True

        return False

    def _clean_html(self, html: str, base_url: Optional[str] = None) -> str:
        """
        清洗 HTML
        移除不需要的标签和属性，修复 EPUB 验证错误

        Args:
            html: HTML 内容
            base_url: 基础 URL，用于将相对链接解析为绝对链接

        Returns:
            str: 清洗后的 HTML 片段
        """
        # === 全局预处理：将单行 <pre> 转换为行内 <code> ===
        # 问题根源：trafilatura 在提取 HTML 时，会把原始文章中的行内 <code> 标签
        # 转换为 <pre> 标签（例如 sspai 等平台）。这些被错误转换的 <pre> 内容在包含
        # 首尾换行符或空白时（如 <pre><code>\ncmd\n</code></pre>），过去会被误判为
        # 多行代码块，从而拆分段落 <p>，在 Kindle 上显示为强制换行。
        # 解决方案：剥离首尾换行符后再检测内部是否包含换行。若内容为单行文本，
        # 将其转换/unwrap 为行内 <code> 标签。真正的多行代码块（包含内部 \n）保留为 <pre>。
        def _is_single_line_pre_content(inner: str) -> bool:
            code_match = re.match(r'^\s*<code\b[^>]*>(.*?)</code>\s*$', inner, re.DOTALL | re.IGNORECASE)
            if code_match:
                text = code_match.group(1).strip('\r\n')
            else:
                text = inner.strip('\r\n ')
            return not ('\n' in text or '\r' in text or '<br' in text.lower())

        def _convert_singleline_pre_to_code(m: re.Match) -> str:
            inner = m.group(1)
            if not _is_single_line_pre_content(inner):
                return m.group(0)
            
            code_match = re.match(r'^\s*<code\b([^>]*)>(.*?)</code>\s*$', inner, re.DOTALL | re.IGNORECASE)
            if code_match:
                attrs = code_match.group(1)
                code_text = code_match.group(2).strip('\r\n')
                return f'<code{attrs}>{code_text}</code>'
            return f'<code>{inner.strip()}</code>'

        html = re.sub(
            r'<pre\b[^>]*>(.*?)</pre>',
            _convert_singleline_pre_to_code,
            html,
            flags=re.DOTALL | re.IGNORECASE
        )

        # === 预处理：转换不合法嵌套在段落/行内元素中的 <pre> 标签 ===
        # 标准 HTML 解释器（如 lxml）会在遇到嵌套在 <p> 内的 <pre> 时，自动闭合先前未闭合的 <p> 标签。
        # 从而将 <p>xxx<pre>code</pre>yyy</p> 树结构破坏为：<p>xxx</p><pre>code</pre>yyy
        # 导致后面的 text 逃逸出 <p> 标签并发生行内代码强制换行。
        # 我们在进入 BeautifulSoup 解析之前，用正则在字符串级别解决该问题。
        # 1. 首先处理嵌套在 h1-h6, span, a 等行内/标题元素中的 <pre> 标签。
        # 这些标签通常不应该包含块级 <pre>，我们将其转换为行内 <code>。
        inline_containers = ['h1', 'h2', 'h3', 'h4', 'h5', 'h6', 'span', 'a']
        for container in inline_containers:
            pattern = re.compile(rf'(<{container}\b[^>]*>)(.*?)(</{container}>)', re.DOTALL | re.IGNORECASE)
            
            def replace_pre_inside_inline(match):
                start_tag, content, end_tag = match.group(1), match.group(2), match.group(3)
                if '<pre' in content.lower():
                    # 1. <pre...><code...>...</code></pre> -> <code...>...</code> (unwrap pre, preserve code attributes)
                    content = re.sub(
                        r'<pre\b[^>]*>\s*(<code\b[^>]*>.*?</code>)\s*</pre>',
                        r'\1',
                        content,
                        flags=re.DOTALL | re.IGNORECASE
                    )
                    # 2. <pre...>...</pre> -> <code>...</code>
                    content = re.sub(
                        r'<pre\b[^>]*>(.*?)</pre>',
                        r'<code>\1</code>',
                        content,
                        flags=re.DOTALL | re.IGNORECASE
                    )
                return f"{start_tag}{content}{end_tag}"
            
            html = pattern.sub(replace_pre_inside_inline, html)

        # 2. 特殊处理嵌套在 <p> 中的 <pre> 标签。
        p_pattern = re.compile(r'(<p\b[^>]*>)(.*?)(</p>)', re.DOTALL | re.IGNORECASE)
        
        def replace_pre_inside_p(match):
            start_p, p_content, end_p = match.group(1), match.group(2), match.group(3)
            if '<pre' not in p_content.lower():
                return match.group(0)
            
            # 检查 <p> 内是否仅包含 <pre> 块（忽略空白字符）
            stripped = re.sub(r'<pre\b[^>]*>.*?</pre>', '', p_content, flags=re.DOTALL | re.IGNORECASE).strip()
            if not stripped:
                # 仅包含 <pre> 标签，直接剥离外部 <p> 标签，使其变为块级元素
                return p_content
            
            # 匹配所有 <pre>...</pre> 子块
            pre_blocks = list(re.finditer(r'<pre\b[^>]*>(.*?)</pre>', p_content, re.DOTALL | re.IGNORECASE))
            
            # 判断是否所有嵌套的 <pre> 块都是单行的（即没有内部换行符或 <br>）
            all_single_line = True
            for pb in pre_blocks:
                inner = pb.group(1)
                if not _is_single_line_pre_content(inner):
                    all_single_line = False
                    break
            
            if all_single_line:
                # 都是单行行内代码，转换 <pre> 为 <code> 并保留在 <p> 内部
                content = re.sub(
                    r'<pre\b[^>]*>\s*(<code\b[^>]*>.*?</code>)\s*</pre>',
                    r'\1',
                    p_content,
                    flags=re.DOTALL | re.IGNORECASE
                )
                content = re.sub(
                    r'<pre\b[^>]*>(.*?)</pre>',
                    r'<code>\1</code>',
                    content,
                    flags=re.DOTALL | re.IGNORECASE
                )
                return f"{start_p}{content}{end_p}"
            
            # 存在多行块级代码，必须将 <p> 进行拆分：<p>前</p><pre>代码</pre><p>后</p>
            pre_pattern = re.compile(r'(<pre\b[^>]*>.*?</pre>)', re.DOTALL | re.IGNORECASE)
            parts = pre_pattern.split(p_content)
            res = []
            for part in parts:
                if not part:
                    continue
                if re.match(r'^<pre\b', part, re.IGNORECASE):
                    res.append(part)
                else:
                    if part.strip():
                        res.append(f"{start_p}{part}{end_p}")
            return "".join(res)

        html = p_pattern.sub(replace_pre_inside_p, html)

        # 清除行内 code 标签紧邻的前后换行符，防止在 Kindle 等阅读器中强制换行
        html = re.sub(r'[\r\n]+\s*(<code\b)', r'\1', html)
        html = re.sub(r'(</code>)\s*[\r\n]+', r'\1', html)

        soup = BeautifulSoup(html, 'lxml')

        # === 处理 a 标签的 href 属性，防止 EPUB 验证由于非法或相对链接失败 ===
        from urllib.parse import urlparse, urljoin
        for a_tag in list(soup.find_all('a')):
            href = a_tag.get('href')
            if href is None:
                continue
            
            href_str = href.strip()
            if not href_str:
                a_tag.unwrap()
                continue
                
            # 保留本页面内的锚点链接
            if href_str.startswith('#'):
                continue
                
            try:
                parsed = urlparse(href_str)
            except Exception as e:
                self.logger.warning(f"Failed to parse URL '{href_str}': {e}")
                a_tag.unwrap()
                continue
                
            # 校验 scheme，如果是相对 URL (即无 scheme) 或者非法 scheme
            if not parsed.scheme or parsed.scheme.lower() not in ('http', 'https', 'mailto', 'tel'):
                if base_url:
                    try:
                        resolved_url = urljoin(base_url, href_str)
                        parsed_resolved = urlparse(resolved_url)
                        if parsed_resolved.scheme.lower() in ('http', 'https'):
                            href_str = resolved_url
                        else:
                            a_tag.unwrap()
                            continue
                    except Exception as e:
                        self.logger.warning(f"Failed to resolve relative URL '{href_str}' with base '{base_url}': {e}")
                        a_tag.unwrap()
                        continue
                else:
                    a_tag.unwrap()
                    continue
                    
            # 替换空格为 %20 (比如 'elon musk' 转换)
            if ' ' in href_str:
                href_str = href_str.replace(' ', '%20')
                
            a_tag['href'] = href_str

        # === 布局清洗：将复杂的、嵌套的邮件/网页模版表格拆解为普通文本流 ===
        self._unwrap_layout_tables(soup)

        # === 预过滤：移除社交分享小图标与跟踪像素 ===
        for img in list(soup.find_all('img')):
            if self._is_small_rendered_image(img):
                parent_a = img.find_parent('a')
                if parent_a:
                    # 若链接内只剩该图标（无其它图、无文字），整段分享链接一起删
                    other_imgs = [c for c in parent_a.find_all('img') if c is not img]
                    other_text = parent_a.get_text(strip=True)
                    if not other_imgs and not other_text:
                        parent_a.decompose()
                    else:
                        img.decompose()
                else:
                    img.decompose()

        # === EPUB 验证修复规则 ===

        # 1. 转换废弃/非法标签
        # <row> → <tr>（表格行）
        for row in soup.find_all('row'):
            row.name = 'tr'

        # <cell> → <td>（表格单元格）
        for cell in soup.find_all('cell'):
            cell.name = 'td'

        # <font> → <span>，保留样式属性
        for font in soup.find_all('font'):
            font.name = 'span'
            # 将 face/size 转换为 style
            style_parts = []
            # 忽略 color 属性以避免在 Kindle 上显示为灰色
            if font.get('color'):
                del font['color']
                
            if font.get('face'):
                style_parts.append(f"font-family:{font['face']}")
                del font['face']
            if font.get('size'):
                # HTML font size 1-7 转换为 px
                sizes = {'1': '8', '2': '10', '3': '12', '4': '14', '5': '18', '6': '24', '7': '36'}
                px = sizes.get(font['size'], '12')
                style_parts.append(f"font-size:{px}px")
                del font['size']
            if style_parts:
                font['style'] = ';'.join(style_parts)

        # 清洗所有标签的 style 属性，移除颜色设置以及对非 img 标签的布局约束
        layout_properties_to_remove = {
            'width', 'height', 'min-width', 'max-width', 'min-height', 'max-height',
            'margin', 'margin-top', 'margin-bottom', 'margin-left', 'margin-right',
            'padding', 'padding-top', 'padding-bottom', 'padding-left', 'padding-right',
            'position', 'top', 'bottom', 'left', 'right', 'float', 'clear',
            'display', 'flex', 'grid', 'border', 'background', 'background-image'
        }

        for tag in soup.find_all(True):
            if 'style' in tag.attrs:
                style_str = tag['style']
                # 移除 color 和 background-color 属性
                new_style = re.sub(r'(?i)\b(background-)?color\s*:[^;]+(;|$)', '', style_str)
                
                # 如果不是 img 标签，进一步移除布局和尺寸相关限制属性
                if tag.name != 'img':
                    parts = new_style.split(';')
                    filtered_parts = []
                    for part in parts:
                        part_strip = part.strip()
                        if not part_strip or ':' not in part_strip:
                            continue
                        prop, val = part_strip.split(':', 1)
                        prop_name = prop.strip().lower()
                        if prop_name in layout_properties_to_remove or 'background' in prop_name:
                            continue
                        filtered_parts.append(f"{prop_name}:{val.strip()}")
                    new_style = ';'.join(filtered_parts)

                # 移除多余的空格和分号
                new_style = new_style.strip().strip(';')
                if new_style:
                    tag['style'] = new_style
                else:
                    del tag['style']

        # 2. 修复图片属性：width/height 必须是整数，且清理 alt/title 属性以防 Kindle Previewer 报错
        for img in soup.find_all('img'):
            # 清理 alt 和 title 中的 <, >, &lt;, &gt;，防止 Kindle Previewer 转换失败 (E21018)
            for attr in ('alt', 'title'):
                if attr in img.attrs:
                    val = img.get(attr, '')
                    if isinstance(val, str):
                        val_cleaned = val.replace('&gt;', ' - ').replace('&lt;', ' - ').replace('>', ' - ').replace('<', ' - ')
                        img[attr] = val_cleaned
            # 处理 width 属性
            if 'width' in img.attrs:
                width_value = img.get('width', '')
                if isinstance(width_value, str):
                    width_str = width_value.strip()
                    if width_str:  # 非空字符串
                        try:
                            width = int(float(width_str))
                            img['width'] = str(width)
                        except (ValueError, TypeError):
                            del img['width']
                    else:  # 空字符串，删除属性
                        del img['width']

            # 处理 height 属性
            if 'height' in img.attrs:
                height_value = img.get('height', '')
                if isinstance(height_value, str):
                    height_str = height_value.strip()
                    if height_str:  # 非空字符串
                        try:
                            height = int(float(height_str))
                            img['height'] = str(height)
                        except (ValueError, TypeError):
                            del img['height']
                    else:  # 空字符串，删除属性
                        del img['height']

        # 3. 移除 SVG 和远程资源标签
        # SVG 缺少命名空间会导致 EPUB 验证失败
        # 视频/音频是远程资源，Kindle 不支持
        for tag in soup(['svg', 'video', 'source', 'audio', 'track']):
            tag.decompose()

        # 3.5. 转换不合法的嵌套 <pre> 标签为行内 <code> 标签
        # 当 <pre> 标签被嵌套在 <p>、<h1>-<h6>、<span>、<a> 等行内/段落元素中时，
        # 在 HTML/EPUB 规范中是不合法的块级嵌套。我们应将其转换为 <code> 标签。
        # 如果 <pre> 内已包含 <code>，则可以直接 unwrap 掉 <pre>，仅保留 <code>。
        inline_containers = ['p', 'h1', 'h2', 'h3', 'h4', 'h5', 'h6', 'span', 'a']
        for container_name in inline_containers:
            for container in soup.find_all(container_name):
                for pre in list(container.find_all('pre')):
                    code_child = pre.find('code')
                    if code_child:
                        pre.unwrap()
                    else:
                        pre.name = 'code'

        # 4. 修复嵌套结构：块级元素不能在 <p> 内
        self._fix_nested_blocks(soup)

        # 4.5. 把被解析器拆出段落的行内 <code> 等重新合并回前一个 <p>/<h*>
        self._rejoin_split_phrasing(soup)

        # 4.6. 解耦段落中的混排插图，防止插图前文本因 text-align: justify 产生非正常两端对齐拉伸
        self._separate_mixed_images_from_p(soup)

        # === 原有安全规则 ===

        # 移除 script 和 style 标签
        for tag in soup(['script', 'style', 'iframe', 'form', 'input', 'button', 'noscript']):
            tag.decompose()

        # 移除不安全的属性
        # 保留基本属性和图片处理所需的属性，以及表格/样式属性
        allowed_attrs = [
            'href', 'src', 'alt', 'title', 'class', 'style',
            'srcset', 'data-srcset', 'data-src', 'data-original',
            'data-actualsrc', 'data-lazy-src', 'file', 'zoom-target', 'original',
            'width', 'height', 'colspan', 'rowspan', 'id'
        ]

        for tag in soup.find_all(True):
            attrs = dict(tag.attrs)
            for attr in attrs:
                if attr not in allowed_attrs:
                    del tag[attr]
                # 限制 width/height 属性只能在 img 标签上保留，防止复杂的表格固定宽度导致挤压
                elif attr in ('width', 'height') and tag.name != 'img':
                    del tag[attr]

        # === 对话者/采访人姓名加粗增强 ===
        # 扫描段落 <p> 中以 "Speaker Name:" 开头但未被 <strong>/<b> 包裹的对话者标识并进行加粗
        speaker_pattern = re.compile(r'^([A-Z\u4e00-\u9fa5][A-Za-z0-9\u4e00-\u9fa5\s\.\-–—]{0,30}[:：])(.*|$)')
        skip_prefixes = {"http:", "https:", "ftp:", "file:", "note:", "url:"}
        from bs4 import NavigableString, Tag
        for p in soup.find_all('p'):
            if not p.contents:
                continue
            first_child = p.contents[0]
            if isinstance(first_child, NavigableString) and not isinstance(first_child, Tag):
                text_str = str(first_child)
                m = speaker_pattern.match(text_str)
                if m:
                    speaker_part = m.group(1)
                    if speaker_part.lower() not in skip_prefixes:
                        rest_part = text_str[len(speaker_part):]
                        strong_tag = soup.new_tag('strong')
                        strong_tag.string = speaker_part
                        first_child.replace_with(strong_tag)
                        if rest_part:
                            strong_tag.insert_after(rest_part)

        # 仅返回 body 内部的内容，避免产生嵌套 of html/body 标签
        if soup.body:
            return soup.body.decode_contents()
        return str(soup)

    def _unwrap_layout_tables(self, soup: BeautifulSoup) -> None:
        """
        拆解用于定位、边距和邮件模版布局的表格标签。
        若表格带有 role="presentation" 或 role="none"，或每行最多只有一个单元格（单列包装），
        或包含嵌套的表格，则将其子项（tr/td/tbody等）以及 table 标签自身全部拆开，使其流式排版，
        能自适应 Kindle 等电子书阅读器的屏幕尺寸。
        """
        # 采用自下而上的逆序遍历，确保嵌套表格能从小到大依次正确拆解
        for table in reversed(soup.find_all('table')):
            is_layout = False
            
            # 1. 显式指定的布局角色
            role = table.get('role')
            if role in ('presentation', 'none'):
                is_layout = True
            else:
                # 2. 判断是否是单列包裹表格或多层嵌套包裹表格
                max_cols = 0
                for tr in table.find_all('tr', recursive=False):
                    cells = tr.find_all(['td', 'th'], recursive=False)
                    max_cols = max(max_cols, len(cells))
                
                has_nested_table = bool(table.find('table'))
                
                if max_cols <= 1 or has_nested_table:
                    is_layout = True

            if is_layout:
                # 找到该 table 内的所有布局辅助标签（按深度倒序，防止父子标签拆解时影响树结构）
                tags_to_unwrap = table.find_all(['tbody', 'thead', 'tfoot', 'tr', 'td', 'th'])
                for tag in reversed(tags_to_unwrap):
                    tag.unwrap()
                table.unwrap()

    def _fix_nested_blocks(self, soup: BeautifulSoup) -> None:
        """
        修复 HTML 嵌套结构问题
        将 <p> 内的块级元素移出，确保 EPUB 验证通过

        EPUB 3.3 不允许 <p> 内包含块级元素（section, div, p 等）

        Args:
            soup: BeautifulSoup 解析对象
        """
        block_elements = {
            'section', 'div', 'article', 'aside', 'header', 'footer',
            'nav', 'main', 'figure', 'blockquote', 'pre', 'ul', 'ol',
            'li', 'table', 'form', 'fieldset', 'h1', 'h2', 'h3',
            'h4', 'h5', 'h6', 'p', 'address', 'hr', 'dl', 'dt', 'dd'
        }

        # 多次遍历确保深度嵌套也被修复
        # 增加迭代次数到 5 次，确保多层嵌套都被处理
        for _ in range(5):
            fixed_count = 0
            for p_tag in soup.find_all('p'):
                children_to_move = []
                for child in p_tag.children:
                    if hasattr(child, 'name') and child.name in block_elements:
                        children_to_move.append(child)

                for child in children_to_move:
                    child.extract()
                    p_tag.insert_after(child)
                    fixed_count += 1

            # 如果没有修复任何问题，提前退出
            if fixed_count == 0:
                break

    def _rejoin_split_phrasing(self, soup: BeautifulSoup) -> None:
        """
        将因 <p> 内嵌 <pre> 而被 HTML 解析器拆出的行内内容合并回前一段落。

        输入常见形态（trafilatura 把 <code> 写成 <pre>，再被 lxml 拆段）：
          <p>是用 </p><code>codesign</code> 给微信重新签名
        处理后：
          <p>是用 <code>codesign</code> 给微信重新签名</p>
        """
        from bs4 import NavigableString, Tag

        inline_tags = {
            'a', 'abbr', 'b', 'cite', 'code', 'del', 'em', 'i',
            'kbd', 'mark', 'q', 's', 'samp', 'small', 'span', 'strong', 'sub',
            'sup', 'u', 'var', 'time',
        }

        for tag in soup.find_all(['p', 'h1', 'h2', 'h3', 'h4', 'h5', 'h6']):
            while True:
                nxt = tag.next_sibling
                if nxt is None:
                    break
                if isinstance(nxt, NavigableString):
                    if str(nxt).strip():
                        # 被拆出段落的正文必须合并回去
                        tag.append(nxt)
                        continue
                    # nxt 是纯空白：向后跳过连续空白，找到首个非空白兄弟
                    # 只有当后续是行内内容（行内标签或非空白文本）时才吸收该空白，
                    # 避免把段落后的尾巴空格吞进 <p>
                    probe = nxt.next_sibling
                    while probe is not None and isinstance(probe, NavigableString) and not str(probe).strip():
                        probe = probe.next_sibling
                    if probe is None:
                        break
                    if isinstance(probe, Tag) and probe.name in inline_tags:
                        tag.append(nxt)
                        continue
                    if isinstance(probe, NavigableString) and str(probe).strip():
                        tag.append(nxt)
                        continue
                    break
                if isinstance(nxt, Tag) and nxt.name in inline_tags:
                    tag.append(nxt)
                    continue
                break

        # 块级元素之后仍漂在 body 下的行内节点（如 <pre> 后的 " After"）包进 <p>
        body = soup.body if soup.body else soup
        run = []

        def flush_run():
            if not run:
                return
            if all(isinstance(n, NavigableString) and not str(n).strip() for n in run):
                run.clear()
                return
            wrapper = soup.new_tag('p')
            run[0].insert_before(wrapper)
            for node in run:
                wrapper.append(node)
            run.clear()

        for child in list(body.children):
            is_inline = isinstance(child, NavigableString) or (
                isinstance(child, Tag) and child.name in inline_tags
            )
            if is_inline:
                run.append(child)
            else:
                flush_run()
        flush_run()

    def _separate_mixed_images_from_p(self, soup: BeautifulSoup) -> None:
        """
        将与文本混排在同一个 <p> 中的非 Emoji 插图拆解为独立段落。

        当正文插图与文本混在同一个 <p> 标签内（例如 <p>段落文本<img/></p>）时，
        在 EPUB 阅读器中因应用 text-align: justify 样式，图片上一行的文本会被误判为
        段落中间行而强制拉伸两端对齐产生巨大字符间距。
        将非 Emoji 图片从混排段落中拆分出来，使其作为独立段落排版。
        """
        from bs4 import NavigableString, Tag

        for p in list(soup.find_all('p')):
            imgs = [img for img in p.find_all('img') if not (img.get('class') and 'emoji' in img.get('class'))]
            if not imgs:
                continue

            # 检查 <p> 中除该插图外是否还有实质性的其它内容（文本或其他标签）
            has_other_content = False
            for child in p.contents:
                if isinstance(child, NavigableString):
                    if str(child).strip():
                        has_other_content = True
                        break
                elif isinstance(child, Tag):
                    if child.name != 'img' or (child.get('class') and 'emoji' in child.get('class')):
                        has_other_content = True
                        break

            if not has_other_content:
                # 仅包含该图片本身（或纯空白），本身就是独立的图片包装段落，保持不变
                continue

            # 将 <p> 内容按插图切分成多个节点序列
            new_nodes = []
            current_run = []

            def flush_run():
                if not current_run:
                    return
                # 检查 current_run 是否包含实质内容（非纯空白且非仅有 <br>）
                has_text = any(
                    (isinstance(n, NavigableString) and str(n).strip()) or
                    (isinstance(n, Tag) and n.name != 'br')
                    for n in current_run
                )
                if has_text:
                    new_p = soup.new_tag('p')
                    for n in current_run:
                        new_p.append(n)
                    new_nodes.append(new_p)
                current_run.clear()

            for child in list(p.contents):
                if isinstance(child, Tag) and child.name == 'img' and not (child.get('class') and 'emoji' in child.get('class')):
                    flush_run()
                    img_p = soup.new_tag('p')
                    img_p.append(child)
                    new_nodes.append(img_p)
                else:
                    current_run.append(child)
            flush_run()

            if new_nodes:
                first = new_nodes[0]
                p.replace_with(first)
                prev = first
                for node in new_nodes[1:]:
                    prev.insert_after(node)
                    prev = node

    def _ensure_valid_html(self, html: str) -> str:
        """
        确保 HTML 格式正确
        主要用于修复未闭合标签

        Args:
            html: HTML 内容

        Returns:
            str: 有效的 HTML 片段
        """
        # 使用 BeautifulSoup 的修复能力
        soup = BeautifulSoup(html, 'lxml')
        
        if soup.body:
            return soup.body.decode_contents()
        return str(soup)
