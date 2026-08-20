"""
pytest 全局配置
提供共享的 fixtures
"""

import os
import sys
import pytest
import tempfile

# 确保项目根目录在 sys.path 中，以便直接 `import src.xxx`
sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))

from src.config import ContentSource, TitleConfig, Config


# ---------------------------------------------------------------------------
# ContentSource fixtures
# ---------------------------------------------------------------------------

@pytest.fixture
def rss_source():
    """标准 RSS 内容源"""
    return ContentSource(
        type="rss",
        src="https://hnrss.org/frontpage",
        title="Hacker News",
        priority=10,
        keep_link="Y",
        metadata={"full_text": "N"},
    )


@pytest.fixture
def rss_full_text_source():
    """启用全文抓取的 RSS 内容源"""
    return ContentSource(
        type="rss",
        src="https://example.com/rss",
        title="Full Text RSS",
        priority=5,
        keep_link="Y",
        metadata={"full_text": "Y"},
    )


@pytest.fixture
def web_source():
    """标准网页内容源"""
    return ContentSource(
        type="web",
        src="https://example.com/article",
        title="测试文章",
        priority=5,
        keep_link="N",
    )


@pytest.fixture
def mail_source():
    """标准邮件内容源"""
    return ContentSource(
        type="mail",
        src="test_namespace",
        title="测试邮件",
        priority=8,
        metadata={"tag": "daily", "limit": 10},
    )


@pytest.fixture
def trending_source():
    """标准 trending 内容源"""
    return ContentSource(
        type="trending",
        src="AI 最新趋势",
        title="AI 热点",
        priority=15,
        metadata={"goal": "分析最新 AI 发展", "model": "openai/gpt-4o"},
    )


@pytest.fixture
def source_with_exclude():
    """带 exclude 规则的内容源"""
    return ContentSource(
        type="rss",
        src="https://example.com/rss",
        priority=5,
        exclude=[
            {"type": "start", "value": "前言部分"},
            {"type": "end", "value": "— 完 —"},
            {"type": "exact", "value": "<span class=\"ad\">广告</span>"},
        ],
    )


@pytest.fixture
def source_with_delete():
    """带 delete 关键词的内容源"""
    return ContentSource(
        type="rss",
        src="https://example.com/rss",
        priority=5,
        delete="广告,推广,赞助",
    )


# ---------------------------------------------------------------------------
# TitleConfig / Config fixtures
# ---------------------------------------------------------------------------

@pytest.fixture
def title_config():
    return TitleConfig(text="{每日新闻 {time}}", img="")


@pytest.fixture
def minimal_config_data():
    """最小有效配置 dict"""
    return {
        "title": {"text": "Test {time}", "img": ""},
        "body": [
            {"type": "rss", "src": "https://example.com/rss"}
        ],
    }


@pytest.fixture
def full_config_data():
    """包含所有属性的配置 dict"""
    return {
        "title": {"text": "{每日新闻 {time}}", "img": "https://example.com/cover.jpg"},
        "body": [
            {
                "type": "rss",
                "src": "https://example.com/rss",
                "title": "RSS 源",
                "priority": 10,
                "keep_link": "Y",
                "metadata": {"full_text": "Y"},
                "exclude": [
                    {"type": "start", "value": "阅读更多"},
                    {"type": "end", "value": "— 完 —"},
                ],
                "delete": "广告,推广",
            },
            {
                "type": "web",
                "src": "https://example.com/article",
                "title": "网页文章",
                "priority": 5,
                "keep_link": "N",
            },
            {
                "type": "mail",
                "src": "test_namespace",
                "title": "订阅邮件",
                "priority": 8,
                "metadata": {
                    "tag": "daily",
                    "timestamp_from": 1718300000000,
                    "limit": 10,
                },
            },
            {
                "type": "trending",
                "src": "AI 趋势",
                "title": "AI 热点",
                "priority": 15,
                "metadata": {
                    "goal": "分析 AI 发展方向",
                    "model": "openai/gpt-4o",
                },
            },
        ],
    }


# ---------------------------------------------------------------------------
# 临时文件 fixtures
# ---------------------------------------------------------------------------

@pytest.fixture
def tmp_dir():
    """临时目录，测试结束后自动清理"""
    with tempfile.TemporaryDirectory() as d:
        yield d


@pytest.fixture
def tmp_config_file(tmp_dir, minimal_config_data):
    """写入临时 config.json 并返回路径"""
    import json
    path = os.path.join(tmp_dir, "config.json")
    with open(path, "w", encoding="utf-8") as f:
        json.dump(minimal_config_data, f)
    return path


@pytest.fixture
def sample_html():
    """用于测试内容处理的 HTML 片段"""
    return """
<html><body>
<p>前言部分</p>
<p>这是正文的第一段。</p>
<p>这是正文的第二段，包含 <a href="https://example.com">一个链接</a>。</p>
<p>这是正文的第三段。</p>
<span class="ad">广告</span>
<p>这是结尾段落。</p>
<p>— 完 —</p>
<p>这段应该被删除。</p>
</body></html>
"""


@pytest.fixture(autouse=True)
def mock_cover_generator_network(monkeypatch):
    """
    全局 Mock CoverGenerator 的网络请求（获取 Bing 壁纸及下载自定义图片），
    避免测试过程中产生真实的网络 I/O，显著提升测试运行速度。
    """
    from PIL import Image
    from src.epub.cover import CoverGenerator

    def mock_fetch_bing_wallpaper(self):
        # 返回一个简单的 640x960 纯色 PIL Image
        return Image.new('RGB', (640, 960), color=(240, 240, 240))

    def mock_download_image(self, url):
        # 同样返回一个简单的 640x960 纯色 PIL Image
        return Image.new('RGB', (640, 960), color=(220, 220, 220))

    monkeypatch.setattr(CoverGenerator, "_fetch_bing_wallpaper", mock_fetch_bing_wallpaper)
    monkeypatch.setattr(CoverGenerator, "_download_image", mock_download_image)
