# Ought Gather — Fetcher 插件开发指南

本文档介绍如何在 Ought Gather 中开发并集成一个新的内容抓取器（Fetcher）插件。

---

## 目录

1. [架构原则与规范](#1-架构原则与规范)
2. [核心类与数据契约](#2-核心类与数据契约)
3. [Fetcher 生命周期与抓取模式](#3-fetcher-生命周期与抓取模式)
   - [单阶段模式（直接抓取）](#31-单阶段模式直接抓取)
   - [两阶段模式（列表过滤 + 正文抓取）](#32-两阶段模式列表过滤--正文抓取)
4. [配置元数据与编辑器集成](#4-配置元数据与编辑器集成)
5. [基类内置辅助方法](#5-基类内置辅助方法)
6. [实战示例：开发一个自定义 Fetcher](#6-实战示例开发一个自定义-fetcher)
7. [编写单元测试](#7-编写单元测试)
8. [开发验收核对清单](#8-开发验收核对清单)

---

## 1. 架构原则与规范

在 Ought Gather 中，抓取器采用**自注册插件化架构（Pluggable Registration）**，在开发新 Fetcher 时必须严格遵循以下原则：

1. **自动扫描与注册**：
   - 所有 Fetcher 必须置于 `src/fetchers/` 目录下，文件命名遵循 `<type_name>_fetcher.py`。
   - Fetcher 类必须继承自 `BaseFetcher`，并定义唯一的类属性 `type_name`（如 `"my_feed"`）。
   - 继承 `BaseFetcher` 时会自动通过 `__init_subclass__` 注册到内部路由字典中，无需且**严禁**在外部代码中手动导入或修改注册表。
2. **严禁外部硬编码（No Hardcoded References）**：
   - 严禁在 `src/config.py`、`src/epub/generator.py`、`src/epub/toc.py` 等核心模块中编写针对特定 Fetcher 的条件判断（如 `if source.type == "my_type"`）。
3. **配置解耦（Decoupled Settings）**：
   - 不得在 `ContentSource` 数据类顶层增加专属于某个 Fetcher 的字段。
   - 所有特异化配置参数统一放在 `source.metadata` 字典中，通过 `cls.validate_source(source)` 进行校验与默认值回填。
4. **呈现与样式解耦（Decoupled Formatting/Styling）**：
   - 电子书样式通过 Fetcher 类的 `custom_css` 属性提供，生成器会在排版时自动合并所有注册 Fetcher 的 CSS。
   - 目录与章节名称由 `FetchResult.source_title` 或 `get_default_source_title` 确定。
5. **统一时区**：
   - 项目规范所有时间计算统一使用北京时间（UTC+8）。获取当前时间必须使用 `from src.utils.helpers import get_now`，禁止使用原生无时区的 `datetime.now()`。

---

## 2. 核心类与数据契约

### 2.1 Article（文章对象）
每篇文章必须封装为 `Article` 数据类（位于 `src/fetchers/base.py`）：

```python
@dataclass
class Article:
    title: str                            # 文章标题（纯文本，必填）
    content: str                          # 文章内容（HTML 格式，必填）
    url: str                              # 原文链接（用于去重与溯源，必填）
    author: Optional[str] = None          # 作者名
    published_date: Optional[str] = None  # 发布时间字符串（如 "2026-09-12 08:00:00"）
    images: List[str] = field(default_factory=list) # 需离线下载的图片绝对 URL 列表
    metadata: Dict[str, Any] = field(default_factory=dict) # 自定义扩展元数据
```

> **注意**：如果正文中包含 `<img>` 标签，建议将图片 URL 提取后放入 `images` 列表中，后置的 `ImageProcessor` 会自动下载、缩放并转为电子书内嵌资源。

### 2.2 FetchResult（抓取结果）
Fetcher 执行完毕后返回 `FetchResult`：

```python
@dataclass
class FetchResult:
    source: ContentSource                 # 关联的内容源配置
    articles: List[Article]               # 抓取到的文章列表
    success: bool = True                  # 整体是否成功
    error: Optional[str] = None           # 错误描述
    error_count: int = 0                  # 捕获的异常条目数
    source_title: Optional[str] = None    # 章节展示名称（如 RSS 标题、城市名称等）
```

---

## 3. Fetcher 生命周期与抓取模式

系统支持两种抓取工作流，可根据目标数据源的特征进行选择：

### 3.1 单阶段模式（直接抓取）

适合于**无需提前去重**或**内容量极少且必须全量计算**的场景（例如 Weather、Trending、Web 单页面）：

- **实现方法**：重写 `fetch(self) -> FetchResult`。
- **去重开关**：若该数据源每次运行都需要刷新（例如天气预报、AI 每日热点总结），需显式在类中声明：
  ```python
  dedup_enabled = False
  ```

### 3.2 两阶段模式（列表过滤 + 正文抓取）

对于 RSS、社交媒体（Twitter/Telegram）、书签（Raindrop）等内容源，先拉取文章摘要列表，经由去重模块过滤掉已推送过的文章后，**仅对剩余的新文章抓取全文和图片**。这种方式极大减少无效网络请求和耗时。

- **开启配置**：
  ```python
  supports_two_phase = True
  ```
- **需要实现的方法**：
  1. `fetch_list(self) -> Optional[List[Dict[str, Any]]]`：
     - 拉取候选列表，不请求全文。
     - 每个元素必须至少包含 `"url"`（用于去重校验）和 `"title"`（可选，用于辅助去重与日志）。
     - 可在字典中保存原始数据对象（例如 `_entry`），供后续使用。
  2. `fetch_items(self, candidates: List[Dict[str, Any]]) -> FetchResult`：
     - 接收去重过滤后且在限制数量（limit）以内的 candidates。
     - 逐条抓取正文与图片，组装成 `Article` 并返回 `FetchResult`。
  3. `fetch(self) -> FetchResult`：
     - 作为回退保底实现（当系统未启用两阶段流程时调用），通常可以直接复用两阶段逻辑：`candidates = self.fetch_list(); return self.fetch_items(candidates)`。

---

## 4. 配置元数据与编辑器集成

项目自带可视化配置编辑器 `config-editor.html`。为了让新 Fetcher 自动在编辑器中显示友好的表单与提示，可在类中声明元数据配置：

```python
class MyFetcher(BaseFetcher):
    type_name = "my_source"
    
    # 1. 对应 config.json 中 body[i].src 的输入提示
    src_placeholder = "请输入目标源 URL 或标识，例如: https://example.com/api"
    
    # 2. metadata 字段规范，定义编辑器自动生成的表单控件
    # 支持类型: "text", "number", "select", "textarea"
    config_schema = {
        "metadata.category": {
            "type": "text",
            "label": "分类标签",
            "placeholder": "technology, finance"
        },
        "metadata.fetch_full_text": {
            "type": "select",
            "label": "获取全文",
            "options": ["Y", "N"],
            "hint": "是否深入抓取正文 HTML"
        },
        "metadata.limit": {
            "type": "number",
            "label": "抓取数量上限",
            "placeholder": "留空继承全局限制"
        }
    }

    # 3. 依赖的环境变量或 GitHub Secrets（说明文档与校验用）
    required_secrets = {
        "MY_SERVICE_TOKEN": "服务访问 API Token，用于身份认证"
    }

    # 4. 可选：针对该内容源的专属样式（会合并注入到 EPUB 全局 CSS 中）
    custom_css = """
    .my-custom-box {
        border-left: 3px solid #333;
        padding-left: 0.8em;
        margin: 1em 0;
    }
    """
```

### 同步到可视化编辑器
编写好上述元数据后，运行辅助脚本即可自动将新的 Fetcher Schema 注入 `config-editor.html`：

```bash
python3.11 scripts/update_editor.py
```

---

## 5. 基类内置辅助方法

`BaseFetcher` 提供了许多开箱即用的工具方法，开发时应优先调用，避免重复造轮子：

| 方法 | 功能说明 |
| --- | --- |
| `self._make_request(url, ...)` | **核心网络请求方法**。复用连接池、统一 User-Agent、提供超时保护、防 SSRF 校验与安全重定向。支持 `allow_browser_fallback=True`。 |
| `self._make_request(..., allow_browser_fallback=True)` | 当遇到动态 JS 挑战（如 HTTP 202）或普通 HTTP 无法正常加载时，自动唤起 Headless Chromium (Playwright) 渲染并返回 HTML。 |
| `self._extract_images(html, base_url)` | 从 HTML 中解析图片绝对链接，智能识别 `src`、`data-src`、`srcset` 懒加载属性，并过滤小图标与 SVG。 |
| `self._extract_og_image(html, base_url)` | 从 `<head>` 的 `meta[property="og:image"]` / `meta[name="twitter:image"]` 中提取封面大图。 |
| `self._fetch_full_text(url)` | 传入文章 URL，通过 Trafilatura 智能提取正文 HTML 并自动还原标准 `<img>` 标签，返回 `(content_html, raw_html)`。 |
| `self._extract_article_metadata(raw_html, url)` | 从原始网页中提取 `(title, author, published_date)`。 |
| `self._should_delete(title)` | 检查文章标题是否命中了配置中 `source.delete` 指定的删除关键词。 |
| `self.get_limit()` | 获取当前源生效的抓取条数上限（优先级：`source.limit` > `metadata.limit` > `global_limit`）。 |

---

## 6. 实战示例：开发一个自定义 Fetcher

下面以一个假想的新闻 API 源 `TechDaily` 为例，演示完整的 Fetcher 实现：

创建文件 `src/fetchers/techdaily_fetcher.py`：

```python
import os
from typing import List, Optional, Dict, Any

from src.config import ContentSource
from src.fetchers.base import BaseFetcher, FetchResult, Article
from src.utils.helpers import get_now, format_date


class TechDailyFetcher(BaseFetcher):
    """TechDaily 科技资讯抓取器"""

    type_name = "techdaily"
    supports_two_phase = True
    dedup_enabled = True
    
    src_placeholder = "分类频道，例如: ai, gadgets, startups"
    config_schema = {
        "metadata.tag": {
            "type": "text",
            "label": "过滤标签",
            "placeholder": "可选标签，如 python"
        },
        "metadata.limit": {
            "type": "number",
            "label": "抓取数量",
            "placeholder": "默认使用全局限制"
        }
    }
    required_secrets = {
        "TECHDAILY_API_KEY": "TechDaily 开放平台 API 密钥"
    }

    custom_css = """
    .techdaily-summary {
        font-style: italic;
        color: #555;
        margin-bottom: 1em;
    }
    """

    def __init__(self, source: ContentSource, global_limit: int = 15, max_retries: int = 2):
        super().__init__(source, global_limit=global_limit, max_retries=max_retries)
        self.api_key = os.environ.get("TECHDAILY_API_KEY", "")

    @classmethod
    def get_default_source_title(cls, source: Any, articles: List[Article], source_title: Optional[str] = None) -> str:
        channel = source.src or "综合"
        return source_title or f"TechDaily - {channel.upper()}"

    def fetch_list(self) -> Optional[List[Dict[str, Any]]]:
        """【阶段一】获取文章元数据列表（用于快速去重）"""
        channel = self.source.src.strip()
        metadata = self.source.metadata or {}
        tag = metadata.get("tag", "")

        url = f"https://api.techdaily.example.com/v1/articles"
        params = {"channel": channel, "tag": tag, "limit": self.get_limit()}
        headers = {"Authorization": f"Bearer {self.api_key}"}

        try:
            resp = self._make_request(url, params=params, headers=headers)
            data = resp.json()
            items = data.get("items", [])

            candidates = []
            for item in items:
                title = item.get("title", "")
                article_url = item.get("url", "")
                if not article_url or self._should_delete(title):
                    continue
                candidates.append({
                    "url": article_url,
                    "title": title,
                    "_item": item  # 暂存接口原始数据
                })
            return candidates
        except Exception as e:
            self.logger.error(f"TechDaily 获取列表失败: {e}")
            return None

    def fetch_items(self, candidates: List[Dict[str, Any]]) -> FetchResult:
        """【阶段二】对去重后保留的条目抓取详情并组装 Article"""
        result = FetchResult(source=self.source, articles=[])

        for entry in candidates:
            item = entry.get("_item", {})
            title = entry.get("title") or item.get("title", "Untitled")
            article_url = entry["url"]

            try:
                # 优先使用接口给出的摘要，或抓取全文网页
                summary = item.get("summary", "")
                content_html = f"<div class='techdaily-summary'>{summary}</div>"
                images = []

                # 如果没有全文，使用基类 helper 从网页提取
                if not item.get("full_content"):
                    fetched_html, raw_html = self._fetch_full_text(article_url)
                    if fetched_html:
                        content_html += fetched_html
                        images = self._extract_images(fetched_html, base_url=article_url)
                    else:
                        content_html += f"<p><a href='{article_url}'>阅读原文</a></p>"
                else:
                    content_html += item["full_content"]
                    images = self._extract_images(content_html, base_url=article_url)

                article = Article(
                    title=title,
                    content=content_html,
                    url=article_url,
                    author=item.get("author", "TechDaily"),
                    published_date=item.get("published_at") or get_now().strftime("%Y-%m-%d %H:%M:%S"),
                    images=images
                )
                result.articles.append(article)

            except Exception as exc:
                self.logger.warning(f"解析 TechDaily 文章失败 [{article_url}]: {exc}")
                result.add_error(f"解析失败: {exc}")

        result.source_title = f"TechDaily - {self.source.src.upper()}"
        result.success = len(result.articles) > 0 or result.error_count == 0
        return result

    def fetch(self) -> FetchResult:
        """单阶段调用回退实现"""
        candidates = self.fetch_list()
        if candidates is None:
            return FetchResult(source=self.source, articles=[], success=False, error="获取候选列表失败")
        return self.fetch_items(candidates[:self.get_limit()])
```

---

## 7. 编写单元测试

在 `tests/` 目录下新建 `test_techdaily_fetcher.py`。为了保证 CI 环境平稳运行，所有外部 HTTP 请求均需通过 `unittest.mock` 进行模拟。

```python
import os
import pytest
from unittest.mock import MagicMock, patch

from src.config import ContentSource
from src.fetchers.techdaily_fetcher import TechDailyFetcher


class TestTechDailyFetcher:

    @pytest.fixture
    def source(self):
        return ContentSource(
            type="techdaily",
            src="ai",
            metadata={"tag": "deeplearning", "limit": 5}
        )

    @patch.dict(os.environ, {"TECHDAILY_API_KEY": "fake_token"})
    @patch.object(TechDailyFetcher, "_make_request")
    def test_fetch_two_phase_success(self, mock_make_request, source):
        # 1. 模拟列表请求返回
        mock_response = MagicMock()
        mock_response.json.return_value = {
            "items": [
                {
                    "id": "1",
                    "title": "GPT Next Released",
                    "url": "https://techdaily.example.com/article/1",
                    "summary": "Summary of GPT Next",
                    "full_content": "<p>Article details here</p>",
                    "author": "Alice"
                }
            ]
        }
        mock_make_request.return_value = mock_response

        fetcher = TechDailyFetcher(source)

        # 测试阶段一：fetch_list
        candidates = fetcher.fetch_list()
        assert candidates is not None
        assert len(candidates) == 1
        assert candidates[0]["title"] == "GPT Next Released"

        # 测试阶段二：fetch_items
        result = fetcher.fetch_items(candidates)
        assert result.success is True
        assert len(result.articles) == 1
        
        art = result.articles[0]
        assert art.title == "GPT Next Released"
        assert "Article details here" in art.content
        assert art.author == "Alice"

    @patch.dict(os.environ, {"TECHDAILY_API_KEY": "fake_token"})
    @patch.object(TechDailyFetcher, "_make_request")
    def test_fetch_error_handling(self, mock_make_request, source):
        mock_make_request.side_effect = RuntimeError("Network timeout")

        fetcher = TechDailyFetcher(source)
        result = fetcher.fetch()

        assert result.success is False
        assert "获取候选列表失败" in result.error
```

运行测试命令：
```bash
python3.11 -m pytest tests/test_techdaily_fetcher.py -v
```

---

## 8. 开发验收核对清单

在完成新 Fetcher 开发后，提交 PR 或代码合并前请确认以下各项：

- [ ] **类继承与命名**：继承了 `BaseFetcher`，设置了唯一的 `type_name`，文件位于 `src/fetchers/<type_name>_fetcher.py`。
- [ ] **零侵入架构**：没有在 `src/main.py`、`src/config.py`、`src/epub/generator.py` 等外部文件中硬编码任何关于此 Fetcher 的 `if/else`。
- [ ] **配置与元数据**：定义了 `src_placeholder`、`config_schema`，并在需要密钥时声明了 `required_secrets`。
- [ ] **编辑器同步**：已执行 `python3.11 scripts/update_editor.py` 更新 `config-editor.html`。
- [ ] **关键词过滤**：在解析候选条目时调用了 `self._should_delete(title)`。
- [ ] **时区规范**：日期生成均使用了 `src.utils.helpers.get_now()`（北京时间）。
- [ ] **图片解析**：提取到的图片均为绝对 URL（可借助 `self._resolve_url`），并填充进了 `article.images`。
- [ ] **单测覆盖**：在 `tests/test_<type_name>_fetcher.py` 中编写了 Mock 单元测试并全部通过（`pytest` 绿灯）。
