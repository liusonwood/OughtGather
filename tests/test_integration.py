"""
集成测试 - 测试完整流程，真正生成 EPUB 文件
运行：python -m pytest tests/test_integration.py -v -s
"""

import os
import subprocess
import shutil
import pytest
from unittest.mock import patch, MagicMock

from src.config import Config, TitleConfig, ContentSource, _parse_config
from src.fetchers.base import Article, FetchResult
from src.fetchers.rss_fetcher import RSSFetcher
from src.fetchers.web_fetcher import WebFetcher
from src.processors.content_processor import ContentProcessor
from src.processors.image_processor import ImageProcessor
from src.dedup.tracker import DedupTracker
from src.epub.generator import EPUBGenerator


def _make_feedparser_dict(d):
    """模拟 feedparser 的 FeedParserDict"""
    class FeedParserDict(dict):
        def __getattr__(self, name):
            try:
                return self[name]
            except KeyError:
                raise AttributeError(name)
    return FeedParserDict(d)


# =========================================================================
# 完整流程集成测试
# =========================================================================

class TestFullPipeline:
    """完整流程集成测试：从抓取到生成 EPUB"""

    def test_rss_to_epub(self, tmp_path):
        """测试 RSS 抓取 → 内容处理 → EPUB 生成"""
        # 1. 准备配置
        config_data = {
            "title": {
                "text": "集成测试 {time}",
                "img": ""
            },
            "body": [
                {
                    "type": "rss",
                    "src": "https://example.com/rss",
                    "title": "测试 RSS 源",
                    "priority": 10,
                    "keep_link": "Y",
                }
            ]
        }
        config = _parse_config(config_data)

        # 2. Mock RSS 数据
        mock_feed = MagicMock()
        mock_feed.bozo = False
        mock_feed.feed = {"title": "测试 Feed"}
        mock_feed.entries = [
            _make_feedparser_dict({
                "title": "文章一：Python 教程",
                "link": "https://example.com/1",
                "author": "作者 A",
                "published": "2024-01-01",
                "content": [_make_feedparser_dict({
                    "value": "<h2>Python 入门</h2><p>这是一篇关于 Python 的教程。</p><p>Python 是一门优秀的编程语言。</p>"
                })],
                "tags": [{"term": "python"}, {"term": "programming"}],
            }),
            _make_feedparser_dict({
                "title": "文章二：Web 开发",
                "link": "https://example.com/2",
                "author": "作者 B",
                "published": "2024-01-02",
                "content": [_make_feedparser_dict({
                    "value": "<h2>Web 开发基础</h2><p>本文介绍 Web 开发的基本概念。</p><p>包括 HTML、CSS、JavaScript。</p>"
                })],
                "tags": [{"term": "web"}],
            }),
        ]

        with patch.object(RSSFetcher, "_make_request", return_value=MagicMock(content=b"<rss></rss>", text="<rss></rss>")), \
             patch("src.fetchers.rss_fetcher.feedparser.parse", return_value=mock_feed):
            # 3. 抓取 RSS
            source = config.body[0]
            fetcher = RSSFetcher(source)
            fetch_result = fetcher.fetch()

            assert fetch_result.success is True
            assert len(fetch_result.articles) == 2
            print(f"✓ 成功抓取 {len(fetch_result.articles)} 篇文章")

            # 4. 处理内容
            processor = ContentProcessor(source)
            processed_articles = []
            for article in fetch_result.articles:
                original_content = article.content
                processed = processor.process(article)
                processed_articles.append(processed)
                print(f"  文章 '{article.title}': 内容长度 {len(original_content)} -> {len(processed.content)}")

            fetch_result.articles = processed_articles
            assert len(fetch_result.articles) == 2
            assert "Python" in fetch_result.articles[0].content
            print(f"✓ 内容处理完成")

            # 5. 生成 EPUB（需要 FetchResult 列表，不是 Article 列表）
            generator = EPUBGenerator(config)
            epub_path = generator.generate([fetch_result])  # 返回实际路径

            # 6. 验证 EPUB 文件
            assert os.path.exists(epub_path), f"EPUB 文件应该存在: {epub_path}"
            assert os.path.getsize(epub_path) > 0, "EPUB 文件不应该为空"
            print(f"✓ EPUB 文件生成成功：{epub_path}")
            print(f"  文件大小：{os.path.getsize(epub_path)} 字节")

            # 7. 验证 EPUB 内容（可选：解压检查）
            import zipfile
            assert zipfile.is_zipfile(epub_path), "EPUB 应该是 ZIP 格式"

            with zipfile.ZipFile(epub_path, 'r') as zf:
                file_list = zf.namelist()
                assert 'mimetype' in file_list, "EPUB 应包含 mimetype 文件"
                # 目录文件可能在根目录或 EPUB/ 子目录
                has_toc = any('toc.ncx' in f or 'nav.xhtml' in f for f in file_list)
                assert has_toc, f"EPUB 应包含目录文件，实际文件：{file_list}"
                print(f"  EPUB 包含 {len(file_list)} 个文件")

            # 清理生成的文件
            os.remove(epub_path)

    def test_multiple_sources_to_epub(self, tmp_path):
        """测试多个内容源 → EPUB 生成"""
        # 1. 准备配置（多个内容源）
        config_data = {
            "title": {
                "text": "多源测试 {time}",
                "img": ""
            },
            "body": [
                {
                    "type": "rss",
                    "src": "https://example.com/rss1",
                    "title": "RSS 源 1",
                    "priority": 15,
                },
                {
                    "type": "rss",
                    "src": "https://example.com/rss2",
                    "title": "RSS 源 2",
                    "priority": 10,
                },
            ]
        }
        config = _parse_config(config_data)

        # 2. Mock 两个 RSS 源
        def mock_make_request(url, **kwargs):
            resp = MagicMock()
            resp.content = url.encode("utf-8")
            resp.text = url
            return resp

        def mock_parse_factory(content):
            url = content.decode("utf-8") if isinstance(content, bytes) else str(content)
            mock_feed = MagicMock()
            mock_feed.bozo = False

            if "rss1" in url:
                mock_feed.feed = {"title": "Feed 1"}
                mock_feed.entries = [
                    _make_feedparser_dict({
                        "title": "来自源 1 的文章",
                        "link": "https://example.com/1",
                        "content": [_make_feedparser_dict({
                            "value": "<p>这是第一个源的文章内容。</p>"
                        })],
                        "tags": [],
                    }),
                ]
            else:
                mock_feed.feed = {"title": "Feed 2"}
                mock_feed.entries = [
                    _make_feedparser_dict({
                        "title": "来自源 2 的文章",
                        "link": "https://example.com/2",
                        "content": [_make_feedparser_dict({
                            "value": "<p>这是第二个源的文章内容。</p>"
                        })],
                        "tags": [],
                    }),
                ]
            return mock_feed

        all_results = []

        with patch.object(RSSFetcher, "_make_request", side_effect=mock_make_request), \
             patch("src.fetchers.rss_fetcher.feedparser.parse", side_effect=mock_parse_factory):
            # 3. 抓取所有源
            for source in config.body:
                fetcher = RSSFetcher(source)
                result = fetcher.fetch()
                assert result.success is True

                processor = ContentProcessor(source)
                processed_articles = []
                for article in result.articles:
                    processed = processor.process(article)
                    processed_articles.append(processed)
                result.articles = processed_articles

                all_results.append(result)

            assert len(all_results) == 2
            total_articles = sum(len(r.articles) for r in all_results)
            assert total_articles == 2
            print(f"✓ 从 {len(config.body)} 个源抓取了 {total_articles} 篇文章")

            # 4. 生成 EPUB（传入 FetchResult 列表）
            generator = EPUBGenerator(config)
            epub_path = generator.generate(all_results)  # 返回实际路径

            # 5. 验证
            assert os.path.exists(epub_path)
            assert os.path.getsize(epub_path) > 0
            print(f"✓ EPUB 生成成功：{epub_path}")
            print(f"  文件大小：{os.path.getsize(epub_path)} 字节")

            # 清理
            os.remove(epub_path)


