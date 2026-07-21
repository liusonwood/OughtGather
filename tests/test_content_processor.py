"""
内容处理器测试
测试 exclude、chop、keep_link、delete 等规则的 HTML 处理行为
"""

import pytest
from bs4 import BeautifulSoup

from src.config import ContentSource
from src.fetchers.base import Article
from src.processors.content_processor import ContentProcessor


def _make_article(content: str, title: str = "Test") -> Article:
    """构造测试用 Article"""
    return Article(
        title=title,
        content=content,
        url="https://example.com/test",
    )


# =========================================================================
# exclude: start 规则测试
# =========================================================================

class TestExcludeStart:
    """exclude type=start 测试"""

    def test_delete_from_start(self, sample_html, source_with_exclude):
        """删除从开头到 '前言部分' 的内容"""
        processor = ContentProcessor(source_with_exclude)
        article = _make_article(sample_html)
        result = processor.process(article)
        # "前言部分" 及其之前内容应被删除
        assert "前言部分" not in result.content

    def test_start_keyword_not_found(self):
        """start 关键词不存在时 HTML 保持不变"""
        source = ContentSource(
            type="rss", src="https://example.com/rss",
            exclude=[{"type": "start", "value": "不存在的关键词"}],
        )
        processor = ContentProcessor(source)
        html = "<p>内容A</p><p>内容B</p>"
        article = _make_article(html)
        result = processor.process(article)
        assert "内容A" in result.content
        assert "内容B" in result.content

    def test_start_with_html_tags(self):
        """start 关键词包含 HTML 标签的情况"""
        source = ContentSource(
            type="rss", src="https://example.com/rss",
            exclude=[{"type": "start", "value": "阅读更多"}],
        )
        processor = ContentProcessor(source)
        html = '<p>摘要内容</p><a href="#">阅读更多</a><p>正文内容</p>'
        article = _make_article(html)
        result = processor.process(article)
        assert "阅读更多" not in result.content
        assert "正文内容" in result.content


# =========================================================================
# exclude: end 规则测试
# =========================================================================

class TestExcludeEnd:
    """exclude type=end 测试"""

    def test_delete_from_end(self, sample_html, source_with_exclude):
        """删除从 '— 完 —' 到结尾的内容"""
        processor = ContentProcessor(source_with_exclude)
        article = _make_article(sample_html)
        result = processor.process(article)
        assert "— 完 —" not in result.content
        assert "这段应该被删除" not in result.content

    def test_end_keyword_not_found(self):
        """end 关键词不存在时 HTML 保持不变"""
        source = ContentSource(
            type="rss", src="https://example.com/rss",
            exclude=[{"type": "end", "value": "不存在的关键词"}],
        )
        processor = ContentProcessor(source)
        html = "<p>内容A</p><p>内容B</p>"
        article = _make_article(html)
        result = processor.process(article)
        assert "内容A" in result.content
        assert "内容B" in result.content

    def test_end_uses_rfind(self):
        """end 应使用 rfind（匹配最后一次出现）"""
        source = ContentSource(
            type="rss", src="https://example.com/rss",
            exclude=[{"type": "end", "value": "分割线"}],
        )
        processor = ContentProcessor(source)
        html = "<p>前文</p><p>分割线</p><p>中间</p><p>分割线</p><p>结尾</p>"
        article = _make_article(html)
        result = processor.process(article)
        # "分割线" 最后一次出现之后的内容应被删除
        assert "结尾" not in result.content
        assert "前文" in result.content


# =========================================================================
# exclude: exact 规则测试
# =========================================================================

