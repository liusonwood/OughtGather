"""
EPUB合规性测试 - 专门测试EPUB生成是否符合规范
运行：python -m pytest tests/test_epub_compliance.py -v

这个测试文件专门验证EPUB生成的合规性，包括：
- EPUB文件结构（目录、路径）
- OPF文件内容（version、manifest、spine、nav属性）
- 必需元素（nav document、NCX）
- XHTML文件格式（DOCTYPE）
- CSS转义问题
- 封面文件非空
- EPUBCheck验证（如果可用）

优化：使用fixture在类级别共享EPUB，避免每个测试重复生成
"""

import os
import zipfile
import xml.etree.ElementTree as ET
from unittest.mock import patch, MagicMock
import pytest
import subprocess
import shutil

from src.config import ContentSource, _parse_config
from src.fetchers.base import Article, FetchResult
from src.epub.generator import EPUBGenerator


# =========================================================================
# Fixture：生成一次EPUB，供整个测试会话共享使用
# =========================================================================

@pytest.fixture(scope="session")
def shared_epub(request, tmp_path_factory):
    """
    在整个测试会话级别生成一次EPUB文件，供所有测试类及方法共享

    使用方法：在测试方法中添加参数 `shared_epub`，fixture会自动传入EPUB路径
    """
    # 生成EPUB
    config_data = {
        "title": {"text": "EPUB合规测试", "img": ""},
        "body": [
            {"type": "rss", "src": "https://example.com/rss", "priority": 10}
        ]
    }
    config = _parse_config(config_data)
    generator = EPUBGenerator(config)

    source = ContentSource(type="rss", src="https://example.com/rss", priority=10)
    articles = [
        Article(title="测试文章", content="<p>内容</p>", url="https://example.com/1"),
        Article(title="测试&符号", content="<p>内容</p>", url="https://example.com/2"),
    ]
    results = [FetchResult(source=source, articles=articles)]

    epub_path = generator.generate(results)

    # 返回路径供测试使用
    yield epub_path

    # 测试类结束后清理
    if os.path.exists(epub_path):
        os.remove(epub_path)


class TestEpubStructure:
    """测试EPUB文件结构是否符合规范"""

    def test_epub_directory_structure(self, shared_epub):
        """测试EPUB使用标准EPUB目录，不使用绝对路径"""
        with zipfile.ZipFile(shared_epub, 'r') as zf:
            files = zf.namelist()

            # 检查没有绝对路径（以/开头的文件）
            absolute_paths = [f for f in files if f.startswith('/')]
            assert len(absolute_paths) == 0, f"发现绝对路径文件：{absolute_paths}，违反OCF规范"

            # 检查标准目录结构
            assert 'mimetype' in files, "缺少mimetype文件"
            assert 'META-INF/container.xml' in files, "缺少container.xml"

            # 检查EPUB目录存在
            epub_files = [f for f in files if f.startswith('EPUB/')]
            assert len(epub_files) > 0, "缺少EPUB目录"

            print(f"✓ EPUB使用标准目录结构，共{len(files)}个文件")

    def test_opf_version_is_3_0(self, shared_epub):
        """测试OPF文件声明version='3.0'（ebooklib硬编码）"""
        with zipfile.ZipFile(shared_epub, 'r') as zf:
            opf_content = zf.read('EPUB/content.opf')
            root = ET.fromstring(opf_content)

            # 检查version属性
            version = root.get('version')
            assert version == '3.0', f"OPF version应为'3.0'，实际为'{version}'"

            print(f"✓ OPF声明version='3.0'")

    def test_opf_has_nav_property(self, shared_epub):
        """测试OPF manifest中有一个item声明nav属性（EPUB 3.0必需）"""
        with zipfile.ZipFile(shared_epub, 'r') as zf:
            opf_content = zf.read('EPUB/content.opf')
            root = ET.fromstring(opf_content)

            # 查找manifest中的nav item
            manifest = root.find('.//{*}manifest')
            nav_items = []
            for item in manifest.findall('.//{*}item'):
                properties = item.get('properties', '')
                if 'nav' in properties:
                    nav_items.append(item.get('id'))

            assert len(nav_items) == 1, f"应有1个nav item，实际{len(nav_items)}个：{nav_items}"

            print(f"✓ OPF manifest中有nav属性声明")

    def test_opf_has_cover_image_property(self, shared_epub):
        """测试OPF manifest中封面图片声明了cover-image属性（EPUB 3.0用于识别封面）"""
        with zipfile.ZipFile(shared_epub, 'r') as zf:
            opf_content = zf.read('EPUB/content.opf')
            root = ET.fromstring(opf_content)

            # 查找manifest中的cover-image item
            manifest = root.find('.//{*}manifest')
            cover_image_items = []
            for item in manifest.findall('.//{*}item'):
                properties = item.get('properties', '')
                if 'cover-image' in properties:
                    cover_image_items.append(item.get('id'))

            assert len(cover_image_items) == 1, f"应有1个cover-image item，实际{len(cover_image_items)}个：{cover_image_items}"

            print(f"✓ OPF manifest中有cover-image属性声明")

    def test_epub_has_ncx_file(self, shared_epub):
        """测试EPUB包含NCX导航文件（向后兼容），且首个navPoint指向contents.xhtml"""
        with zipfile.ZipFile(shared_epub, 'r') as zf:
            files = zf.namelist()

            # 检查NCX文件存在
            ncx_files = [f for f in files if 'toc.ncx' in f]
            assert len(ncx_files) >= 1, "缺少NCX导航文件"

            # 检查NCX首项指向contents.xhtml
            ncx_content = zf.read('EPUB/toc.ncx')
            root = ET.fromstring(ncx_content)
            first_content = root.find('.//{*}navPoint/{*}content')
            assert first_content is not None, "NCX应包含navPoint/content"
            assert first_content.get('src') == 'contents.xhtml', f"NCX首个navPoint应为contents.xhtml，实际为'{first_content.get('src')}'"

            print(f"✓ EPUB包含NCX导航文件且首个navPoint指向contents.xhtml")

    def test_epub_has_nav_document(self, shared_epub):
        """测试EPUB包含nav.xhtml导航文档（EPUB 3.0必需）"""
        with zipfile.ZipFile(shared_epub, 'r') as zf:
            files = zf.namelist()

            # 检查nav.xhtml文件存在
            nav_files = [f for f in files if 'nav.xhtml' in f]
            assert len(nav_files) >= 1, "缺少nav.xhtml导航文档（EPUB 3.0必需）"

            print(f"✓ EPUB包含nav.xhtml导航文档")


