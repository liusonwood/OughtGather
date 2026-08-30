"""
EPUB 辅助工具模块测试
测试 src/epub/helpers.py 中的工具函数
"""

import pytest
from ebooklib import epub
from src.epub.helpers import generate_toc_link, create_section_divider_page
from src.epub.i18n import EPUBTranslator


class TestEPUBHelpers:
    """EPUB 辅助工具函数测试"""

    def test_generate_toc_link(self):
        """测试生成返回目录超链接"""
        link_html = generate_toc_link("toc_chapter_1", EPUBTranslator("zh-CN"))
        assert 'class="toc-link"' in link_html
        assert 'href="contents.xhtml#toc_chapter_1"' in link_html
        assert "返回目录" in link_html
        assert "style" not in link_html

    def test_create_section_divider_page(self):
        """测试生成章节分隔页"""
        articles_info = [
            {"title": "文章标题 1 & 测试", "file_name": "chapter_0.xhtml"},
            {"title": "文章标题 2", "file_name": "chapter_1.xhtml"}
        ]
        divider = create_section_divider_page(
            section_title="测试大栏目 & 频道",
            file_name="divider_99.xhtml",
            target_toc_id="toc_section_99",
            articles_info=articles_info,
            translator=EPUBTranslator("zh-CN")
        )
        assert isinstance(divider, epub.EpubHtml)
        assert divider.title == "测试大栏目 & 频道"
        assert divider.file_name == "divider_99.xhtml"

        # 检查生成内容中是否有正确转义的标题、链接和返回目录片段
        content = divider.content
        assert "<title>测试大栏目 &amp; 频道</title>" in content
        assert "<h2>测试大栏目 &amp; 频道</h2>" in content
        assert 'href="contents.xhtml#toc_section_99"' in content
        assert "返回目录" in content
        assert 'class="toc-link"' in content

        # 检查是否包含子目录列表及其样式与转义
        assert 'id="toc"' in content
        assert 'class="article-link"' in content
        assert 'href="chapter_0.xhtml"' in content
        assert '文章标题 1 &amp; 测试' in content
        assert 'href="chapter_1.xhtml"' in content
        assert '文章标题 2' in content
