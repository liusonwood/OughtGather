"""
辅助函数模块
提供通用的工具函数
"""

import re
import hashlib
from datetime import datetime
from zoneinfo import ZoneInfo
from typing import Optional
from urllib.parse import urlparse


# 默认时区：北京时间 UTC+8
DEFAULT_TZ = ZoneInfo("Asia/Shanghai")


def get_now(tz: Optional[ZoneInfo] = None) -> datetime:
    """
    获取当前时间（带时区）

    Args:
        tz: 可选时区，默认为 Asia/Shanghai (UTC+8)

    Returns:
        datetime: 带时区的当前时间
    """
    if tz is None:
        tz = DEFAULT_TZ
    return datetime.now(tz)


def normalize_url(url: str) -> str:
    """
    标准化 URL
    保留 Query 参数，仅剥离末尾斜杠和 fragment (#anchor)
    """
    if not url:
        return ""

    parsed = urlparse(url)
    path = parsed.path.rstrip('/')
    query = f"?{parsed.query}" if parsed.query else ""
    return f"{parsed.scheme}://{parsed.netloc}{path}{query}"


def generate_content_id(url: str, title: Optional[str] = None, published_date: Optional[str] = None) -> str:
    """
    生成内容唯一标识符 (MD5 哈希)
    仅基于标准化后的 URL
    """
    content = normalize_url(url)
    return hashlib.md5(content.encode('utf-8')).hexdigest()


def extract_text_from_html(html: str) -> str:
    """
    从 HTML 中提取纯文本
    简单的实现，去除 HTML 标签
    """
    if not html:
        return ""

    # 移除 script 和 style 标签及其内容
    text = re.sub(r'<(script|style)[^>]*>.*?</\1>', '', html, flags=re.DOTALL | re.IGNORECASE)

    # 移除 HTML 标签
    text = re.sub(r'<[^>]+>', '', text)

    # 解码 HTML 实体
    text = text.replace('&nbsp;', ' ')
    text = text.replace('&amp;', '&')
    text = text.replace('&lt;', '<')
    text = text.replace('&gt;', '>')
    text = text.replace('&quot;', '"')
    text = text.replace('&#39;', "'")

    # 移除多余的空白
    text = re.sub(r'\s+', ' ', text)

    return text.strip()


def truncate_text(text: str, max_length: int = 200) -> str:
    """
    截断文本
    """
    if not text or len(text) <= max_length:
        return text

    return text[:max_length] + "..."


def is_valid_url(url: str) -> bool:
    """
    验证 URL 是否有效
    """
    if not url:
        return False

    try:
        result = urlparse(url)
        return all([result.scheme, result.netloc])
    except Exception:
        return False


def sanitize_filename(filename: str) -> str:
    """
    清理文件名
    移除非法字符
    """
    # 移除文件系统不允许的字符
    illegal_chars = r'[<>:"/\\|?*]'
    sanitized = re.sub(illegal_chars, '_', filename)

    # 先去除首尾空白，再将内部空格替换为下划线
    sanitized = sanitized.strip()
    sanitized = re.sub(r'\s+', '_', sanitized)

    # 限制长度
    if len(sanitized) > 200:
        sanitized = sanitized[:200]

    return sanitized


def format_date(date_str: str) -> str:
    """
    统一日期格式化

    支持的输入格式：
    - RFC 822 (如: "Mon, 14 Jun 2026 10:30:00 GMT")
    - ISO 8601 (如: "2026-06-14T10:30:00")
    - Unix 时间戳（秒或毫秒，如: "1718343000" 或 "1718343000000"）
    - 任意字符串（原样返回）

    输出格式：YYYY-MM-DD HH:MM
    输出时区：DEFAULT_TZ (Asia/Shanghai)

    Args:
        date_str: 日期字符串或数字时间戳

    Returns:
        str: 格式化后的日期
    """
    if not date_str and date_str != 0:
        return ""

    from datetime import datetime

    def _format_dt(dt: datetime) -> str:
        """将 datetime 转换为目标时区并格式化"""
        if dt.tzinfo is None:
            # 不带时区的视为 UTC+0
            dt = dt.replace(tzinfo=ZoneInfo("UTC"))
        dt = dt.astimezone(DEFAULT_TZ)
        return dt.strftime("%Y-%m-%d %H:%M")

    # 处理数字类型（int/float）时间戳
    if isinstance(date_str, (int, float)):
        try:
            timestamp = date_str
            # 判断是秒还是毫秒（毫秒 > 1e12）
            if timestamp > 1_000_000_000_000:
                timestamp = timestamp / 1000  # 毫秒转秒
            dt = datetime.fromtimestamp(timestamp, tz=DEFAULT_TZ)
            return dt.strftime("%Y-%m-%d %H:%M")
        except (ValueError, OSError, OverflowError):
            pass  # 继续尝试其他格式

    # 处理字符串类型
    if isinstance(date_str, str):
        # 首先检查是否是纯数字（时间戳）
        if date_str.isdigit():
            try:
                timestamp = int(date_str)
                # 判断是秒还是毫秒（毫秒 > 1e12）
                if timestamp > 1_000_000_000_000:
                    timestamp = timestamp / 1000  # 毫秒转秒
                dt = datetime.fromtimestamp(timestamp, tz=DEFAULT_TZ)
                return dt.strftime("%Y-%m-%d %H:%M")
            except (ValueError, OSError, OverflowError):
                pass  # 继续尝试其他格式

    # 尝试常见的日期格式
    formats = [
        "%a, %d %b %Y %H:%M:%S %Z",  # RFC 822: "Mon, 14 Jun 2026 10:30:00 GMT"
        "%a, %d %b %Y %H:%M:%S %z",  # RFC 822 with timezone offset
        "%Y-%m-%dT%H:%M:%S",  # ISO 8601: "2026-06-14T10:30:00"
        "%Y-%m-%dT%H:%M:%S.%f",  # ISO 8601 with microseconds
        "%Y-%m-%dT%H:%M:%S%z",  # ISO 8601 with timezone
        "%Y-%m-%d %H:%M:%S",  # Standard format
        "%Y/%m/%d %H:%M:%S",  # Alternative separator
        "%Y-%m-%d",  # Date only
    ]

    for fmt in formats:
        try:
            dt = datetime.strptime(date_str, fmt)
            return _format_dt(dt)
        except (ValueError, TypeError):
            continue

    # 如果都解析失败，尝试使用 dateutil（如果有安装）
    try:
        from dateutil import parser, tz

        # 提供常见时区缩写映射，避免 UnknownTimezoneWarning
        # （未来版本 dateutil 会将此 warning 升级为 exception）
        _TZINFOS = {
            # 北美时区
            "EST": tz.gettz("America/New_York"),
            "EDT": tz.gettz("America/New_York"),
            "CST": tz.gettz("America/Chicago"),
            "CDT": tz.gettz("America/Chicago"),
            "MST": tz.gettz("America/Denver"),
            "MDT": tz.gettz("America/Denver"),
            "PST": tz.gettz("America/Los_Angeles"),
            "PDT": tz.gettz("America/Los_Angeles"),
            # 通用 UTC
            "UT": tz.UTC,
        }

        dt = parser.parse(date_str, tzinfos=_TZINFOS)
        return _format_dt(dt)
    except (ImportError, ValueError, TypeError, OverflowError):
        # 最后手段：返回原始字符串
        return date_str


import threading

# 全局 HTML 解析锁，确保 lxml, BeautifulSoup, trafilatura 在多线程环境下的安全性，防止 C 级 double free or corruption 崩溃
HTML_PARSING_LOCK = threading.Lock()