class TestEpubContent:
    """测试EPUB内容格式是否符合规范"""

    def _read_epub_xhtml(self, epub_path, file_name):
        """读取EPUB内的XHTML文件内容"""
        with zipfile.ZipFile(epub_path, 'r') as zf:
            try:
                return zf.read(f'EPUB/{file_name}').decode('utf-8')
            except KeyError:
                return zf.read(file_name).decode('utf-8')

    def test_nav_has_landmarks_hidden(self, shared_epub):
        """测试nav.xhtml包含landmarks且设置为hidden（EPUB 3标准地标导航，仅供阅读器内部跳转使用）"""
        nav_html = self._read_epub_xhtml(shared_epub, 'nav.xhtml')

        # landmarks 是 EPUB 3 导航文档的标准组成部分，hidden 属性使其不在阅读器目录中显示
        # Kindle 根据 landmarks 中的 bodymatter 条目决定"打开时跳转到哪里"
        assert 'epub:type="landmarks"' in nav_html, "nav.xhtml应包含landmarks地标导航（EPUB 3标准）"
        assert 'hidden=""' in nav_html or 'hidden' in nav_html, "landmarks应设置为hidden以在目录中隐藏"
        assert '<h2>Landmarks</h2>' not in nav_html, "nav.xhtml不应该包含Landmarks标题（地标区域无可见标题）"

        # 验证 landmarks 内部包含 cover, toc 和 bodymatter 条目
        assert 'epub:type="cover" href="cover.xhtml"' in nav_html, \
            "landmarks应包含epub:type='cover'指向cover.xhtml"
        assert 'epub:type="toc" href="contents.xhtml"' in nav_html, \
            "landmarks应包含epub:type='toc'指向contents.xhtml"
        assert 'epub:type="bodymatter" href="contents.xhtml"' in nav_html, \
            "landmarks应包含epub:type='bodymatter'指向contents.xhtml（Kindle打开时落在目录页）"
        assert "{self.translator(" not in nav_html

        print(f"✓ nav.xhtml包含hidden的landmarks地标导航（cover+toc+bodymatter配置正确，Kindle兼容）")

    def test_chapter_has_doctype(self, shared_epub):
        """测试章节XHTML包含DOCTYPE声明"""
        chapter_html = self._read_epub_xhtml(shared_epub, 'chapter_0.xhtml')

        # 检查DOCTYPE声明
        assert '<!DOCTYPE' in chapter_html, "章节XHTML应包含DOCTYPE声明"

        print(f"✓ 章节XHTML包含DOCTYPE声明")

    def test_chapter_has_xhtml_namespace(self, shared_epub):
        """测试章节XHTML包含正确的命名空间"""
        chapter_html = self._read_epub_xhtml(shared_epub, 'chapter_0.xhtml')

        # 检查XHTML命名空间
        assert 'xmlns="http://www.w3.org/1999/xhtml"' in chapter_html, "应包含XHTML命名空间"

        print(f"✓ 章节XHTML包含正确的命名空间")

    def test_html_entities_escaped_in_title(self, shared_epub):
        """测试标题中的HTML特殊字符被转义"""
        # 检查第二个章节（标题包含&符号）
        chapter_html = self._read_epub_xhtml(shared_epub, 'chapter_1.xhtml')

        # 未转义的&不应出现（应该被转义为&amp;）
        # 注意：在XML/HTML中，单独的&是非法的，必须转义
        # 但在文本内容中可能出现，我们的代码应该转义标题
        if '测试&符号' in chapter_html:
            # 如果标题未转义，至少要确保不是裸的&
            # 正确的做法是转义为&amp;
            assert '&amp;' in chapter_html or '&符号' not in chapter_html, "&符号应被转义"

        print(f"✓ HTML特殊字符正确转义")

    def test_default_css_contains_toc_styles(self, shared_epub):
        """测试外部样式表default.css包含了目录/大章节/小章节的排版样式定义，支持样式被完全剥离的情况"""
        css_content = self._read_epub_xhtml(shared_epub, 'style/default.css')

        # 验证包含 #toc 和 section-link 等样式
        assert '#toc' in css_content, "default.css应该定义目录专属样式 #toc"
        assert '.section-link' in css_content, "default.css应该定义大章节样式 .section-link"
        assert '.article-link' in css_content, "default.css应该定义文章链接样式 .article-link"
        assert '!important' in css_content, "default.css中的TOC样式应使用!important提高特异性"

        print(f"✓ default.css中成功包含了目录相关的强特异性排版规则")

    def test_default_css_contains_code_styles(self, shared_epub):
        """测试外部样式表default.css包含了行内代码和代码块样式定义"""
        css_content = self._read_epub_xhtml(shared_epub, 'style/default.css')

        # 验证包含 code, pre, 和 pre code 样式
        assert 'code {' in css_content, "default.css应该定义行内代码样式 code"
        assert 'pre {' in css_content, "default.css应该定义代码块容器样式 pre"
        assert 'pre code {' in css_content, "default.css应该定义代码块内容样式 pre code"
        assert 'display: inline !important' in css_content, "code 样式应该显式声明为 display: inline !important"
        assert 'white-space: normal' in css_content, "code 样式应该声明 white-space: normal 以合并多余换行"

        print(f"✓ default.css中成功包含了行内代码和代码块相关的排版规则")