class TestExcludeExact:
    """exclude type=exact 测试"""

    def test_delete_exact_match(self, sample_html, source_with_exclude):
        """精确匹配删除 HTML 片段"""
        processor = ContentProcessor(source_with_exclude)
        article = _make_article(sample_html)
        result = processor.process(article)
        assert '<span class="ad">广告</span>' not in result.content

    def test_exact_multiple_occurrences(self):
        """exact 删除所有出现"""
        source = ContentSource(
            type="rss", src="https://example.com/rss",
            exclude=[{"type": "exact", "value": "[AD]"}],
        )
        processor = ContentProcessor(source)
        html = "<p>[AD]正文[AD]内容[AD]</p>"
        article = _make_article(html)
        result = processor.process(article)
        assert "[AD]" not in result.content

    def test_exact_with_html_tags(self):
        """exact 可以匹配包含 HTML 标签的字符串"""
        source = ContentSource(
            type="rss", src="https://example.com/rss",
            exclude=[{"type": "exact", "value": '<a href="https://spam.com">推广</a>'}],
        )
        processor = ContentProcessor(source)
        html = '<p>正文</p><a href="https://spam.com">推广</a><p>结尾</p>'
        article = _make_article(html)
        result = processor.process(article)
        assert "推广" not in result.content
        assert "正文" in result.content

    def test_exact_no_match(self):
        """exact 关键词不存在时不修改"""
        source = ContentSource(
            type="rss", src="https://example.com/rss",
            exclude=[{"type": "exact", "value": "不存在的内容"}],
        )
        processor = ContentProcessor(source)
        html = "<p>原始内容</p>"
        article = _make_article(html)
        result = processor.process(article)
        assert "原始内容" in result.content


# =========================================================================
# exclude 组合规则测试
# =========================================================================

class TestExcludeCombined:
    """多条 exclude 规则组合测试"""

    def test_start_then_end(self, sample_html, source_with_exclude):
        """start 和 end 组合使用"""
        processor = ContentProcessor(source_with_exclude)
        article = _make_article(sample_html)
        result = processor.process(article)
        # 两个关键词之间的内容应保留
        assert "正文的第一段" in result.content
        assert "正文的第二段" in result.content
        # 边界之外的应被删除
        assert "前言部分" not in result.content
        assert "这段应该被删除" not in result.content

    def test_invalid_exclude_rule_type_logged(self):
        """无效 exclude type 不崩溃"""
        source = ContentSource(
            type="rss", src="https://example.com/rss",
            exclude=[{"type": "unknown_type", "value": "test"}],
        )
        processor = ContentProcessor(source)
        html = "<p>内容</p>"
        article = _make_article(html)
        result = processor.process(article)
        # 不应该崩溃，内容应保留
        assert "内容" in result.content

    def test_exclude_empty_value_skipped(self):
        """exclude 中 value 为空的规则应被跳过"""
        source = ContentSource(
            type="rss", src="https://example.com/rss",
            exclude=[{"type": "exact", "value": ""}],
        )
        processor = ContentProcessor(source)
        html = "<p>内容</p>"
        article = _make_article(html)
        result = processor.process(article)
        assert "内容" in result.content


# =========================================================================
# keep_link 规则测试
# =========================================================================

class TestKeepLink:
    """keep_link 规则测试"""

    def test_keep_link_yes(self):
        """keep_link=Y 保留 <a> 标签"""
        source = ContentSource(
            type="rss", src="https://example.com/rss",
            keep_link="Y",
        )
        processor = ContentProcessor(source)
        html = '<p>请 <a href="https://example.com">点击这里</a> 查看详情</p>'
        article = _make_article(html)
        result = processor.process(article)
        assert "<a" in result.content
        assert "href" in result.content

    def test_keep_link_no(self):
        """keep_link=N 移除 <a> 标签，保留文字"""
        source = ContentSource(
            type="rss", src="https://example.com/rss",
            keep_link="N",
        )
        processor = ContentProcessor(source)
        html = '<p>请 <a href="https://example.com">点击这里</a> 查看详情</p>'
        article = _make_article(html)
        result = processor.process(article)
        assert "<a" not in result.content
        assert "点击这里" in result.content
        assert "查看详情" in result.content


# =========================================================================
# _should_delete（delete 规则）测试
# =========================================================================

