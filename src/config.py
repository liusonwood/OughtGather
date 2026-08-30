"""
配置管理模块
负责加载、验证和提供配置访问接口
"""

import json
import os
import re
from typing import Any, Dict, List, Optional
from dataclasses import dataclass

from src.utils.helpers import get_now


@dataclass
class TitleConfig:
    """标题配置"""
    text: str
    img: Optional[str] = None

    def get_display_text(self) -> str:
        """获取显示文本，处理时间占位符"""
        now = get_now()
        result = self.text
        date_str = now.strftime("%Y-%m-%d")

        # 先处理 {xxx {time}} 格式（必须在简单替换之前，否则 {time} 会被提前替换掉）
        pattern = r'\{([^{}]+)\{time\}\}'
        result = re.sub(
            pattern,
            lambda match: f"{match.group(1).strip()} {date_str}",
            result,
        )

        # 再替换剩余的独立 {time}
        if "{time}" in result:
            result = result.replace("{time}", date_str)

        return result

    def get_plain_text(self) -> str:
        """获取纯文本标题，去除所有 HTML 标签（如 </br>、<a> 等）"""
        text = self.get_display_text()
        # 移除所有 HTML 标签
        text = re.sub(r'<[^>]+>', '', text)
        return text.strip()


@dataclass
class ContentSource:
    """内容源配置"""
    type: str  # mail / rss / web / trending
    src: str
    priority: int = 0
    title: Optional[str] = None
    keep_link: str = "Y"
    exclude: Optional[List[Dict[str, str]]] = None
    delete: Optional[str] = None
    load_images: str = "Y"  # 是否加载图片 (Y/N)
    metadata: Optional[Dict[str, Any]] = None  # Fetcher 专属配置参数

    def __post_init__(self):
        """验证配置"""
        if self.metadata is None:
            self.metadata = {}
        elif not isinstance(self.metadata, dict):
            raise ValueError("metadata must be an object")

        import src.fetchers
        from src.fetchers.base import _registry

        if self.type not in _registry:
            raise ValueError(
                f"Invalid type: {self.type}. Must be one of {list(_registry.keys())}"
            )

        if not self.src:
            raise ValueError("src is required")

        # 动态委派给对应的 fetcher 进行验证与初始化修饰
        fetcher_class = _registry.get(self.type)
        if fetcher_class and hasattr(fetcher_class, "validate_source"):
            fetcher_class.validate_source(self)

    def __hash__(self) -> int:
        """自定义哈希，仅使用不可变字段，避免 list/dict 导致的 unhashable 错误"""
        return hash((
            self.type,
            self.src,
            self.priority,
            self.title,
            self.keep_link,
            self.delete,
            self.load_images,
            json.dumps(self.metadata, ensure_ascii=False, sort_keys=True, default=str),
        ))


@dataclass
class WebDavConfig:
    """WebDAV 配置（仅由环境变量构造，不属于 Config 文件配置）。"""
    enabled: bool = False
    url: Optional[str] = None
    username: Optional[str] = None
    password: Optional[str] = None
    remote_path: str = "/"


@dataclass
class Config:
    """全局配置"""
    title: TitleConfig
    body: List[ContentSource]
    limit: int = 15  # 全局每源抓取上限
    load_images: str = "Y"  # 全局是否加载图片 (Y/N)

    def get_sorted_sources(self) -> List[ContentSource]:
        """获取按优先级排序的内容源（降序，稳定排序）"""
        return sorted(self.body, key=lambda x: x.priority, reverse=True)


def load_config(config_path: str = "config.json") -> Config:
    """
    加载配置

    优先级：
    1. CONFIG_JSON 环境变量
    2. config.json 文件
    """
    config_data = None

    # 1. 尝试从环境变量加载
    config_json_env = os.getenv("CONFIG_JSON")
    if config_json_env:
        try:
            config_data = json.loads(config_json_env)
        except json.JSONDecodeError as e:
            raise ValueError(f"Failed to parse CONFIG_JSON: {e}")
    else:
        # 2. 从文件加载
        if not os.path.exists(config_path):
            raise FileNotFoundError(
                f"Config file not found: {config_path}\n"
                f"Please create config.json or set CONFIG_JSON environment variable"
            )

        with open(config_path, 'r', encoding='utf-8') as f:
            config_data = json.load(f)

    # 验证和解析配置
    return _parse_config(config_data)