class TestEpubSpine:
    """测试EPUB spine（阅读顺序）是否符合规范"""

    def _get_spine_order(self, epub_path):
        """获取spine中的文件顺序"""
        with zipfile.ZipFile(epub_path, 'r') as zf:
            opf_content = zf.read('EPUB/content.opf')
            root = ET.fromstring(opf_content)

            spine_items = []
            manifest = root.find('.//{*}manifest')

            for itemref in root.findall('.//{*}spine/{*}itemref'):
                idref = itemref.get('idref')
                # 查找对应的href
                for item in manifest.findall('.//{*}item'):
                    if item.get('id') == idref:
                        spine_items.append(item.get('href'))
                        break

            return spine_items

    def test_spine_starts_with_cover(self, shared_epub):
        """测试spine以封面 (cover.xhtml) 和视觉目录 (contents.xhtml) 开始"""
        spine = self._get_spine_order(shared_epub)
        assert spine[0] == 'cover.xhtml', f"spine应以cover.xhtml开始，实际为{spine[0]}"
        assert spine[1] == 'contents.xhtml', f"spine第二位应为contents.xhtml，实际为{spine[1]}"

        print(f"✓ spine以封面+目录开始")

    def test_spine_excludes_nav(self, shared_epub):
        """测试spine不包含nav.xhtml（它是非线性导航，不需要在 spine 中）"""
        spine = self._get_spine_order(shared_epub)
        assert 'nav.xhtml' not in spine, f"spine不应包含nav.xhtml，实际为{spine}"

        print(f"✓ spine不包含nav.xhtml")

    def test_spine_order_correct(self, shared_epub):
        """测试spine顺序正确：cover → contents → chapters"""
        spine = self._get_spine_order(shared_epub)

        # 验证顺序
        assert spine[0] == 'cover.xhtml', "第一位应为封面页"
        assert spine[1] == 'contents.xhtml', "第二位应为视觉目录"

        # 后续应为章节（包括divider）
        chapters_in_spine = [f for f in spine if f.startswith('chapter_')]
        assert len(chapters_in_spine) >= 1, f"应有章节，实际{len(chapters_in_spine)}个"

        print(f"✓ spine顺序正确：{' → '.join(spine[:5])}")