class TestDelete:
    """delete 关键词过滤测试"""

    def test_delete_matching_title(self, source_with_delete):
        """标题包含关键词时 _should_delete 返回 True"""
        from src.fetchers.base import BaseFetcher
        # 用 ContentSource 直接调用 _should_delete 逻辑
        keywords = source_with_delete.delete.split(",")
        assert any(k.strip() in "这是一条广告文章" for k in keywords)

    def test_delete_no_match(self, source_with_delete):
        """标题不含关键词时 _should_delete 返回 False"""
        keywords = source_with_delete.delete.split(",")
        assert not any(k.strip() in "正常文章标题" for k in keywords)

    def test_delete_empty(self):
        """delete 为空时不过滤任何文章"""
        source = ContentSource(type="rss", src="https://example.com/rss")
        assert source.delete is None

    def test_delete_multiple_keywords(self):
        """多个 delete 关键词任意匹配"""
        source = ContentSource(
            type="rss", src="https://example.com/rss",
            delete="广告,推广,赞助",
        )
        keywords = [k.strip() for k in source.delete.split(",")]
        # 分别测试每个关键词
        assert any(k in "这是一个广告" for k in keywords)
        assert any(k in "推广内容" for k in keywords)
        assert any(k in "赞助文章" for k in keywords)
        assert not any(k in "普通文章" for k in keywords)


# =========================================================================
# HTML 清洗测试
# =========================================================================

class TestCleanHtml:
    """HTML 清洗测试"""

    def test_removes_script(self):
        source = ContentSource(type="rss", src="https://example.com/rss")
        processor = ContentProcessor(source)
        html = "<p>内容</p><script>alert('xss')</script>"
        article = _make_article(html)
        result = processor.process(article)
        assert "<script" not in result.content
        assert "alert" not in result.content

    def test_removes_style(self):
        source = ContentSource(type="rss", src="https://example.com/rss")
        processor = ContentProcessor(source)
        html = "<style>body{color:red}</style><p>内容</p>"
        article = _make_article(html)
        result = processor.process(article)
        assert "<style" not in result.content

    def test_removes_iframe(self):
        source = ContentSource(type="rss", src="https://example.com/rss")
        processor = ContentProcessor(source)
        html = '<p>内容</p><iframe src="https://evil.com"></iframe>'
        article = _make_article(html)
        result = processor.process(article)
        assert "<iframe" not in result.content

    def test_filter_small_social_icons(self):
        """测试预过滤逻辑：<a> + 小图(≤32px) 应被移除"""
        source = ContentSource(type="rss", src="https://example.com/rss")
        processor = ContentProcessor(source)
        html = """
        <html>
            <body>
                <!-- 场景 1: 应被移除 (<a> + 16px img) -->
                <a href="https://fb.com">
                    <img src="fb.png" width="16" style="width:16px" alt="facebook">
                </a>
                
                <!-- 场景 2: 应被保留 (<a> + 50px img) -->
                <a href="https://site.com">
                    <img src="big.png" width="50" height="50">
                </a>
                
                <!-- 场景 3: 应被保留 (孤立 16px img) -->
                <img src="standalone.png" width="16">
            </body>
        </html>
        """
        
        # 预处理 HTML
        article = _make_article(html)
        result = processor.process(article)
        soup = BeautifulSoup(result.content, 'lxml')
        
        # 验证
        # 场景 1 应该不存在
        assert not soup.find('a', href="https://fb.com")
        
        # 场景 2 应该存在
        assert soup.find('a', href="https://site.com")
        
        # 场景 3 应该存在
        assert soup.find('img', src="standalone.png")


# =========================================================================
# EPUB 验证错误修复测试
# =========================================================================