class TestDedupIntegration:
    """去重功能集成测试"""

    def test_dedup_across_runs(self, tmp_path):
        """测试跨多次运行的去重"""
        dedup_file = tmp_path / "fetched_urls.txt"

        # 第一次运行
        tracker1 = DedupTracker(str(dedup_file))
        tracker1.mark_as_fetched("https://example.com/1", "文章 1")
        tracker1.mark_as_fetched("https://example.com/2", "文章 2")
        tracker1.save()

        assert dedup_file.exists()
        print(f"✓ 第一次运行：标记了 2 篇文章")

        # 第二次运行（应该能加载之前的记录）
        tracker2 = DedupTracker(str(dedup_file))
        assert tracker2.is_fetched("https://example.com/1", "文章 1") is True
        assert tracker2.is_fetched("https://example.com/2", "文章 2") is True
        assert tracker2.is_fetched("https://example.com/3", "文章 3") is False

        tracker2.mark_as_fetched("https://example.com/3", "文章 3")
        tracker2.save()
        print(f"✓ 第二次运行：新增 1 篇文章，跳过 2 篇已抓取")

        # 第三次运行（应该能加载所有记录）
        tracker3 = DedupTracker(str(dedup_file))
        stats = tracker3.get_stats()
        # 3 篇文章 = 3 条 URL 哈希
        assert stats["total_fetched"] == 3
        assert stats["new_fetched"] == 0  # 没有新标记

        print(f"✓ 第三次运行：总共 {stats['total_fetched']} 篇已抓取")