class TestEpubMetadata:
    """测试EPUB元数据是否符合规范"""

    def test_opf_has_unique_identifier(self, shared_epub):
        """测试OPF包含unique-identifier属性"""
        with zipfile.ZipFile(shared_epub, 'r') as zf:
            opf_content = zf.read('EPUB/content.opf')
            root = ET.fromstring(opf_content)

            unique_id = root.get('unique-identifier')
            assert unique_id, "OPF应包含unique-identifier属性"

            print(f"✓ OPF包含unique-identifier属性")

    def test_metadata_has_required_fields(self, shared_epub):
        """测试元数据包含必需字段（title, identifier, language）"""
        with zipfile.ZipFile(shared_epub, 'r') as zf:
            opf_content = zf.read('EPUB/content.opf')
            root = ET.fromstring(opf_content)

            # 检查title
            titles = root.findall('.//{*}title')
            assert len(titles) >= 1, "元数据应包含title"

            # 检查identifier
            identifiers = root.findall('.//{*}identifier')
            assert len(identifiers) >= 1, "元数据应包含identifier"

            # 检查language
            languages = root.findall('.//{*}language')
            assert len(languages) >= 1, "元数据应包含language"

            print(f"✓ 元数据包含所有必需字段")

    def test_opf_has_guide_with_toc_and_cover(self, shared_epub):
        """测试OPF包含guide元素并引用了封面、目录和正文起点（增加设备兼容性，指定起始页）"""
        with zipfile.ZipFile(shared_epub, 'r') as zf:
            opf_content = zf.read('EPUB/content.opf')
            root = ET.fromstring(opf_content)

            # 查找guide元素
            guide = root.find('.//{*}guide')
            assert guide is not None, "OPF应包含guide元素"

            # 查找封面引用 (cover)
            cover_ref = guide.find('.//{*}reference[@type="cover"]')
            assert cover_ref is not None, "guide应包含type='cover'的引用"
            assert cover_ref.get('href') == 'cover.xhtml', f"封面引用href应为'cover.xhtml'，实际为'{cover_ref.get('href')}'"

            # 查找目录引用 (toc)
            # toc 指向 nav.xhtml，避免 contents.xhtml 被 Kindle 识别为 frontmatter 跳过
            toc_ref = guide.find('.//{*}reference[@type="toc"]')
            assert toc_ref is not None, "guide应包含type='toc'的引用"
            assert toc_ref.get('href') == 'nav.xhtml', f"目录引用href应为'nav.xhtml'，实际为'{toc_ref.get('href')}'"

            # 查找正文起始引用 (text / start)
            text_ref = guide.find('.//{*}reference[@type="text"]')
            assert text_ref is not None, "guide应包含type='text'的引用"
            assert text_ref.get('href') == 'contents.xhtml', f"text引用href应为'contents.xhtml'，实际为'{text_ref.get('href')}'"

            start_ref = guide.find('.//{*}reference[@type="start"]')
            assert start_ref is not None, "guide应包含type='start'的引用"
            assert start_ref.get('href') == 'contents.xhtml', f"start引用href应为'contents.xhtml'，实际为'{start_ref.get('href')}'"

            print(f"✓ OPF包含正确的guide(cover/toc/text/start)元素，cover指向cover.xhtml，toc指向nav.xhtml，text/start指向contents.xhtml")

    def test_language_defaults_to_english_locale(self, shared_epub):
        """测试未设置环境变量时默认使用英文 locale"""
        with zipfile.ZipFile(shared_epub, 'r') as zf:
            opf_content = zf.read('EPUB/content.opf')
            root = ET.fromstring(opf_content)

            languages = root.findall('.//{*}language')
            assert len(languages) >= 1, "应包含language字段"

            lang_value = languages[0].text
        assert lang_value == 'en-US', f"默认语言应为'en-US'，实际为'{lang_value}'"

        print(f"✓ 默认语言设置为 en-US（英文）")