def _parse_config(data: Dict[str, Any]) -> Config:
    """解析配置数据"""
    if not isinstance(data, dict):
        raise ValueError("config must be an object")
    # 解析标题配置
    if "title" not in data:
        raise ValueError("title is required in config")

    title_data = data["title"]
    title_config = TitleConfig(
        text=title_data.get("text", "Daily News"),
        img=title_data.get("img")
    )

    # 解析内容源配置
    if "body" not in data or not isinstance(data["body"], list):
        raise ValueError("body must be a non-empty array in config")

    sources = []
    for idx, source_data in enumerate(data["body"]):
        try:
            raw_priority = source_data.get("priority")
            try:
                priority = int(raw_priority) if raw_priority is not None and str(raw_priority).strip() != "" else 0
            except (ValueError, TypeError):
                priority = 0

            legacy_keys = {"full_text", "goal", "model"}
            misplaced_keys = sorted(legacy_keys.intersection(source_data))
            if misplaced_keys:
                raise ValueError(
                    f"Fetcher-specific options must be nested under metadata: "
                    f"{', '.join(misplaced_keys)}"
                )

            metadata = source_data.get("metadata")

            source = ContentSource(
                type=source_data.get("type"),
                src=source_data.get("src"),
                priority=priority,
                title=source_data.get("title"),
                keep_link=source_data.get("keep_link", "Y"),
                exclude=source_data.get("exclude"),
                delete=source_data.get("delete"),
                load_images=source_data.get("load_images", "Y"),
                metadata=metadata,
            )
            sources.append(source)
        except Exception as e:
            raise ValueError(f"Error parsing body[{idx}]: {e}")

    raw_limit = data.get("limit")
    if raw_limit is None:
        raw_limit = data.get("global_limit", 15)

    valid_limit_type = isinstance(raw_limit, int) and not isinstance(raw_limit, bool)
    if isinstance(raw_limit, str):
        valid_limit_type = raw_limit.strip().isdigit()
    if not valid_limit_type:
        raise ValueError("limit must be a non-negative integer")
    try:
        limit = int(raw_limit)
    except (TypeError, ValueError) as e:
        raise ValueError("limit must be a non-negative integer") from e
    if limit < 0:
        raise ValueError("limit must be a non-negative integer")

    return Config(
        title=title_config,
        body=sources,
        limit=limit,
        load_images=data.get("load_images", "Y")
    )


def get_secret(secret_name: str, required: bool = True) -> Optional[str]:
    """
    获取 Secret 值

    Args:
        secret_name: Secret 名称
        required: 是否必需

    Returns:
        Secret 值

    Raises:
        ValueError: 如果必需的 Secret 不存在
    """
    value = os.getenv(secret_name)

    if required and not value:
        raise ValueError(
            f"Required secret '{secret_name}' is not set. "
            f"Please add it to GitHub Secrets or environment variables."
        )

    return value


def get_smtp_config() -> Dict[str, str]:
    """获取 SMTP 配置"""
    return {
        "host": get_secret("SMTP_HOST"),
        "port": int(get_secret("SMTP_PORT")),
        "username": get_secret("SMTP_USERNAME"),
        "password": get_secret("SMTP_PASSWORD"),
        "kindle_email": get_secret("KINDLE_EMAIL")
    }


def get_webdav_config() -> Optional[WebDavConfig]:
    """获取 WebDAV 配置（可选）"""
    enabled = os.getenv("WEBDAV_ENABLED", "false").lower() == "true"
    if not enabled:
        return None

    return WebDavConfig(
        enabled=True,
        url=get_secret("WEBDAV_URL"),
        username=get_secret("WEBDAV_USERNAME"),
        password=get_secret("WEBDAV_PASSWORD"),
        remote_path=os.getenv("WEBDAV_REMOTE_PATH") or "/"
    )