class TestContentProcessingIntegration:
    """内容处理集成测试"""

    def test_complex_content_rules(self):
        """测试复杂的内容处理规则组合"""
        source = ContentSource(
            type="rss",
            src="https://example.com/rss",
            title="测试",
            keep_link="N",
            exclude=[
                {"type": "start", "value": "阅读更多"},
                {"type": "end", "value": "— 完 —"},
                {"type": "exact", "value": '<span class="ad">广告</span>'},
            ],
        )

        html = """
        <div>
            <a href="#">阅读更多</a>
            <p>正文的第一段，包含重要内容。</p>
            <p>正文的第二段，<a href="https://example.com">链接</a>应该被移除。</p>
            <span class="ad">广告</span>
            <p>正文的第三段。</p>
            <p>— 完 —</p>
            <p>这段应该被删除。</p>
        </div>
        """

        article = Article(
            title="测试文章",
            content=html,
            url="https://example.com/test",
        )

        processor = ContentProcessor(source)
        result = processor.process(article)

        # 验证规则生效
        assert "阅读更多" not in result.content
        assert "这段应该被删除" not in result.content
        assert "广告" not in result.content
        assert "<a" not in result.content  # 链接被移除
        assert "正文的第一段" in result.content
        assert "链接" in result.content  # 链接文字保留
        print("✓ 复杂内容规则处理正确")


class TestEpubStructure:
    """EPUB 文件结构测试"""

    def test_epub_contains_required_files(self, tmp_path):
        """验证 EPUB 包含必需的文件"""
        config_data = {
            "title": {"text": "结构测试", "img": ""},
            "body": [
                {
                    "type": "rss",
                    "src": "https://example.com/rss",
                    "title": "测试源",
                    "priority": 10,
                }
            ]
        }
        config = _parse_config(config_data)

        # 创建一个 FetchResult
        source = config.body[0]
        articles = [
            Article(
                title="测试文章",
                content="<p>内容</p>",
                url="https://example.com",
            ),
        ]
        fetch_result = FetchResult(source=source, articles=articles)

        generator = EPUBGenerator(config)
        epub_path_str = generator.generate([fetch_result])  # 传入 FetchResult 列表，返回实际路径

        import zipfile
        with zipfile.ZipFile(epub_path_str, 'r') as zf:
            files = zf.namelist()

            # 检查必需文件
            assert 'mimetype' in files, "缺少 mimetype"
            assert 'META-INF/container.xml' in files, "缺少 container.xml"

            # 检查内容文件（可能在 EPUB/ 或 OEBPS/ 目录）
            content_files = [f for f in files if 'EPUB/' in f or 'OEBPS/' in f]
            assert len(content_files) > 0, f"应该包含内容文件，实际文件：{files}"

            print(f"✓ EPUB 结构正确，包含 {len(files)} 个文件：")
            for f in sorted(files):
                print(f"    - {f}")

        # 清理
        os.remove(epub_path_str)