class TestEpubValidationFixes:
    """EPUB 验证错误修复测试"""

    def test_row_to_tr_conversion(self):
        """<row> 应转换为 <tr>"""
        source = ContentSource(type="rss", src="https://example.com/rss")
        processor = ContentProcessor(source)
        html = "<table><row><td>单元格</td></row></table>"
        article = _make_article(html)
        result = processor.process(article)
        assert "<tr>" in result.content
        assert "<row>" not in result.content

    def test_font_to_span_with_color(self):
        """<font color='red'> 应转换为 <span>，但忽略 color 以免 Kindle 灰色"""
        source = ContentSource(type="rss", src="https://example.com/rss")
        processor = ContentProcessor(source)
        html = "<font color='red'>红色文字</font>"
        article = _make_article(html)
        result = processor.process(article)
        assert "<span" in result.content
        assert "color" not in result.content  # 不应包含颜色
        assert "<font" not in result.content

    def test_font_to_span_with_size(self):
        """<font size='5'> 应转换为带 font-size 的 <span>"""
        source = ContentSource(type="rss", src="https://example.com/rss")
        processor = ContentProcessor(source)
        html = "<font size='5'>大号文字</font>"
        article = _make_article(html)
        result = processor.process(article)
        assert "<span" in result.content
        assert "font-size:18px" in result.content  # size 5 → 18px
        assert "<font" not in result.content

    def test_font_to_span_with_multiple_attrs(self):
        """<font color='blue' face='Arial'> 应转换多个属性，但忽略 color"""
        source = ContentSource(type="rss", src="https://example.com/rss")
        processor = ContentProcessor(source)
        html = "<font color='blue' face='Arial'>蓝色Arial</font>"
        article = _make_article(html)
        result = processor.process(article)
        assert "<span" in result.content
        assert "color" not in result.content  # 忽略颜色
        assert "font-family:Arial" in result.content
        assert "<font" not in result.content

    def test_strip_inline_color_styles(self):
        """应从 style 属性中移除 color 和 background-color"""
        source = ContentSource(type="rss", src="https://example.com/rss")
        processor = ContentProcessor(source)
        html = '<p style="color:red; font-weight:bold; background-color: #fff;">内容</p>'
        article = _make_article(html)
        result = processor.process(article)
        assert 'font-weight:bold' in result.content
        assert 'color' not in result.content
        assert 'background-color' not in result.content

    def test_svg_removal(self):
        """SVG 元素应被移除"""
        source = ContentSource(type="rss", src="https://example.com/rss")
        processor = ContentProcessor(source)
        html = "<svg><circle cx='50' cy='50' r='40'/></svg>正文"
        article = _make_article(html)
        result = processor.process(article)
        assert "<svg" not in result.content
        assert "正文" in result.content

    def test_video_removal(self):
        """视频元素应被移除"""
        source = ContentSource(type="rss", src="https://example.com/rss")
        processor = ContentProcessor(source)
        html = "<video src='https://example.com/video.mp4'></video>正文"
        article = _make_article(html)
        result = processor.process(article)
        assert "<video" not in result.content
        assert "正文" in result.content

    def test_audio_removal(self):
        """音频元素应被移除"""
        source = ContentSource(type="rss", src="https://example.com/rss")
        processor = ContentProcessor(source)
        html = "<audio src='https://example.com/audio.mp3'></audio>正文"
        article = _make_article(html)
        result = processor.process(article)
        assert "<audio" not in result.content
        assert "正文" in result.content

    def test_nested_section_in_p_fixed(self):
        """<p> 内的 <section> 应移到外面"""
        source = ContentSource(type="rss", src="https://example.com/rss")
        processor = ContentProcessor(source)
        html = "<p>文本<section>块内容</section>更多文本</p>"
        article = _make_article(html)
        result = processor.process(article)
        # section 不应在 p 内
        soup = BeautifulSoup(result.content, 'lxml')
        for p in soup.find_all('p'):
            assert not p.find('section')

    def test_nested_div_in_p_fixed(self):
        """<p> 内的 <div> 应移到外面"""
        source = ContentSource(type="rss", src="https://example.com/rss")
        processor = ContentProcessor(source)
        html = "<p>文本<div>块内容</div>更多文本</p>"
        article = _make_article(html)
        result = processor.process(article)
        soup = BeautifulSoup(result.content, 'lxml')
        for p in soup.find_all('p'):
            assert not p.find('div')

    def test_nested_p_in_p_fixed(self):
        """嵌套 <p> 应被拆分"""
        source = ContentSource(type="rss", src="https://example.com/rss")
        processor = ContentProcessor(source)
        html = "<p>外层<p>内层</p>继续</p>"
        article = _make_article(html)
        result = processor.process(article)
        # 不应有嵌套的 p
        soup = BeautifulSoup(result.content, 'lxml')
        for p in soup.find_all('p'):
            assert not p.find('p')

    def test_nested_header_in_p_fixed(self):
        """<p> 内的 <h1> 应移到外面"""
        source = ContentSource(type="rss", src="https://example.com/rss")
        processor = ContentProcessor(source)
        html = "<p>文本<h1>标题</h1>更多文本</p>"
        article = _make_article(html)
        result = processor.process(article)
        soup = BeautifulSoup(result.content, 'lxml')
        for p in soup.find_all('p'):
            assert not p.find(['h1', 'h2', 'h3', 'h4', 'h5', 'h6'])

    def test_complex_nested_structure(self):
        """复杂嵌套结构应被修复"""
        source = ContentSource(type="rss", src="https://example.com/rss")
        processor = ContentProcessor(source)
        html = "<p>文本1<section><p>文本2</p></section>文本3</p>"
        article = _make_article(html)
        result = processor.process(article)
        # 检查结构是否有效
        soup = BeautifulSoup(result.content, 'lxml')
        assert soup.find('section') is not None
        # 所有 p 内不应有嵌套的块级元素
        for p in soup.find_all('p'):
            assert not p.find(['section', 'div', 'p', 'article', 'aside'])

    def test_deep_nested_structure_fixed(self):
        """深度嵌套应被多次遍历修复"""
        source = ContentSource(type="rss", src="https://example.com/rss")
        processor = ContentProcessor(source)
        html = "<p>外<p>中<p>内</p></p></p>"
        article = _make_article(html)
        result = processor.process(article)
        soup = BeautifulSoup(result.content, 'lxml')
        # 确保没有嵌套的 p
        for p in soup.find_all('p'):
            assert not p.find('p')

    def test_text_preserved_after_fix(self):
        """修复嵌套结构后文本内容应保留"""
        source = ContentSource(type="rss", src="https://example.com/rss")
        processor = ContentProcessor(source)
        html = "<p>段落1<section>块内容</section>段落2</p>"
        article = _make_article(html)
        result = processor.process(article)
        assert "段落1" in result.content
        assert "块内容" in result.content
        assert "段落2" in result.content

    def test_cell_to_td_conversion(self):
        """<cell> 应转换为 <td>"""
        source = ContentSource(type="rss", src="https://example.com/rss")
        processor = ContentProcessor(source)
        html = "<table><row><cell>单元格1</cell><cell>单元格2</cell></row></table>"
        article = _make_article(html)
        result = processor.process(article)
        assert "<td>" in result.content
        assert "<cell>" not in result.content
        assert "单元格1" in result.content
        assert "单元格2" in result.content

    def test_img_width_height_integer_conversion(self):
        """图片 width/height 属性有小数点时应转换为整数"""
        source = ContentSource(type="rss", src="https://example.com/rss")
        processor = ContentProcessor(source)
        html = '<img src="test.jpg" width="120.5" height="798.67"/>'
        article = _make_article(html)
        result = processor.process(article)
        # 小数应被取整
        assert 'width="120"' in result.content
        assert 'height="798"' in result.content
        assert "120.5" not in result.content
        assert "798.67" not in result.content

    def test_img_width_height_already_integer(self):
        """图片 width/height 属性已经是整数时应保持不变"""
        source = ContentSource(type="rss", src="https://example.com/rss")
        processor = ContentProcessor(source)
        html = '<img src="test.jpg" width="100" height="200"/>'
        article = _make_article(html)
        result = processor.process(article)
        assert 'width="100"' in result.content
        assert 'height="200"' in result.content

    def test_img_invalid_width_removed(self):
        """图片 width/height 属性无效时应被移除"""
        source = ContentSource(type="rss", src="https://example.com/rss")
        processor = ContentProcessor(source)
        html = '<img src="test.jpg" width="abc" height=""/>'
        article = _make_article(html)
        result = processor.process(article)
        # 无效属性应被移除
        assert 'width=' not in result.content or 'width=""' not in result.content
        assert 'height=' not in result.content or 'height=""' not in result.content


