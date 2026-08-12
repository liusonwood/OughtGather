"""
热点分析抓取器模块
调用 LLM API 生成热点分析内容
"""

import json
import markdown
import re
import os
from datetime import datetime
from typing import Optional, Dict, Any

from src.config import ContentSource
from src.fetchers.base import BaseFetcher, FetchResult, Article
from src.utils.logger import get_logger
from src.utils.helpers import generate_content_id, get_now

class TrendingFetcher(BaseFetcher):
    """热点分析抓取器"""

    type_name = "trending"
    dedup_enabled = False
    src_placeholder = "关键词, 例如: 人工智能最新发展趋势"
    
    # 按照配置规范注册 config_schema
    config_schema = {
        "goal": {
            "type": "textarea",
            "label": "目标 (goal)",
            "placeholder": "LLM 分析目标，例如: 分析最新的 AI 技术突破..."
        },
        "metadata.language": {
            "type": "select",
            "label": "输出语言",
            "options": [
                {"value": "auto", "label": "根据时区自动识别"},
                {"value": "Chinese", "label": "中文 (Chinese)"},
                {"value": "English", "label": "英文 (English)"}
            ],
            "default": "auto",
            "placeholder": "请选择输出语言"
        },
        "metadata.search_topic": {
            "type": "select",
            "label": "搜索主题类型",
            "options": [
                {"value": "news", "label": "新闻资讯 (最新时效)"},
                {"value": "general", "label": "通用网页 (历史数据)"}
            ],
            "default": "news",
            "placeholder": "请选择搜索主题类型"
        },
        "metadata.search_time_range": {
            "type": "select",
            "label": "搜索时间范围",
            "options": [
                {"value": "day", "label": "当天 (24小时内)"},
                {"value": "week", "label": "最近1周"},
                {"value": "month", "label": "最近1月"},
                {"value": "year", "label": "最近1年"}
            ],
            "default": "day",
            "placeholder": "请选择搜索时间范围"
        }
    }
    
    required_secrets = {
        "OPENROUTER_API_KEY": "OpenRouter API 密钥，用于调用 LLM 生成热点分析。",
        "OPENROUTER_API_ENDPOINT": "自定义 OpenRouter 兼容接口，默认 `https://openrouter.ai/api/v1/chat/completions`。",
        "OPENROUTER_MODEL": "使用的 LLM 模型名称。",
        "TAVILY_API_KEY": "Tavily API 密钥，用于搜索热点信息。"
    }

    @classmethod
    def validate_source(cls, source: Any):
        """验证/修饰 trending 类型的 ContentSource 实例。"""
        if not source.goal:
            source.goal = "分析并总结相关热点信息"

    def __init__(self, source: ContentSource, global_limit: int = 15, max_retries: int = 3):
        """
        初始化热点分析抓取器

        Args:
            source: 内容源配置
            global_limit: 全局抓取数量限制
            max_retries: 最大重试次数
        """
        super().__init__(source, global_limit=global_limit, max_retries=max_retries)

        # 内部获取 OpenRouter 配置
        api_key = os.environ.get("OPENROUTER_API_KEY")
        if api_key:
            self.config = {
                "api_key": api_key,
                "endpoint": os.environ.get("OPENROUTER_API_ENDPOINT") or "https://openrouter.ai/api/v1/chat/completions",
                "model": os.environ.get("OPENROUTER_MODEL"),
            }
        else:
            self.config = None
            self.logger.warning(
                "OPENROUTER_API_KEY not configured. Trending analysis will be skipped."
            )

        # 内部获取 Tavily 配置
        self.tavily_api_key = os.environ.get("TAVILY_API_KEY")


    def fetch(self) -> FetchResult:
        """
        执行热点分析抓取

        Returns:
            FetchResult: 抓取结果
        """
        result = FetchResult(source=self.source, articles=[])

        # 检查配置
        if not self.config:
            result.success = False
            result.error = "OPENROUTER_API_KEY not configured"
            return result

        # 检查是否有 goal 配置
        if not self.source.goal:
            result.success = False
            result.error = "goal is required for trending type"
            return result

        try:
            # 1. 搜索实时信息
            search_results = self._search_web(self.source.src) if self.tavily_api_key else []

            # 2. 调用 LLM API
            analysis, model, extracted_title = self._call_llm_api(search_results)

            if not analysis:
                result.success = False
                result.error = "Failed to get analysis from LLM"
                return result

            # 创建文章对象（带当日时间戳，用于去重哈希计算）
            # 作者使用实际调用的 LLM 模型名称
            # 文章标题优先从 AI 回复中提取（extracted_title），自定义标题 (self.source.title) 仅作为 EPUB 大章节标题
            title = extracted_title or f"热点分析: {self.source.src}"
            today = get_now().strftime("%Y-%m-%d")
            article = Article(
                title=title,
                content=analysis,
                url=self.source.src,
                author=model,
                published_date=today,
                metadata={
                    "goal": self.source.goal,
                    "model": model,
                    "has_search_context": len(search_results) > 0
                }
            )

            # 记录带时间戳的去重哈希
            content_id = generate_content_id(article.url, article.title, today)
            self.logger.info(f"Trending dedup hash [{today}]: src={self.source.src}, hash={content_id}")

            result.articles.append(article)
            return result

        except Exception as e:
            self.logger.error(f"Trending fetch failed: {e}")
            result.success = False
            result.error = str(e)
            return result

    def _search_web(self, query: str) -> list:
        """调用 Tavily API 获取实时信息"""
        import httpx
        try:
            # 安全读取通过 config_schema 注册并配置的 metadata 参数
            metadata = getattr(self.source, "metadata", {}) or {}
            search_topic = metadata.get("search_topic", "news")
            search_time_range = metadata.get("search_time_range", "day")

            with httpx.Client(timeout=10) as client:
                headers = {
                    "Authorization": f"Bearer {self.tavily_api_key}",
                    "Content-Type": "application/json"
                }
                payload = {
                    "query": query,
                    "max_results": 3,
                    "search_depth": "advanced",
                    "topic": search_topic,
                    "time_range": search_time_range
                }
                resp = client.post(
                    "https://api.tavily.com/search",
                    headers=headers,
                    json=payload
                )
                resp.raise_for_status()
                return resp.json().get("results", [])
        except Exception as e:
            self.logger.error(f"Search failed: {e}")
            return []

    def _get_target_language(self) -> str:
        """
        根据系统时区和配置判断目标语言，默认中文
        """
        try:
            # 1. 优先读取配置中的 metadata.language
            metadata = getattr(self.source, "metadata", {}) or {}
            lang_opt = metadata.get("language", "auto")
            if lang_opt in ["Chinese", "zh", "cn", "Chinese (中文)", "中文"]:
                return "Chinese"
            if lang_opt in ["English", "en"]:
                return "English"

            # 2. 如果是 auto，根据系统时区自动判断
            now = datetime.now().astimezone()
            tz_name = now.tzname() or ""
            offset = now.utcoffset()
            offset_seconds = offset.total_seconds() if offset is not None else 0

            # 如果是 CST (China Standard Time), offset 是 +8 小时 (+28800 秒)
            # 美国 Central Standard Time (CST) 是 -6 小时 (-21600 秒)
            if tz_name == 'CST' and offset_seconds > 0:
                return "Chinese"

            # 映射列表 (简单示例)
            english_tzs = ['EST', 'EDT', 'CDT', 'MST', 'MDT', 'PST', 'PDT', 'GMT', 'UTC', 'CET', 'CEST']
            if tz_name == 'CST' and offset_seconds <= 0:
                english_tzs.append('CST')

            if tz_name in english_tzs:
                return "English"
        except Exception:
            pass
        return "Chinese" # 默认中文

    def _call_llm_api(self, search_results: list) -> tuple:
        """
        调用 LLM API

        Returns:
            tuple: (分析结果 HTML, 实际调用的模型名称, 提取的标题)；调用失败时 HTML 和提取的标题为 None
        """
        # 构造 prompt
        prompt = self._build_prompt(search_results)

        # 构造请求
        headers = {
            "Authorization": f"Bearer {self.config['api_key']}",
            "Content-Type": "application/json"
        }

        # 确定使用的模型：source.model > OPENROUTER_MODEL secret > 默认值
        model = (
            self.source.model
            or (self.config.get("model") if self.config else None)
            or "google/gemma-4-31b-it:free"
        )

        target_lang = self._get_target_language()
        payload = {
            "model": model,
            "messages": [
                {
                    "role": "system",
                    "content": (
                        "You are an expert industry analyst specializing in capturing cutting-edge information, identifying key trends, and distilling actionable insights."
                        "When performing the analysis, you must leverage the [Real-time Web Search Results] provided by the user as your core factual basis and reference."
                        "Your analysis style: Depth over breadth, data-supported arguments, avoid empty jargon or generalities, concise and impactful language."
                        f"Output language: {target_lang} only."
                        "\n\nOutput Specifications:\n"
                        "- The very first line of your response must be the title of the analysis (can be plain text or markdown heading).\n"
                        "- Strictly use Markdown format with clear hierarchy (H2/H3/lists/bold)\n"
                        "- Each point must contain specific facts or data; avoid hollow descriptions\n"
                        "- If information is uncertain, clearly mark it as 'To be verified'\n"
                        "- Do not output Markdown code block wrappers"
                    )
                },
                {
                    "role": "user",
                    "content": prompt
                }
            ],
            "temperature": 0.7,
            "max_tokens": 2000
        }

        try:
            # 使用 httpx 发送 POST 请求
            import httpx
            with httpx.Client(timeout=60) as client:
                resp = client.post(
                    self.config['endpoint'],
                    headers=headers,
                    json=payload
                )
                
                # 如果状态码不对，在抛出异常前把 OpenRouter 的原生错误明细打印到日志里
                if resp.status_code >= 400:
                    self.logger.error(f"OpenRouter error: {resp.text}")
                
                resp.raise_for_status()
                data = resp.json()

            # 提取响应内容
            content = data.get("choices", [{}])[0].get("message", {}).get("content")
            extracted_title = None
            if content:
                cleaned_content = self._remove_code_block_markers(content).strip()
                lines = cleaned_content.splitlines()
                
                # 找到第一个非空行作为候选标题行
                non_empty_indices = [i for i, line in enumerate(lines) if line.strip()]
                
                if non_empty_indices:
                    first_non_empty_idx = non_empty_indices[0]
                    first_line = lines[first_non_empty_idx].strip()
                    
                    # 提取首行作为标题（支持 Markdown 标题 #/##/###、加粗 **/** 或纯文本）
                    raw_title = first_line
                    # 1. 移除开头的 # 号及空格
                    raw_title = re.sub(r'^#{1,6}\s*', '', raw_title)
                    # 2. 移除结尾的 # 号
                    raw_title = re.sub(r'\s*#+$', '', raw_title)
                    # 3. 移除头尾的加粗/斜体标记 (*, _, ** __)
                    raw_title = re.sub(r'^\*{1,2}|^\_{1,2}', '', raw_title)
                    raw_title = re.sub(r'\*{1,2}$|\_{1,2}$', '', raw_title)
                    extracted_title = raw_title.strip()
                    
                    if extracted_title and len(extracted_title) <= 200:
                        # 从原 content 中移除该行
                        lines.pop(first_non_empty_idx)
                        cleaned_content = "\n".join(lines).strip()
                    else:
                        extracted_title = None
                        self.logger.warning(f"Failed to extract title from first line: '{first_line}'. Content will be used as-is.")
                else:
                    self.logger.warning("AI returned empty content.")
                
                return self._format_as_html(cleaned_content), model, extracted_title

            self.logger.error(f"Unexpected API response: {data}")
            return None, model, None

        except Exception as e:
            self.logger.error(f"LLM API call failed: {e}")
            return None, model, None

    def _build_prompt(self, search_results: list) -> str:
        """
        Construct prompt

        Returns:
            str: prompt text
        """
        today = get_now().strftime("%Y-%m-%d")
        
        search_context = ""
        if search_results:
            search_context = "\n## Real-time Web Search Results (for reference)\n"
            for i, res in enumerate(search_results, 1):
                search_context += f"[{i}] {res.get('title')}: {res.get('content')}\n"
        
        return f"""## Analysis Task

**Current Date**: {today}
**Topic**: {self.source.src}
**Core Goal**: {self.source.goal}
{search_context}

## Output Requirements

Please provide a structured, in-depth analysis report around the above topic, covering the following dimensions:

### 1. Recent Hot Dynamics (3-5 items)
- List the most noteworthy specific events or developments
- Each item must include time context or specific sources (if available)

### 2. Key Trends and Signals
- Identify 2-3 emerging medium-to-long-term trends
- Explain the drivers for each trend

### 3. Core Insights and Actionable Recommendations
- Extract 1-2 most noteworthy core insights
- Provide recommendations or implications that have actual value for the target audience

## Quality Standards
- Content is based on facts; avoid speculation; mark uncertain information as 'To be verified'
- Language is concise; each key point should not exceed 60 words
- When citing online information, annotate with [1], [2], etc.
"""

    def _format_as_html(self, text: str) -> str:
        """
        将 Markdown 文本转换为 HTML

        Args:
            text: Markdown 文本

        Returns:
            str: HTML 格式文本
        """
        # 清理 LLM 可能返回的代码块标记
        text = self._remove_code_block_markers(text)

        # 使用 markdown 库转换为 HTML
        html = markdown.markdown(
            text,
            extensions=[
                'extra',  # 支持表格、代码块等扩展
                'codehilite',  # 代码高亮
                'tables',  # 表格支持
                'fenced_code',  # 围栏代码块
            ],
            output_format='html5'
        )

        return html

    @staticmethod
    def _remove_code_block_markers(text: str) -> str:
        """
        移除文本中可能出现的任何 Markdown 代码块标记。

        Args:
            text: 原始文本

        Returns:
            str: 清理后的文本
        """
        # 使用正则表达式匹配并移除 ``` 或 ''' 代码块及其可选语言标识
        return re.sub(r"```[a-zA-Z]*\n?|'''[a-zA-Z]*\n?", "", text).strip()