"""
配置模块测试
测试 TitleConfig、ContentSource、Config 的数据类行为，以及 load_config 的加载逻辑
"""

import json
import os
import re
import pytest
from datetime import datetime

from src.config import (
    TitleConfig,
    ContentSource,
    Config,
    load_config,
    _parse_config,
)


# =========================================================================
# TitleConfig 测试
# =========================================================================

class TestTitleConfig:
    """TitleConfig 数据类测试"""

    def test_simple_time_placeholder(self):
        """测试独立的 {time} 占位符"""
        config = TitleConfig(text="每日新闻 {time}")
        result = config.get_display_text()
        today = datetime.now().strftime("%Y-%m-%d")
        assert result == f"每日新闻 {today}"

    def test_nested_time_placeholder(self):
        """测试嵌套的 {前缀 {time}} 占位符"""
        config = TitleConfig(text="{Daily News {time}}")
        result = config.get_display_text()
        today = datetime.now().strftime("%Y-%m-%d")
        assert result == f"Daily News {today}"

    def test_no_time_placeholder(self):
        """测试不含占位符的纯文本"""
        config = TitleConfig(text="固定书名")
        assert config.get_display_text() == "固定书名"

    def test_multiple_time_placeholders(self):
        """测试多个 {time} 占位符"""
        config = TitleConfig(text="{time} - 新闻 - {time}")
        result = config.get_display_text()
        today = datetime.now().strftime("%Y-%m-%d")
        assert result == f"{today} - 新闻 - {today}"

    def test_img_optional(self):
        """测试 img 可选参数"""
        config = TitleConfig(text="Test")
        assert config.img is None

        config_with_img = TitleConfig(text="Test", img="https://example.com/img.jpg")
        assert config_with_img.img == "https://example.com/img.jpg"

    def test_display_text_with_br_tag(self):
        """测试含 </br> 的标题，get_display_text 保留标签"""
        config = TitleConfig(text="{Daily News</br>{time}}")
        result = config.get_display_text()
        today = datetime.now().strftime("%Y-%m-%d")
        assert result == f"Daily News</br> {today}"

    def test_plain_text_strips_br_tag(self):
        """测试 get_plain_text 去除 </br> 标签"""
        config = TitleConfig(text="{Daily News</br>{time}}")
        result = config.get_plain_text()
        today = datetime.now().strftime("%Y-%m-%d")
        assert result == f"Daily News {today}"
        assert "</br>" not in result
        assert "<br>" not in result

    def test_plain_text_strips_all_html_tags(self):
        """测试 get_plain_text 去除所有 HTML 标签"""
        config = TitleConfig(text="<b>Bold</b> <a href='#'>Link</a> News")
        result = config.get_plain_text()
        assert result == "Bold Link News"
        assert "<" not in result
        assert ">" not in result


# =========================================================================
# ContentSource 测试
# =========================================================================

class TestContentSource:
    """ContentSource 数据类测试"""

    def test_valid_types(self):
        """测试所有有效的 type 值"""
        for t in ("rss", "web", "mail", "trending"):
            source = ContentSource(type=t, src="test")
            assert source.type == t

    def test_invalid_type_raises(self):
        """测试无效的 type 抛出 ValueError"""
        with pytest.raises(ValueError, match="Invalid type"):
            ContentSource(type="invalid", src="test")

    def test_empty_src_raises(self):
        """测试空 src 抛出 ValueError"""
        with pytest.raises(ValueError, match="src is required"):
            ContentSource(type="rss", src="")

    def test_default_values(self):
        """测试默认值"""
        source = ContentSource(type="rss", src="https://example.com")
        assert source.priority == 0
        assert source.title is None
        assert source.keep_link == "Y"
        assert source.metadata == {}
        assert source.exclude is None
        assert source.delete is None
        assert "goal" not in source.metadata
        assert "model" not in source.metadata

    def test_trending_auto_goal(self):
        """测试 trending 类型未提供 goal 时自动填充默认值"""
        source = ContentSource(type="trending", src="AI 趋势")
        assert source.metadata["goal"] == "分析并总结相关热点信息"

    def test_trending_with_custom_goal(self):
        """测试 trending 类型使用自定义 goal"""
        source = ContentSource(type="trending", src="AI", metadata={"goal": "自定义分析"})
        assert source.metadata["goal"] == "自定义分析"

    def test_all_fields_set(self):
        """测试所有字段都可正确赋值"""
        source = ContentSource(
            type="rss",
            src="https://example.com/rss",
            priority=10,
            title="测试源",
            keep_link="N",
            exclude=[{"type": "start", "value": "test"}],
            delete="广告,推广",
            metadata={
                "tag": "daily",
                "full_text": "Y",
                "goal": "分析目标",
                "model": "openai/gpt-4o",
            },
        )
        assert source.priority == 10
        assert source.title == "测试源"
        assert source.keep_link == "N"
        assert len(source.exclude) == 1
        assert source.delete == "广告,推广"
        assert source.metadata["full_text"] == "Y"
        assert source.metadata["goal"] == "分析目标"
        assert source.metadata["model"] == "openai/gpt-4o"


# =========================================================================
# Config 测试
# =========================================================================