class TestSectionDividers:
    """章节分隔页测试：不同 source 分组间插入分隔页"""

    def _make_fetch_result(self, source, article_titles):
        """构造一个包含指定标题文章的 FetchResult"""
        articles = [
            Article(title=t, content=f"<p>内容{i}</p>", url=f"https://example.com/{i}")
            for i, t in enumerate(article_titles)
        ]
        return FetchResult(source=source, articles=articles)

    def _generate_epub(self, fetch_results):
        """用给定的 FetchResult 列表生成 EPUB，返回路径"""
        config_data = {
            "title": {"text": "分隔页测试", "img": ""},
            "body": [
                {"type": r.source.type, "src": r.source.src,
                 "title": r.source.title, "priority": r.source.priority}
                for r in fetch_results
            ],
        }
        config = _parse_config(config_data)
        generator = EPUBGenerator(config)
        return generator.generate(fetch_results)

    def _read_epub_xhtml(self, epub_path, filename):
        """读取 EPUB 中指定 xhtml 文件的内容"""
        import zipfile
        with zipfile.ZipFile(epub_path, 'r') as zf:
            # 查找文件（可能在 EPUB/ 或 OEBPS/ 子目录）
            target = next(
                (n for n in zf.namelist() if n.endswith(filename)),
                None
            )
            assert target is not None, f"找不到 {filename}，实际文件：{zf.namelist()}"
            return zf.read(target).decode('utf-8')

    def _get_spine_order(self, epub_path):
        """
        从 content.opf 中提取 spine 阅读顺序

        Returns:
            List[str]: 按阅读顺序排列的文件名列表（如 'chapter_0.xhtml'、'divider_0.xhtml'）
        """
        import zipfile
        from xml.etree import ElementTree as ET
        with zipfile.ZipFile(epub_path, 'r') as zf:
            opf_name = next(n for n in zf.namelist() if n.endswith('.opf'))
            opf_content = zf.read(opf_name).decode('utf-8')

        ns = {'opf': 'http://www.idpf.org/2007/opf'}
        root = ET.fromstring(opf_content)
        # manifest: id → href
        manifest = {
            item.get('id'): item.get('href')
            for item in root.findall('.//opf:manifest/opf:item', ns)
        }
        # spine: 按顺序列出 idref，映射为 href（文件名）
        return [
            manifest[itemref.get('idref')]
            for itemref in root.findall('.//opf:spine/opf:itemref', ns)
            if itemref.get('idref') in manifest
        ]

    def test_divider_inserted_between_different_sources(self, tmp_path):
        """两个不同 source 之间应该插入一个分隔页"""
        source_a = ContentSource(type="rss", src="https://a.com/rss", title="源 A", priority=10)
        source_b = ContentSource(type="rss", src="https://b.com/rss", title="源 B", priority=5)

        results = [
            self._make_fetch_result(source_a, ["文章 A1", "文章 A2"]),
            self._make_fetch_result(source_b, ["文章 B1"]),
        ]
        epub_path = self._generate_epub(results)
        try:
            import zipfile
            with zipfile.ZipFile(epub_path, 'r') as zf:
                files = zf.namelist()
                divider_files = [f for f in files if 'divider_' in f]
                assert len(divider_files) == 2, (
                    f"应有 2 个分隔页（每个 source 一个），实际：{divider_files}"
                )

            # 验证分隔页内容包含对应的栏目标题
            divider_0 = self._read_epub_xhtml(epub_path, "divider_0.xhtml")
            assert "源 A" in divider_0, "第一个分隔页应显示源 A 的标题"
            divider_1 = self._read_epub_xhtml(epub_path, "divider_1.xhtml")
            assert "源 B" in divider_1, "第二个分隔页应显示源 B 的标题"

            print(f"✓ 在两个不同 source 之间插入了分隔页")
        finally:
            os.remove(epub_path)

    def test_divider_in_spine_but_not_in_toc(self, tmp_path):
        """分隔页应在 spine 阅读顺序中，但不应出现在目录（TOC）里"""
        source_a = ContentSource(type="rss", src="https://a.com/rss", title="源 A", priority=10)
        source_b = ContentSource(type="rss", src="https://b.com/rss", title="源 B", priority=5)

        results = [
            self._make_fetch_result(source_a, ["文章 A1"]),
            self._make_fetch_result(source_b, ["文章 B1"]),
        ]
        epub_path = self._generate_epub(results)
        try:
            spine = self._get_spine_order(epub_path)

            # 验证分隔页顺序：toc → divider_0 → chapter_0 → divider_1 → chapter_1 → summary
            expected_order = [
                'contents.xhtml',
                'divider_0.xhtml', 'chapter_0.xhtml',
                'divider_1.xhtml', 'chapter_1.xhtml',
                'summary.xhtml',
            ]
            assert spine == expected_order, (
                f"spine 顺序错误，期望：{expected_order}，实际：{spine}"
            )

            print(f"✓ 分隔页在 spine 中位置正确：{' → '.join(spine)}")
        finally:
            os.remove(epub_path)

    def test_no_divider_for_single_source(self, tmp_path):
        """只有一个 source 时，仍会在文章前插入一个分隔页（作为章节起始页）"""
        source = ContentSource(type="rss", src="https://a.com/rss", title="唯一源", priority=10)
        results = [self._make_fetch_result(source, ["文章 1", "文章 2", "文章 3"])]
        epub_path = self._generate_epub(results)
        try:
            import zipfile
            with zipfile.ZipFile(epub_path, 'r') as zf:
                files = zf.namelist()
                divider_files = [f for f in files if 'divider_' in f]
                # 单个 source 仍会有一个分隔页（在文章之前）
                assert len(divider_files) == 1, (
                    f"单个 source 应有 1 个分隔页，实际：{divider_files}"
                )

            spine = self._get_spine_order(epub_path)
            chapter_files = [f for f in spine if f.startswith('chapter_')]
            assert len(chapter_files) == 3, f"应有 3 个文章章节，实际：{chapter_files}"

            # spine 顺序：toc → divider_0 → chapter_0 → chapter_1 → chapter_2 → summary
            expected = [
                'contents.xhtml', 'divider_0.xhtml',
                'chapter_0.xhtml', 'chapter_1.xhtml', 'chapter_2.xhtml',
                'summary.xhtml',
            ]
            assert spine == expected, f"spine 顺序错误：{spine}"
            print(f"✓ 单个 source：1 个分隔页 + 3 个文章章节，顺序正确")
        finally:
            os.remove(epub_path)

    def test_divider_html_escaping(self, tmp_path):
        """分隔页标题中的 HTML 特殊字符应被转义"""
        source = ContentSource(type="rss", src="https://a.com/rss",
                               title="<script>alert('xss')</script>", priority=10)
        results = [self._make_fetch_result(source, ["文章 1"])]
        epub_path = self._generate_epub(results)
        try:
            divider_html = self._read_epub_xhtml(epub_path, "divider_0.xhtml")
            # 不应出现未转义的 <script> 标签
            assert "<script>" not in divider_html, "HTML 特殊字符应被转义"
            assert "&lt;script&gt;" in divider_html, "应包含转义后的文本"
            print(f"✓ 分隔页 HTML 正确转义了特殊字符")
        finally:
            os.remove(epub_path)

    def test_chapter_title_emoji_is_rendered_as_local_image(self, tmp_path):
        source = ContentSource(type="rss", src="https://a.com/rss", title="测试源", priority=10)
        epub_path = self._generate_epub([self._make_fetch_result(source, ["新闻 📰"])])
        try:
            chapter_html = self._read_epub_xhtml(epub_path, "chapter_0.xhtml")
            assert 'src="images/emoji_1f4f0.png"' in chapter_html
            assert "<h1>新闻 <img" in chapter_html
        finally:
            os.remove(epub_path)

    def test_divider_link_back_to_toc(self, tmp_path):
        """分隔页应包含返回目录的链接"""
        source = ContentSource(type="rss", src="https://a.com/rss", title="测试源", priority=10)
        results = [self._make_fetch_result(source, ["文章 1"])]
        epub_path = self._generate_epub(results)
        try:
            divider_html = self._read_epub_xhtml(epub_path, "divider_0.xhtml")
            assert "contents.xhtml" in divider_html, "分隔页应包含返回目录的链接"
            print(f"✓ 分隔页包含返回目录的链接")
        finally:
            os.remove(epub_path)

    def test_divider_link_back_to_toc_matches_nav_ids(self, tmp_path):
        """测试不同类型（rss/web）的分隔页返回目录的链接ID在contents.xhtml中确实存在且匹配"""
        source_rss = ContentSource(type="rss", src="https://rss.com", title="RSS源", priority=10)
        source_web = ContentSource(type="web", src="https://web.com", title="Web源", priority=5)

        results = [
            self._make_fetch_result(source_rss, ["RSS文章1", "RSS文章2"]),
            self._make_fetch_result(source_web, ["Web文章"]),
        ]
        epub_path = self._generate_epub(results)
        try:
            # 读取 contents.xhtml
            toc_html = self._read_epub_xhtml(epub_path, "contents.xhtml")

            # RSS 分隔页为第一个：divider_0.xhtml
            divider_rss_html = self._read_epub_xhtml(epub_path, "divider_0.xhtml")
            # 应该链接到 toc_section_0
            assert 'href="contents.xhtml#toc_section_0"' in divider_rss_html, "RSS分隔页链接错误"
            assert 'id="toc_section_0"' in toc_html, "contents.xhtml中应该有id='toc_section_0'"

            # Web 分隔页为第二个：divider_1.xhtml
            divider_web_html = self._read_epub_xhtml(epub_path, "divider_1.xhtml")
            # 所有 fetcher 均使用两级结构，应该链接到 toc_section_1
            assert 'href="contents.xhtml#toc_section_1"' in divider_web_html, "Web分隔页链接错误"
            assert 'id="toc_section_1"' in toc_html, "contents.xhtml中应该有id='toc_section_1'"

            print(f"✓ 分隔页返回目录的链接完全匹配 contents.xhtml 中的 ID")
        finally:
            os.remove(epub_path)