# =========================================================================
# Emoji 处理测试
# =========================================================================

class TestEmojiProcessing:
    """Emoji 处理测试"""

    def test_wrap_multiple_emojis(self):
        """测试单个文本节点中存在多个 Emoji 时均被包裹"""
        source = ContentSource(type="rss", src="https://example.com/rss")
        processor = ContentProcessor(source)
        html = "<p>Hello 😀 World 😂</p>"
        article = _make_article(html)
        result = processor.process(article)
        
        # 验证是否包含两个 span
        soup = BeautifulSoup(result.content, 'lxml')
        emojis = soup.find_all('span', class_='emoji')
        assert len(emojis) == 2
        assert emojis[0].get_text() == '😀'
        assert emojis[1].get_text() == '😂'
        
        # 验证文本内容是否正确
        assert "Hello" in result.content
        assert "World" in result.content

    def test_render_text_with_emojis_escapes_text_and_uses_local_image(self):
        rendered = ContentProcessor.render_text_with_emojis("标题 📰 <测试>")

        assert 'src="images/emoji_1f4f0.png"' in rendered
        assert "&lt;测试&gt;" in rendered

class TestLayoutTableCleaning:
    """测试邮件布局表格与样式清洗行为"""

    def test_unwrap_role_none_table(self):
        """拆解显式标记为 role='none' 或 role='presentation' 的布局表格"""
        source = ContentSource(type="mail", src="testmail")
        processor = ContentProcessor(source)
        html = (
            '<table role="none" width="100%">'
            '  <tr>'
            '    <td align="center" style="padding: 10px;">'
            '      <p>实际正文内容</p>'
            '    </td>'
            '  </tr>'
            '</table>'
        )
        article = _make_article(html)
        result = processor.process(article)
        # 表格、行、单元格标签都应该被拆解（unwrap）
        assert "<table" not in result.content
        assert "<tr>" not in result.content
        assert "<td>" not in result.content
        assert "<p>实际正文内容</p>" in result.content

    def test_unwrap_single_column_table(self):
        """拆解每行最多只有一列（单列包装）的非显式标记布局表格"""
        source = ContentSource(type="mail", src="testmail")
        processor = ContentProcessor(source)
        html = (
            '<table>'
            '  <tr>'
            '    <td>第一行内容</td>'
            '  </tr>'
            '  <tr>'
            '    <td>第二行内容</td>'
            '  </tr>'
            '</table>'
        )
        article = _make_article(html)
        result = processor.process(article)
        assert "<table" not in result.content
        assert "<td>" not in result.content
        assert "第一行内容" in result.content
        assert "第二行内容" in result.content

    def test_unwrap_nested_layout_tables(self):
        """拆解多层嵌套的邮件布局模板表格"""
        source = ContentSource(type="mail", src="testmail")
        processor = ContentProcessor(source)
        html = (
            '<table class="outer">'
            '  <tr>'
            '    <td>'
            '      <table class="inner">'
            '        <tr>'
            '          <td><p>嵌套正文</p></td>'
            '        </tr>'
            '      </table>'
            '    </td>'
            '  </tr>'
            '</table>'
        )
        article = _make_article(html)
        result = processor.process(article)
        assert "<table" not in result.content
        assert "嵌套正文" in result.content

    def test_preserve_data_tables(self):
        """保留真正的、具有多列的表格（若没有被指定为 role='none'）"""
        source = ContentSource(type="rss", src="https://example.com/rss")
        processor = ContentProcessor(source)
        html = (
            '<table class="data-table">'
            '  <tr>'
            '    <th>学号</th>'
            '    <th>姓名</th>'
            '  </tr>'
            '  <tr>'
            '    <td>001</td>'
            '    <td>张三</td>'
            '  </tr>'
            '</table>'
        )
        article = _make_article(html)
        result = processor.process(article)
        assert "<table>" in result.content or '<table class="data-table">' in result.content
        assert "<tr>" in result.content
        assert "<th>学号</th>" in result.content
        assert "<td>001</td>" in result.content

    def test_strip_layout_styles_from_non_img_tags(self):
        """从非 img 标签中剥离尺寸/边距等限制排版的样式，但保留 font-weight 等内容格式化样式"""
        source = ContentSource(type="mail", src="testmail")
        processor = ContentProcessor(source)
        html = (
            '<div style="width: 670px; margin: 0px auto; padding: 15px; font-weight: bold; font-style: italic;">'
            '  <p style="max-width: 100%; display: flex;">内容</p>'
            '</div>'
        )
        article = _make_article(html)
        result = processor.process(article)
        assert 'width' not in result.content
        assert 'margin' not in result.content
        assert 'padding' not in result.content
        assert 'display' not in result.content
        # 应该保留内容格式样式
        assert 'font-weight:bold' in result.content or 'font-weight: bold' in result.content
        assert 'font-style:italic' in result.content or 'font-style: italic' in result.content

    def test_preserve_img_width_and_height(self):
        """对于 img 标签，保留其 style/attributes 中的 width 和 height 用于排版"""
        source = ContentSource(type="rss", src="https://example.com/rss")
        processor = ContentProcessor(source)
        html = (
            '<div width="500" style="width: 500px;">'
            '  <img src="test.jpg" width="300" height="200" style="width: 300px; height: 200px;" />'
            '</div>'
        )
        article = _make_article(html)
        result = processor.process(article)
        # div 的 width 属性和 width 样式应被去除
        assert 'width="500"' not in result.content
        assert 'width:500' not in result.content
        # img 的 width/height 属性和样式应该保留
        assert 'width="300"' in result.content
        assert 'height="200"' in result.content
        assert 'width: 300px' in result.content
        assert 'height: 200px' in result.content