class TestConfig:
    """Config 数据类测试"""

    def test_get_sorted_sources_descending(self):
        """测试按 priority 降序排列"""
        sources = [
            ContentSource(type="rss", src="a", priority=5),
            ContentSource(type="rss", src="b", priority=15),
            ContentSource(type="rss", src="c", priority=10),
        ]
        config = Config(title=TitleConfig(text="Test"), body=sources)
        sorted_sources = config.get_sorted_sources()
        assert [s.src for s in sorted_sources] == ["b", "c", "a"]

    def test_stable_sort(self):
        """测试相同 priority 保持稳定排序"""
        sources = [
            ContentSource(type="rss", src="a", priority=10),
            ContentSource(type="rss", src="b", priority=10),
            ContentSource(type="rss", src="c", priority=10),
        ]
        config = Config(title=TitleConfig(text="Test"), body=sources)
        sorted_sources = config.get_sorted_sources()
        # 稳定排序应保持原始顺序
        assert [s.src for s in sorted_sources] == ["a", "b", "c"]

    def test_empty_body_sort(self):
        """测试空 body 排序"""
        config = Config(title=TitleConfig(text="Test"), body=[])
        assert config.get_sorted_sources() == []


# =========================================================================
# _parse_config 测试
# =========================================================================

class TestParseConfig:
    """_parse_config 解析测试"""

    def test_parse_minimal_config(self, minimal_config_data):
        """测试最小配置解析"""
        config = _parse_config(minimal_config_data)
        assert config.title.text == "Test {time}"
        assert config.title.img == ""
        assert len(config.body) == 1
        assert config.body[0].type == "rss"
        assert config.body[0].src == "https://example.com/rss"

    def test_parse_full_config(self, full_config_data):
        """测试完整配置解析"""
        config = _parse_config(full_config_data)
        assert config.title.text == "{每日新闻 {time}}"
        assert config.title.img == "https://example.com/cover.jpg"
        assert len(config.body) == 4

        # 检查各类型正确解析
        types = [s.type for s in config.body]
        assert types == ["rss", "web", "mail", "trending"]

        # 检查 RSS 源详细字段
        rss = config.body[0]
        assert rss.metadata["full_text"] == "Y"
        assert len(rss.exclude) == 2
        assert rss.delete == "广告,推广"

        # 检查 mail metadata
        mail = config.body[2]
        assert mail.metadata["tag"] == "daily"
        assert mail.metadata["timestamp_from"] == 1718300000000

        # 检查 trending 字段
        trending = config.body[3]
        assert trending.metadata["goal"] == "分析 AI 发展方向"
        assert trending.metadata["model"] == "openai/gpt-4o"

    def test_missing_title_raises(self):
        """测试缺少 title 抛出异常"""
        with pytest.raises(ValueError, match="title is required"):
            _parse_config({"body": []})

    def test_missing_body_raises(self):
        """测试缺少 body 抛出异常"""
        with pytest.raises(ValueError, match="body must be a non-empty array"):
            _parse_config({"title": {"text": "Test"}})

    def test_body_not_list_raises(self):
        """测试 body 不是列表时抛出异常"""
        with pytest.raises(ValueError, match="body must be a non-empty array"):
            _parse_config({"title": {"text": "Test"}, "body": "not_a_list"})

    @pytest.mark.parametrize("key", ["full_text", "goal", "model"])
    def test_fetcher_options_must_be_nested_in_metadata(self, key):
        """Fetcher 专属配置不得再出现在内容源顶层。"""
        data = {
            "title": {"text": "Test"},
            "body": [{"type": "rss", "src": "https://example.com/rss", key: "Y"}],
        }
        with pytest.raises(ValueError, match="must be nested under metadata"):
            _parse_config(data)

    def test_invalid_source_type_raises(self):
        """测试无效 source type 抛出异常"""
        data = {
            "title": {"text": "Test"},
            "body": [{"type": "invalid", "src": "test"}],
        }
        with pytest.raises(ValueError, match="Invalid type"):
            _parse_config(data)


# =========================================================================
# load_config 测试
# =========================================================================

class TestLoadConfig:
    """load_config 加载测试"""

    def test_load_from_file(self, tmp_config_file):
        """测试从文件加载配置"""
        config = load_config(tmp_config_file)
        assert config.title.text == "Test {time}"
        assert len(config.body) == 1

    def test_load_from_env(self, minimal_config_data, monkeypatch):
        """测试从环境变量加载配置"""
        monkeypatch.setenv("CONFIG_JSON", json.dumps(minimal_config_data))
        config = load_config("nonexistent.json")  # 即使文件不存在也能加载
        assert config.title.text == "Test {time}"

    def test_file_not_found_raises(self):
        """测试配置文件不存在时抛出异常"""
        # 确保 CONFIG_JSON 环境变量不存在
        if os.getenv("CONFIG_JSON"):
            os.environ.pop("CONFIG_JSON")
        with pytest.raises(FileNotFoundError):
            load_config("/nonexistent/path/config.json")

    def test_invalid_json_env_raises(self, monkeypatch):
        """测试无效的 CONFIG_JSON 环境变量"""
        monkeypatch.setenv("CONFIG_JSON", "not_valid_json{{{")
        with pytest.raises(ValueError, match="Failed to parse CONFIG_JSON"):
            load_config()

    def test_env_takes_precedence(self, tmp_config_file, monkeypatch, minimal_config_data):
        """测试环境变量优先于文件"""
        # 修改环境变量中的配置
        env_data = {
            "title": {"text": "From Env", "img": ""},
            "body": [{"type": "rss", "src": "https://env.com/rss"}],
        }
        monkeypatch.setenv("CONFIG_JSON", json.dumps(env_data))
        config = load_config(tmp_config_file)
        # 应该使用环境变量中的配置
        assert config.title.text == "From Env"
        assert config.body[0].src == "https://env.com/rss"