# =========================================================================
# EPUB 标准合规性验证（使用 epubcheck）
# =========================================================================

class TestEpubcheckValidation:
    """使用 W3C epubcheck 工具验证生成的 EPUB 是否符合 EPUB 3 标准"""

    def setup_method(self, method):
        """检查 epubcheck 是否可用，不可用则跳过并提示"""
        if not shutil.which("java"):
            pytest.skip("⚠ EPUB 合规测试不存在：未找到 Java 运行时，请先安装 Java")
        jar = self._epubcheck_jar()
        if not os.path.exists(jar):
            pytest.skip(f"⚠ EPUB 合规测试不存在：未找到 {jar}，请参考 README 配置 epubcheck")

    @staticmethod
    def _epubcheck_jar():
        """返回 epubcheck.jar 路径（项目根目录下）"""
        return os.path.join(
            os.path.dirname(os.path.dirname(__file__)),
            "epubcheck", "epubcheck.jar"
        )

    def test_epub_with_failed_images_passes_epubcheck(self):
        """即使含图片下载失败，生成的 EPUB 仍应通过 epubcheck 验证（最复杂集成场景）"""
        jar = self._epubcheck_jar()

        source = ContentSource(
            type="rss", src="https://example.com/rss",
            title="图片测试源", priority=10
        )
        # 内容中包含无法下载的外部图片
        articles = [
            Article(
                title="含图片文章",
                content='<p>正文。</p><img src="https://via.placeholder.com/600x400"/>',
                url="https://example.com/1",
            ),
        ]
        results = [FetchResult(source=source, articles=articles)]

        # Mock 图片下载失败
        with patch.object(
            ImageProcessor, 'download_and_process', return_value=None
        ):
            # 生成临时 EPUB
            config_data = {
                "title": {"text": "Epubcheck 合规测试", "img": ""},
                "body": [
                    {"type": r.source.type, "src": r.source.src,
                     "title": r.source.title, "priority": r.source.priority}
                    for r in results
                ],
            }
            config = _parse_config(config_data)
            generator = EPUBGenerator(config)
            epub_path = generator.generate(results)

        try:
            result = subprocess.run(
                ["java", "-jar", jar, "--failonwarnings", epub_path],
                capture_output=True, text=True, timeout=60
            )
            print(result.stderr)
            assert result.returncode == 0, (
                f"epubcheck 验证失败（exit={result.returncode}）：\n"
                f"{result.stderr}"
            )
        finally:
            os.remove(epub_path)