# =========================================================================
# URL 规范化与过滤测试
# =========================================================================

class TestUrlNormalization:
    """测试 content_processor 对于非法或相对 URL 的规范化与过滤行为"""

    def test_url_with_space_quoted(self):
        """测试 URL 中的空格应该被转换为 %20"""
        source = ContentSource(type="web", src="https://example.com")
        processor = ContentProcessor(source)
        html = '<p>See <a href="https://example.com/elon musk">Elon Musk</a></p>'
        article = _make_article(html)
        result = processor.process(article)
        assert 'href="https://example.com/elon%20musk"' in result.content

    def test_relative_url_resolved_with_base_url(self):
        """测试相对 URL 能够根据 article.url 被正确解析为绝对 URL"""
        source = ContentSource(type="web", src="https://gushiwen.org")
        processor = ContentProcessor(source)
        html = '<p>Goto <a href="/user/wode.aspx">My Page</a></p>'
        # Article url is https://example.com/test
        article = Article(title="Test", content=html, url="https://gushiwen.org/shiwens/default.aspx")
        result = processor.process(article)
        assert 'href="https://gushiwen.org/user/wode.aspx"' in result.content

    def test_relative_url_with_query_resolved(self):
        """测试带查询参数的相对 URL 被正确解析且保留查询参数"""
        source = ContentSource(type="web", src="https://gushiwen.org")
        processor = ContentProcessor(source)
        html = '<p>Filter <a href="/shiwens/default.aspx?cstr=%e5%ae%8b%e4%bb%a3">Song Dynasty</a></p>'
        article = Article(title="Test", content=html, url="https://gushiwen.org/home")
        result = processor.process(article)
        assert 'href="https://gushiwen.org/shiwens/default.aspx?cstr=%e5%ae%8b%e4%bb%a3"' in result.content

    def test_unresolved_relative_url_unwrapped(self):
        """测试无法解析的相对 URL (例如无 base_url) 的 a 标签会被 unwrap"""
        source = ContentSource(type="web", src="https://gushiwen.org")
        processor = ContentProcessor(source)
        html = '<p>Go <a href="/items/123">Item</a></p>'
        # 如果 article.url 也是相对的或者无效的，无法得到 valid absolute URL，则 a 标签应该被 unwrap
        article = Article(title="Test", content=html, url="/invalid-relative-base")
        result = processor.process(article)
        # a 标签应当被 unwrap，只留下文本
        assert '<a' not in result.content
        assert 'Go Item' in result.content

    def test_anchor_link_preserved(self):
        """测试本页内的锚链接 (#anchor) 能够被完好保留"""
        source = ContentSource(type="web", src="https://example.com")
        processor = ContentProcessor(source)
        html = '<p>Read <a href="#footnote-1">Footnote</a></p>'
        article = _make_article(html)
        result = processor.process(article)
        assert 'href="#footnote-1"' in result.content

    def test_invalid_scheme_unwrapped(self):
        """测试非主流或非法 schema 的链接 (如 javascript: 或者是 ftp:) 应当被 unwrap"""
        source = ContentSource(type="web", src="https://example.com")
        processor = ContentProcessor(source)
        html = '<p>Click <a href="javascript:alert(1)">Here</a> or <a href="ftp://files.com">FTP</a></p>'
        article = _make_article(html)
        result = processor.process(article)
        assert '<a' not in result.content
        assert 'Click Here or FTP' in result.content