class TestContainerXml:
    """测试META-INF/container.xml是否符合规范"""

    def test_container_xml_points_to_opf(self, shared_epub):
        """测试container.xml正确指向OPF文件"""
        with zipfile.ZipFile(shared_epub, 'r') as zf:
            container_xml = zf.read('META-INF/container.xml')
            root = ET.fromstring(container_xml)

            # 查找rootfile元素
            rootfiles = root.findall('.//{*}rootfile')
            assert len(rootfiles) >= 1, "container.xml应包含rootfile元素"

            # 检查full-path属性
            full_path = rootfiles[0].get('full-path')
            assert full_path == 'EPUB/content.opf', f"full-path应为'EPUB/content.opf'，实际为'{full_path}'"

            print(f"✓ container.xml正确指向EPUB/content.opf")

    def test_container_xml_no_absolute_path(self, shared_epub):
        """测试container.xml中的路径不是绝对路径"""
        with zipfile.ZipFile(shared_epub, 'r') as zf:
            container_xml = zf.read('META-INF/container.xml')
            root = ET.fromstring(container_xml)

            rootfiles = root.findall('.//{*}rootfile')
            full_path = rootfiles[0].get('full-path')

            # 绝对路径以/开头
            assert not full_path.startswith('/'), f"full-path不应为绝对路径：'{full_path}'"

            print(f"✓ container.xml使用相对路径")


class TestMimetype:
    """测试mimetype文件是否符合规范"""

    def test_mimetype_correct(self, shared_epub):
        """测试mimetype文件内容正确"""
        with zipfile.ZipFile(shared_epub, 'r') as zf:
            mimetype = zf.read('mimetype').decode('utf-8')
            assert mimetype == 'application/epub+zip', f"mimetype应为'application/epub+zip'，实际为'{mimetype}'"

            print(f"✓ mimetype正确")

    def test_mimetype_first_in_zip(self, shared_epub):
        """测试mimetype是ZIP中的第一个文件"""
        with zipfile.ZipFile(shared_epub, 'r') as zf:
            # mimetype必须在第一位且未压缩
            first_file = zf.namelist()[0]
            assert first_file == 'mimetype', f"第一个文件应为'mimetype'，实际为'{first_file}'"

            print(f"✓ mimetype是ZIP中的第一个文件")


class TestEpubcheck:
    """使用 W3C epubcheck 工具验证生成的 EPUB 是否符合 EPUB 3 标准"""

    def setup_method(self, method):
        """检查 epubcheck 是否可用，不可用则跳过并提示"""
        if not shutil.which("java"):
            pytest.skip("⚠ 未找到 Java 命令，请先安装 Java")

        try:
            res = subprocess.run(["java", "-version"], capture_output=True, text=True, timeout=5)
            if res.returncode != 0 or "Unable to locate a Java Runtime" in res.stderr:
                pytest.skip(f"⚠ Java 运行时不可用，跳过 epubcheck 测试: {res.stderr.strip()}")
        except Exception as e:
            pytest.skip(f"⚠ 无法运行 Java，跳过 epubcheck 测试: {e}")

        jar = self._epubcheck_jar()
        if not os.path.exists(jar):
            pytest.skip(f"⚠ 未找到 {jar}，请参考 README 配置 epubcheck")

    @staticmethod
    def _epubcheck_jar():
        """返回 epubcheck.jar 路径（项目根目录下）"""
        return os.path.join(
            os.path.dirname(os.path.dirname(__file__)),
            "epubcheck", "epubcheck.jar"
        )

    def test_epub_passes_epubcheck(self, shared_epub):
        """生成的 EPUB 应通过 epubcheck 验证，无错误无警告"""
        jar = self._epubcheck_jar()

        result = subprocess.run(
            ["java", "-jar", jar, shared_epub],
            capture_output=True, text=True, timeout=60
        )

        # 打印输出方便调试
        if result.returncode != 0:
            print(f"\nEPUBCheck Output:\n{result.stderr}")
            print(f"\nEPUBCheck Stdout:\n{result.stdout}")

        assert result.returncode == 0, (
            f"epubcheck 验证失败（exit={result.returncode}）：\n"
            f"{result.stderr}"
        )

        print(f"✓ EPUBCheck 验证通过")