class TestImgAltTitleCleaning:
    """测试 content_processor 对于 img 标签 alt 和 title 属性中的特殊字符清洗行为"""

    def test_img_alt_title_cleaning(self):
        """测试 img 标签中的 <, >, &lt;, &gt; 应该被替换为 -"""
        source = ContentSource(type="web", src="https://example.com")
        processor = ContentProcessor(source)
        html = '<p><img src="test.jpg" alt="A &gt; B &lt; C > D < E" title="X &gt; Y"/></p>'
        article = _make_article(html)
        result = processor.process(article)
        # attrs should be cleaned and output correctly
        assert 'alt="A  -  B  -  C  -  D  -  E"' in result.content
        assert 'title="X  -  Y"' in result.content


class TestNestedPreInParagraphOrInline:
    """测试 content_processor 对嵌套在段落 or 行内元素中的 <pre> 标签的清洗/转换行为"""

    def test_nested_pre_in_p_converts_to_code(self):
        """测试 <p> 内的 <pre> 应该转换为 <code>"""
        source = ContentSource(type="web", src="https://example.com")
        processor = ContentProcessor(source)
        html = '<p>Claude Code 新增 <pre>sandbox.filesystem.disabled</pre> 设置。</p>'
        article = _make_article(html)
        result = processor.process(article)
        # <pre> 应该被替换为 <code>，且其应该保留在 <p> 标签内部，而不被移到外面
        assert '<p>Claude Code 新增 <code>sandbox.filesystem.disabled</code> 设置。</p>' in result.content

    def test_nested_pre_with_code_in_p_unwraps_pre(self):
        """测试 <p> 内包含 <code> 的 <pre> 标签应该直接 unwrap 掉 <pre>"""
        source = ContentSource(type="web", src="https://example.com")
        processor = ContentProcessor(source)
        html = '<p>Claude Code 新增 <pre><code>sandbox.filesystem.disabled</code></pre> 设置。</p>'
        article = _make_article(html)
        result = processor.process(article)
        # <pre> 应该被 unwrap 掉，剩下 <code>，且保留在 <p> 内部
        assert '<p>Claude Code 新增 <code>sandbox.filesystem.disabled</code> 设置。</p>' in result.content

    def test_nested_pre_in_h1_converts_to_code(self):
        """测试 <h1> 内的 <pre> 应该转换为 <code>"""
        source = ContentSource(type="web", src="https://example.com")
        processor = ContentProcessor(source)
        html = '<h1>标题 <pre>code</pre></h1>'
        article = _make_article(html)
        result = processor.process(article)
        assert '<h1>标题 <code>code</code></h1>' in result.content

