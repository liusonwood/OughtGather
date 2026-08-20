"""
EPUB 生成器模块
负责生成完整的 EPUB 电子书
"""

import os
from typing import List, Tuple, Dict, Optional, Union
from ebooklib import epub
from bs4 import BeautifulSoup

from src.config import Config, ContentSource
from src.fetchers.base import Article, FetchResult
from src.processors.content_processor import ContentProcessor
from src.epub.cover import CoverGenerator
from src.epub.toc import TOCGenerator
from src.epub.helpers import generate_toc_link, create_section_divider_page
from src.processors.image_processor import ImageProcessor
from src.utils.logger import get_logger
from src.utils.helpers import get_now

import html as html_module


class EPUBGenerator:
    """EPUB 生成器"""

    def __init__(self, config: Config):
        """
        初始化 EPUB 生成器

        Args:
            config: 全局配置
        """
        self.config = config
        self.logger = get_logger()
        self.image_processor = ImageProcessor()
        self.toc_generator = TOCGenerator()
        self.cover_generator = CoverGenerator(config.title)

    def generate(
        self,
        results: List[FetchResult],
        error_log: List[str] = None,
        start_time: Optional[float] = None,
        runtime: float = 0.0
    ) -> str:
        """
        生成 EPUB 文件 (EPUB 3.0 格式，符合规范)
        """
        import time
        if start_time is not None:
            runtime = time.time() - start_time
        self.logger.info(f"Generating EPUB, runtime: {runtime:.2f}s so far")
        # 1. 创建 EPUB 书籍对象
        book = epub.EpubBook()

        # 2. 设置元数据
        self._set_metadata(book)

        # 3. 添加封面
        self._add_cover(book)

        # 4. 添加 NCX (EPUB 2.0 兼容)
        ncx = epub.EpubNcx()
        book.add_item(ncx)

        # 5. 准备章节数据
        sections = self._prepare_sections(results)

        # 6. 生成目录数据
        toc = self.toc_generator.generate(sections)
        book.toc = toc

        # 初始化 spine
        book.spine = []

        # 7. 添加章节并收集所有独特的 Emoji
        # 目录和章节标题也是可见内容，需在添加图片资源前预先收集。
        unique_emojis = self._get_title_emojis(sections)
        unique_emojis.update(
            ContentProcessor.get_emojis_from_text(self.config.title.get_plain_text())
        )
        self._add_chapters(book, sections, unique_emojis)

        # 8. 添加推送汇总章节 (包括 Emoji 收集)
        if start_time is not None:
            runtime = time.time() - start_time
        summary_emojis = self._add_summary_chapter(book, results, error_log, runtime=runtime)
        unique_emojis.update(summary_emojis)
        
        # 9. 渲染并添加 Emoji 图片 (一次性添加)
        self._add_rendered_emojis(book, unique_emojis)

        # 10. 手动生成并添加 nav.xhtml
        nav = epub.EpubHtml(title=book.title, file_name='nav.xhtml', uid='nav')
        nav.properties = ['nav']
        nav.content = self._generate_nav_content(book.title, book.toc, is_nav=True)
        nav.add_link(href='style/default.css', rel='stylesheet')
        book.add_item(nav)

        # 11. 生成并添加物理目录页 contents.xhtml
        contents = epub.EpubHtml(title="目录", file_name='contents.xhtml', uid='contents')
        contents.content = self._generate_nav_content(book.title, book.toc, is_nav=False)
        contents.add_link(href='style/default.css', rel='stylesheet')
        book.add_item(contents)

        if isinstance(book.spine, list):
            book.spine.insert(0, contents)
        else:
            book.spine = [contents]

        # 12. 添加样式
        self._add_style(book)

        # 13. 设置 Guide 元素
        book.guide = [
            {'href': 'contents.xhtml', 'title': 'Table of Contents', 'type': 'toc'},
            {'href': 'contents.xhtml', 'title': 'Cover', 'type': 'cover'},
            {'href': 'contents.xhtml', 'title': 'Table of Contents', 'type': 'text'},
            {'href': 'contents.xhtml', 'title': 'Start', 'type': 'start'},
        ]

        # 14. 保存文件
        output_path = self._save_book(book)

        self.logger.info(f"EPUB 3.0 (compliant) generated: {output_path}")
        return output_path

    def _set_metadata(self, book: epub.EpubBook):
        """设置书籍元数据"""
        # 使用标准的 UUID，并确保每次生成的 ID 唯一
        import uuid
        book.set_identifier(str(uuid.uuid4()))
        book.set_title(self.config.title.get_plain_text())
        # 使用 zh (匹配成功文件)
        book.set_language('zh')
        book.add_author('Ought Gather')

    def _add_cover(self, book: epub.EpubBook):
        """添加封面 (EPUB 3.0 格式)"""
        try:
            cover_filename, cover_data = self.cover_generator.generate()

            # 设置封面图片 (使用 set_cover 确保 properties="cover-image" 被正确设置)
            # ebooklib 会自动处理 manifest 中的 properties
            # 设置 create_page=False，避免 ebooklib 自动创建可能被错误解析的 XHTML 封面页
            book.set_cover(cover_filename, cover_data, create_page=False)

            self.logger.info("Cover image set in EPUB (no XHTML page)")
        except Exception as e:
            self.logger.error(f"Failed to add cover: {e}")


    def _prepare_sections(
        self,
        results: List[FetchResult]
    ) -> List[Tuple[ContentSource, List[Article], Optional[str]]]:
        """
        准备章节数据（按优先级排序）

        Args:
            results: 抓取结果列表

        Returns:
            List[Tuple[ContentSource, List[Article], Optional[str]]]: 章节数据
            第三个元素为内容源的显示名称（如 RSS feed 标题）
        """
        # 按优先级排序（降序）
        sorted_results = sorted(
            results,
            key=lambda r: r.source.priority,
            reverse=True
        )

        sections = []
        for result in sorted_results:
            if result.success and result.articles:
                sections.append((result.source, result.articles, result.source_title))

        return sections

    def _add_chapters(
        self,
        book: epub.EpubBook,
        sections: List[Tuple[ContentSource, List[Article], Optional[str]]],
        unique_emojis: set
    ):
        """
        添加章节 (EPUB 3.0 格式)

        在每个不同内容源（大目录）的第一篇文章前插入一个章节分隔页，
        让阅读时能清楚地感知进入了新的栏目/分组。
        """
        chapter_id = 0
        divider_id = 0

        # 使用 book.spine 的当前值
        # 不将 cover 加入 spine，封面仅通过 manifest + guide 引用，
        # 确保打开电子书时直接进入目录 (nav.xhtml) 而非封面。
        if not book.spine:
            book.spine = []
        spine = book.spine

        chapters_to_process = []  # [(chapter, article, source)]

        for source, articles, source_title in sections:
            # 在该分组的第一篇文章前插入章节分隔页，显示所属栏目标题
            section_title = self.toc_generator._get_source_title(
                source, articles, source_title
            )
            # 所有 fetcher 均使用两级结构，锚定到 toc_section_{divider_id}
            target_toc_id = f"toc_section_{divider_id}"

            # 构造栏目下所有文章的信息，用于在分隔页展示子目录
            articles_info = []
            curr_chapter_id = chapter_id
            for article in articles:
                articles_info.append({
                    "title": article.title,
                    "file_name": f"chapter_{curr_chapter_id}.xhtml"
                })
                curr_chapter_id += 1

            divider = create_section_divider_page(
                section_title=section_title,
                file_name=f"divider_{divider_id}.xhtml",
                target_toc_id=target_toc_id,
                articles_info=articles_info
            )
            book.add_item(divider)
            spine.append(divider)
            divider_id += 1

            for article in articles:
                # 标题是纯文本元数据；正文 h1 则使用本地图片渲染 emoji。
                rendered_title = ContentProcessor.render_text_with_emojis(article.title)

                # 生成章节内容
                chapter_content = self._generate_chapter_content(
                    article, chapter_id, rendered_title=rendered_title
                )
                
                # 收集 Emoji 并替换为图片标签 (content)
                unique_emojis.update(ContentProcessor.get_unique_emojis(chapter_content))
                chapter_content = ContentProcessor.replace_emojis_with_images(chapter_content)

                # 创建章节
                chapter = epub.EpubHtml(
                    title=article.title,
                    file_name=f"chapter_{chapter_id}.xhtml"
                )
                chapter.content = chapter_content

                chapters_to_process.append((chapter, article, source))
                book.add_item(chapter)
                spine.append(chapter)  # 添加到 spine（阅读顺序）
                chapter_id += 1

        # 1. 收集所有章节中的唯一图片 URL
        self.logger.info("Gathering all unique image URLs from chapters...")
        unique_images = {}  # image_src -> page_url (用于解析相对路径)
        
        # 检查全局设置
        global_load_images = self.config.load_images == 'Y'

        for chapter, article, source in chapters_to_process:
            if not chapter.content:
                continue
                
            # 检查源设置
            source_load_images = source.load_images == 'Y'
            
            # 只要有一个为 'N'，就不加载图片（严格模式）或者以源设置为准？
            # 通常应该是全局为开关，源为特定开关。
            # 如果全局关闭，所有都关闭。如果全局开启，源可以关闭。
            should_load = global_load_images and source_load_images
            
            if not should_load:
                continue

            soup = BeautifulSoup(chapter.content, 'lxml')
            for img in soup.find_all('img'):
                if img.get('class') and 'emoji' in img.get('class'):
                    continue
                src, _ = self._extract_image_src(img)
                if src and not src.startswith('data:'):
                    if src not in unique_images:
                        unique_images[src] = article.url

        # 2. 并发下载和处理图片
        import concurrent.futures
        download_results = {}  # image_src -> (filename, img_data) or None
        if unique_images:
            self.logger.info(f"Downloading {len(unique_images)} images concurrently...")
            max_workers = min(len(unique_images), 25)
            with concurrent.futures.ThreadPoolExecutor(max_workers=max_workers) as executor:
                future_to_src = {
                    executor.submit(self.image_processor.download_and_process, src, page_url): src
                    for src, page_url in unique_images.items()
                }
                for future in concurrent.futures.as_completed(future_to_src):
                    src = future_to_src[future]
                    try:
                        res = future.result()
                        download_results[src] = res
                    except Exception as e:
                        self.logger.error(f"Image download thread failed for {src}: {e}")
                        download_results[src] = None

        # 2.5 体积/数量超限 → 自动严格压缩
        try:
            needs_strict = (self.image_processor.needs_strict_compression() is True)
        except Exception as e:
            self.logger.warning(f"Failed to check strict compression condition: {e}")
            needs_strict = False

        if needs_strict:
            total_mb = self.image_processor.get_total_size_mb()
            successful_count = sum(1 for r in download_results.values() if r)
            self.logger.warning(
                f"Images exceed threshold "
                f"({total_mb:.2f} MB / {successful_count} images, "
                f"limits: {self.image_processor.TRIGGER_TOTAL_MB} MB / "
                f"{self.image_processor.TRIGGER_IMAGE_COUNT}). "
                f"Applying strict recompression..."
            )
            strict_map = self.image_processor.recompress_all_strict()
            # 用严格压缩后的字节更新 download_results
            for src, result in list(download_results.items()):
                if result is None:
                    continue
                filename, _old_data = result
                if filename in strict_map:
                    download_results[src] = (filename, strict_map[filename])
            self.logger.info(
                f"After strict recompression: "
                f"{self.image_processor.get_total_size_mb():.2f} MB"
            )

        # 3. 顺序更新每个章节的 HTML 并组装电子书
        self.logger.info("Updating image references sequentially and adding images to book...")
        for chapter, article, source in chapters_to_process:
            if not chapter.content:
                continue
                
            soup = BeautifulSoup(chapter.content, 'lxml')
            img_tags = soup.find_all('img')
            
            if not img_tags:
                continue

            # 用于存储本章节已处理的图片 URL，避免在同一章节中重复处理
            url_to_filename = {}
            
            # 再次检查加载开关
            should_load = global_load_images and (source.load_images == 'Y')

            for img in img_tags:
                if img.get('class') and 'emoji' in img.get('class'):
                    continue
                
                if not should_load:
                    img.decompose()
                    continue

                src, remote_attrs = self._extract_image_src(img)
                
                # 彻底移除所有干扰属性，防止残留远程链接
                for attr in remote_attrs:
                    if img.has_attr(attr):
                        del img[attr]

                if not src or src.startswith('data:'):
                    if not src:
                        img.decompose()
                    continue

                # 如果本章节已经处理过这个 URL
                if src in url_to_filename:
                    img['src'] = f"images/{url_to_filename[src]}"
                    continue

                # 获取处理后的结果
                result = download_results.get(src)

                if result:
                    filename, img_data = result
                    url_to_filename[src] = filename

                    # 检查是否已经添加过这个 item
                    image_uid = f"image_{filename}"
                    is_already_added = False
                    for item in book.items:
                        if item.id == image_uid:
                            is_already_added = True
                            break

                    if not is_already_added:
                        epub_image = epub.EpubItem(
                            uid=image_uid,
                            file_name=f"images/{filename}",
                            media_type="image/jpeg",
                            content=img_data
                        )
                        book.add_item(epub_image)

                    # 更新图片 URL
                    img['src'] = f"images/{filename}"
                else:
                    # 处理失败：彻底移除标签，绝不保留 http 引用
                    self.logger.debug(f"Removing image tag (processing failed or skipped): {src}")
                    img.decompose()

            # 将修改后的 HTML 写回 chapter.content
            chapter.content = str(soup)

        # 设置书籍的阅读顺序
        book.spine = spine

        self.logger.info(
            f"Added {chapter_id} chapters and {divider_id} section dividers to EPUB"
        )

    def _generate_chapter_content(
        self, article: Article, chapter_id: int, rendered_title: Optional[str] = None
    ) -> str:
        """
        生成章节 HTML 内容 (EPUB 3.0 格式，返回目录链接在标题下方)

        Args:
            article: 文章对象
            chapter_id: 章节 ID

        Returns:
            str: HTML 内容
        """
        import html

        # 对标题和作者进行 HTML 转义，防止 & 等字符导致 XML 解析失败
        safe_title = html.escape(article.title)
        rendered_title = rendered_title or ContentProcessor.render_text_with_emojis(article.title)
        safe_author = html.escape(article.author) if article.author else ""

        # EPUB 3.0 使用 HTML5 DOCTYPE
        toc_link = generate_toc_link(f"toc_chapter_{chapter_id}")
        content_html = f"""<!DOCTYPE html>
<html xmlns="http://www.w3.org/1999/xhtml" xmlns:epub="http://www.idpf.org/2007/ops" epub:prefix="z3998: http://www.daisy.org/z3998/2012/vocab/structure/#" lang="zh" xml:lang="zh">
<head>
    <title>{safe_title}</title>
    <link rel="stylesheet" type="text/css" href="style/default.css"/>
</head>
<body>
    <h1>{rendered_title}</h1>
    {toc_link}
"""

        # 添加元信息
        if safe_author:
            content_html += f"<p class='author'>Author/作者: {safe_author}</p>"
        if article.published_date:
            content_html += f"<p class='date'>Date/日期: {article.published_date}</p>"

        # 添加正文（正文已经由 ContentProcessor 处理过，应该是安全的 HTML 片段）
        content_html += f"<div class='content'>{article.content}</div>"

        # 添加原文链接 (仅保留 http/https 的合法绝对链接)
        if article.url and (article.url.startswith('http://') or article.url.startswith('https://')):
            safe_url = html.escape(article.url)
            content_html += f"<p class='link'>原文链接: <a href='{safe_url}'>{safe_url}</a></p>"

        content_html += """
</body>
</html>"""

        return content_html

    def _get_title_emojis(
        self, sections: List[Tuple[ContentSource, List[Article], Optional[str]]]
    ) -> set:
        """Collect emojis from every visible section and article title."""
        emojis = set()
        for source, articles, source_title in sections:
            section_title = self.toc_generator._get_source_title(source, articles, source_title)
            emojis.update(ContentProcessor.get_emojis_from_text(section_title))
            for article in articles:
                emojis.update(ContentProcessor.get_emojis_from_text(article.title))
        return emojis

    def _extract_image_src(self, img) -> Tuple[Optional[str], List[str]]:
        """
        从 img 标签中提取真实的图片 URL，并返回需要清理的远程属性列表
        """
        # 跳过已经替换为本地 emoji 图片的标签
        if img.get('class') and 'emoji' in img.get('class'):
            return None, []
            
        src = None
        remote_attrs = ['data-src', 'data-original', 'data-actualsrc', 'data-lazy-src', 'srcset', 'data-srcset', 'file', 'zoom-target', 'original']
        
        # 检查 srcset
        srcset = img.get('data-srcset') or img.get('srcset')
        if srcset:
            candidates = []
            for part in srcset.split(','):
                parts = part.strip().split()
                if parts:
                    url = parts[0]
                    if not any(ext in url.lower() for ext in ['.gif', '.svg']) and not url.lower().startswith('data:'):
                        candidates.append(url)
            if candidates:
                src = candidates[-1]
        
        # 检查懒加载属性
        if not src:
            for attr in remote_attrs:
                val = img.get(attr)
                if val and not any(ext in val.lower() for ext in ['.gif', '.svg']):
                    src = val
                    break
        
        if not src:
            src = img.get('src')
            if src and (any(ext in src.lower() for ext in ['.gif', '.svg']) or src.lower().startswith('data:')):
                src = None
            
        return src, remote_attrs

    def _add_images_to_chapter(
        self,
        book: epub.EpubBook,
        chapter: epub.EpubHtml,
        article: Article
    ):
        """
        添加图片到章节 (保持向后兼容及测试调用支持)

        Args:
            book: EPUB 书籍对象
            chapter: 章节对象
            article: 文章对象
        """
        if not chapter.content:
            return

        soup = BeautifulSoup(chapter.content, 'lxml')
        img_tags = soup.find_all('img')

        if not img_tags:
            return

        # 用于存储已处理 of 图片 URL，避免在同一章节中重复处理
        url_to_filename = {}

        for img in img_tags:
            if img.get('class') and 'emoji' in img.get('class'):
                continue
            src, remote_attrs = self._extract_image_src(img)
            
            # 彻底移除所有干扰属性，防止残留远程链接
            for attr in remote_attrs:
                if img.has_attr(attr):
                    del img[attr]

            if not src or src.startswith('data:'):
                if not src:
                    img.decompose()
                continue

            # 如果已经处理过这个 URL
            if src in url_to_filename:
                img['src'] = f"images/{url_to_filename[src]}"
                continue

            # 处理图片
            result = self.image_processor.download_and_process(src, article.url)

            if result:
                filename, img_data = result
                url_to_filename[src] = filename

                # 检查是否已经添加过这个 item
                image_uid = f"image_{filename}"
                is_already_added = False
                for item in book.items:
                    if item.id == image_uid:
                        is_already_added = True
                        break

                if not is_already_added:
                    epub_image = epub.EpubItem(
                        uid=image_uid,
                        file_name=f"images/{filename}",
                        media_type="image/jpeg",
                        content=img_data
                    )
                    book.add_item(epub_image)

                # 更新图片 URL
                img['src'] = f"images/{filename}"
            else:
                # 处理失败：彻底移除标签，绝不保留 http 引用
                self.logger.debug(f"Removing image tag (processing failed or skipped): {src}")
                img.decompose()

        # 将修改后的 HTML 写回 chapter.content (Bug 2)
        # BeautifulSoup 会生成完整的 HTML 结构并正确处理转义字符
        chapter.content = str(soup)

    def _add_summary_chapter(self, book: epub.EpubBook, results: List[FetchResult], error_log: List[str] = None, runtime: float = 0.0) -> set:
        """
        添加推送汇总章节 (EPUB 3.0 格式，包含本次推送的统计数据与工具介绍)

        Args:
            book: EPUB 书籍对象
            results: 抓取与处理结果列表
            error_log: 错误日志列表
            runtime: 运行耗时 (秒)
        
        Returns:
            set: 汇总章节中发现的唯一 Emoji 集合
        """
        import html

        error_log = error_log or []
        push_time = get_now().strftime("%Y-%m-%d %H:%M:%S")
        
        total_sources = len(results)
        success_sources = sum(1 for r in results if r.success)
        failed_sources = sum(1 for r in results if not r.success)
        total_articles = sum(len(r.articles) for r in results)
        
        runtime_str = f"{runtime:.1f} 秒"

        source_details = ""
        for r in results:
            src_type = r.source.type.upper()
            src_name = html.escape(r.source_title or r.source.title or r.source.src)
            if r.success:
                source_details += f"""
            <li class="source-item">
                <span class="stat-label">[{src_type}] {src_name}</span>：
                <span class="tag-success">成功</span>，新增 <span class="tag-success">{len(r.articles)}</span> 篇文章
            </li>"""
            else:
                err_msg = html.escape(r.error or "未知错误")
                source_details += f"""
            <li class="source-item">
                <span class="stat-label">[{src_type}] {src_name}</span>：
                <span class="tag-failed">失败</span> ({err_msg})
            </li>"""

        if error_log:
            error_log_content = "<ul>\n"
            for error in error_log:
                safe_error = html.escape(error)
                error_log_content += f"        <li>{safe_error}</li>\n"
            error_log_content += "    </ul>"
        else:
            error_log_content = "<p style='color: #2e7d32; font-weight: bold;'><span class=\"emoji\">🎉</span> 一切正常，本次运行未发生任何错误。</p>"

        # EPUB 3.0 使用 HTML5 DOCTYPE
        content_html = f"""<!DOCTYPE html>
<html xmlns="http://www.w3.org/1999/xhtml" xmlns:epub="http://www.idpf.org/2007/ops" epub:prefix="z3998: http://www.daisy.org/z3998/2012/vocab/structure/#" lang="zh" xml:lang="zh">
<head>
    <title>Summary / 推送汇总</title>
    <link rel="stylesheet" type="text/css" href="style/default.css"/>
    <style type="text/css">
        .summary-title {{
            text-align: center;
            margin-top: 1.5em;
            margin-bottom: 0.5em;
            color: #333333;
        }}
        .card {{
            border: 1px solid #dddddd;
            border-radius: 6px;
            padding: 15px;
            margin-bottom: 1.5em;
            background-color: #f9f9f9;
        }}
        .card-title {{
            font-size: 1.1em;
            font-weight: bold;
            margin-bottom: 10px;
            border-bottom: 1px solid #eeeeee;
            padding-bottom: 5px;
        }}
        .stat-item {{
            margin: 8px 0;
            line-height: 1.4;
        }}
        .stat-label {{
            font-weight: bold;
            color: #444444;
        }}
        .source-list {{
            list-style-type: none;
            padding-left: 0;
            margin: 0;
        }}
        .source-item {{
            padding: 8px 0;
            border-bottom: 1px dashed #e0e0e0;
            list-style: none;
        }}
        .source-item:last-child {{
            border-bottom: none;
        }}
        .tag-success {{
            color: #2e7d32;
            font-weight: bold;
        }}
        .tag-failed {{
            color: #c62828;
            font-weight: bold;
        }}
        .intro-text {{
            line-height: 1.6;
            text-indent: 2em;
            margin-bottom: 1em;
            color: #333333;
        }}
    </style>
</head>
<body>
    <h1 class=\"summary-title\">Summary / 推送汇总</h1>
    {generate_toc_link("toc_summary")}


    <div class="card">
        <div class=\"card-title\"><span class=\"emoji\">ℹ️</span> About / 关于 Ought Gather</div>
        <p class=\"intro-text\">Automated information aggregator delivering custom RSS, web articles, and newsletters to your Kindle as daily EPUBs
        <br>自动化信息聚合工具，支持将 RSS、网页、邮件等定时打包为 EPUB 推送至 Kindle。</p>
        <p class=\"intro-text\">For configuration or contribution, please visit the GitHub repository or use <code>config-editor.html</code>.<br>
        想要添加或修改内容源、查看系统说明或贡献代码，请访问 GitHub 项目主页，或使用内置的配置编辑器 <code>config-editor.html</code> 进行可视化管理。</p>
        <p class=\"intro-text\">GitHub: <a href=\"https://github.com/liusonwood/oughtgather\">https://github.com/liusonwood/oughtgather</a></p>
    </div>
    
    <div class="card">
        <div class=\"card-title\">Statistics / 运行数据统计</div>
        <div class=\"stat-item\"><span class=\"stat-label\">Time / 推送时间：</span>{push_time}</div>
        <div class=\"stat-item\"><span class=\"stat-label\">Runtime / 运行耗时：</span>{runtime_str}</div>
        <div class=\"stat-item\"><span class=\"stat-label\">Sources / 内容源总数：</span>{total_sources}</div>
        <div class=\"stat-item\"><span class=\"stat-label\">Articles / 新增文章：</span><span class=\"tag-success\">{total_articles}</span></div>
        <div class=\"stat-item\"><span class=\"stat-label\">Success / 成功抓取：</span><span class=\"tag-success\">{success_sources}</span></div>
        <div class=\"stat-item\"><span class=\"stat-label\">Failed / 抓取失败：</span><span class=\"tag-failed\">{failed_sources}</span></div>
    </div>

    <div class="card">
        <div class=\"card-title\"><span class=\"emoji\">⚠️</span> Errors / 异常与错误记录</div>
        {error_log_content}
    </div>
    
    <div class="card">
        <div class=\"card-title\"><span class=\"emoji\">🔌</span> Source Details / 内容源详情</div>
        <ul class="source-list">
            {source_details}
        </ul>
    </div>


</body>
</html>"""

        # 收集 Emoji
        emojis = ContentProcessor.get_unique_emojis(content_html)
        
        # Process Emoji characters in the summary to replace them with images
        content_html = ContentProcessor.replace_emojis_with_images(content_html)

        chapter = epub.EpubHtml(
            title="Summary / 推送汇总",
            file_name="summary.xhtml"
        )
        chapter.content = content_html

        book.add_item(chapter)

        # 添加到目录
        book.toc.append(epub.Link("summary.xhtml", "Summary / 推送汇总", "summary"))

        # 添加到 spine（阅读顺序），保持为线性 (linear="yes")
        chapter.is_linear = True
        if isinstance(book.spine, list):
            book.spine.append(chapter)

        self.logger.info("Summary chapter added to EPUB (linear spine)")
        return emojis

    def _generate_nav_content(
        self,
        book_title: str,
        toc: List[Union[epub.Link, Tuple[epub.Link, List[epub.Link]]]],
        is_nav: bool = True
    ) -> str:
        """
        手动生成 EPUB 3.0 的 nav.xhtml 内容或 toc.xhtml 内容。
        为每个条目添加 ID 以便回跳。
        """
        import html
        from ebooklib import epub as epub_lib
        safe_title = html.escape(book_title)
        rendered_book_title = ContentProcessor.render_text_with_emojis(book_title)
        
        # 内联样式（作为 Kindle 兜底）：
        # EPUB 3.3 规范禁止 <style> 出现在 nav 文档的 <body> 中（EPUBCheck RSC-005），
        # 因此改用 inline style 属性，所有阅读器（含 Kindle）都能正确渲染，
        # 同时通过 nav.add_link() 注册的外部 CSS 为支持它的阅读器提供完整样式。
        if is_nav:
            STYLE_SECTION_LINK = (
                "font-weight: bold; font-size: 1.2em; color: #111111; "
                "display: block; margin-top: 0.4em; margin-bottom: 0.2em; text-decoration: none;"
            )
            STYLE_H2 = ""
        else:
            STYLE_H2 = (
                "font-size: 1.2em; font-weight: bold; margin-top: 0.4em; margin-bottom: 0.2em; "
                "margin-left: 0; margin-right: 0; padding: 0; display: block;"
            )
            STYLE_SECTION_LINK = (
                "color: #111111; text-decoration: none;"
            )
        STYLE_ARTICLE_LINK = (
            "font-weight: normal; font-size: 1.0em; color: #0066cc; text-decoration: none;"
        )
        STYLE_H1 = (
            "text-align: center; font-size: 1.4em; margin-bottom: 0.5em; "
            "border-bottom: 2px solid #333; padding-bottom: 0.3em;"
        )
        STYLE_OL = "list-style-type: none; margin: 0; padding: 0;"
        STYLE_LI = "margin: 0.8em 0;"
        STYLE_NESTED_OL = (
            "margin-left: 1em; list-style-type: none; "
            "border-left: 2px solid #eee; padding-left: 0.6em; margin-top: 0.4em; margin-bottom: 0.4em;"
        )
        STYLE_NESTED_LI = "margin: 0.2em 0;"

        nav_tag_start = f'<nav epub:type="toc" id="toc">' if is_nav else '<div id="toc">'
        nav_tag_end = '</nav>' if is_nav else '</div>'

        content = f"""<!DOCTYPE html>
<html xmlns="http://www.w3.org/1999/xhtml" xmlns:epub="http://www.idpf.org/2007/ops" lang="zh" xml:lang="zh">
<head>
    <title>{safe_title}</title>
    <link rel="stylesheet" type="text/css" href="style/default.css"/>
</head>
<body style="padding: 1em;">
    {nav_tag_start}
        <h1 style="{STYLE_H1}">{rendered_book_title}</h1>
        <ol style="{STYLE_OL}">
"""
        for item in toc:
            if isinstance(item, epub_lib.Link):
                # 扁平链接（如 summary），使用大章节样式
                link_html = f'<a class="section-link" href="{item.href}" style="{STYLE_SECTION_LINK}">{ContentProcessor.render_text_with_emojis(item.title)}</a>'
                if not is_nav:
                    link_html = f'<h2 style="{STYLE_H2}">{link_html}</h2>'
                content += f'            <li id="toc_{item.uid}" style="{STYLE_LI}">{link_html}</li>\n'
            elif isinstance(item, tuple) and len(item) == 2:
                # 两级 structure（如 mail/rss）
                section_link, links = item
                content += f'            <li id="toc_{section_link.uid}" style="{STYLE_LI}">\n'
                link_html = f'<a class="section-link" href="{section_link.href}" style="{STYLE_SECTION_LINK}">{ContentProcessor.render_text_with_emojis(section_link.title)}</a>'
                if not is_nav:
                    link_html = f'<h2 style="{STYLE_H2}">{link_html}</h2>'
                content += f'                {link_html}\n'
                content += f'                <ol style="{STYLE_NESTED_OL}">\n'
                for link in links:
                    content += (
                        f'                    <li id="toc_{link.uid}" style="{STYLE_NESTED_LI}">'
                        f'<a class="article-link" href="{link.href}" style="{STYLE_ARTICLE_LINK}">'
                        f'{ContentProcessor.render_text_with_emojis(link.title)}</a></li>\n'
                    )
                content += f'                </ol>\n'
                content += f'            </li>\n'

        content += f"""        </ol>
    {nav_tag_end}
"""

        if is_nav:
            content += """
    <!-- EPUB 3.0 landmarks: toc + bodymatter 均指向 contents.xhtml -->
    <!-- Kindle 根据此块决定"打开时跳转到哪里"，hidden 使其不在阅读器目录中显示 -->
    <nav epub:type=\"landmarks\" id=\"landmarks\" hidden=\"\">
        <ol>
            <li><a epub:type=\"toc\" href=\"contents.xhtml\">Table of Contents / 目录</a></li>
            <li><a epub:type=\"bodymatter\" href=\"contents.xhtml\">Start of Content / 开始阅读</a></li>
        </ol>
    </nav>
"""

        if not is_nav:
            # Removed hidden link to nav.xhtml to allow removing nav.xhtml from spine.
            pass

        content += """</body>
</html>"""
        return content

    def _add_rendered_emojis(self, book: epub.EpubBook, unique_emojis: set):
        """渲染并添加 Emoji 图片"""
        from src.utils.emoji_renderer import render_emoji_to_png
        font_path = "Fonts/NotoEmoji-Medium.ttf"
        temp_dir = "temp_emoji_images"
        os.makedirs(temp_dir, exist_ok=True)
        
        for emoji in unique_emojis:
            try:
                filename = render_emoji_to_png(emoji, font_path, temp_dir)
                with open(os.path.join(temp_dir, filename), "rb") as f:
                    image_data = f.read()
                
                epub_image = epub.EpubItem(
                    uid=f"emoji_{filename.replace('.png', '')}",
                    file_name=f"images/{filename}",
                    media_type="image/png",
                    content=image_data
                )
                book.add_item(epub_image)
                self.logger.info(f"Added emoji image: {filename}")
            except Exception as e:
                self.logger.error(f"Failed to render emoji {emoji}: {e}")
        
        # 清理临时文件
        import shutil
        if os.path.exists(temp_dir):
            shutil.rmtree(temp_dir)

    def _add_style(self, book: epub.EpubBook):
        """添加样式"""
        # 动态收集所有已注册 Fetcher 的自定义 CSS 样式
        from src.fetchers.base import _registry
        extra_css = ""
        for name, cls in _registry.items():
            if hasattr(cls, "custom_css") and cls.custom_css:
                extra_css += f"\n/* --- Custom CSS from {cls.__name__} ({name}) --- */\n{cls.custom_css.strip()}\n"

        css = epub.EpubItem(
            uid="style",
            file_name="style/default.css",
            media_type="text/css",
            content="""
body {
    line-height: 1.6;
    margin: 1em;
}
strong, b {
    font-weight: bold;
}
em, i {
    font-style: italic;
}
h1 {
    font-size: 1.5em;
    font-weight: bold;
    margin-bottom: 0.5em;
    color: #333;
}
h2 {
    font-size: 1.3em;
    font-weight: bold;
    margin-bottom: 0.5em;
    color: #333;
}
.author, .date {
    font-size: 0.9em;
    color: #666;
    margin: 0.2em 0;
}
.content {
    margin-top: 1em;
    text-align: justify;
}
.content img {
    max-width: 100%;
    height: auto;
}

img.emoji {
    height: 18px !important;
    width: 18px !important;
    vertical-align: middle !important;
    display: inline-block !important;
    margin: 0 0.1em !important;
    border: none !important;
    object-fit: contain !important;
}

.link {
    margin-top: 2em;
    font-size: 0.8em;
    color: #999;
}
.toc-link {
    margin-top: 2em;
    font-size: 0.9em;
    text-align: left;
}
.toc-link a {
    color: #0066cc;
    text-decoration: none;
}
a {
    color: #0066cc;
    text-decoration: none;
}
ul {
    margin: 1em 0;
    padding-left: 2em;
}
li {
    margin: 0.5em 0;
}
nav ol {
    line-height: 1.5;
}
nav li {
    margin: 0.8em 0;
}

/* 行内代码与代码块样式 */
code {
    font-family: monospace;
    font-size: 0.85em;
    background-color: #f5f5f5;
    padding: 0 2px;
    display: inline !important;
    white-space: normal;
    word-wrap: break-word;
    word-break: break-word;
}
pre {
    font-family: monospace;
    font-size: 0.8em;
    background-color: #f5f5f5;
    padding: 0.5em 0.8em;
    border-radius: 4px;
    margin: 0.8em 0;
    overflow-x: auto;
    white-space: pre-wrap;
    word-wrap: break-word;
    word-break: normal;
}
pre code {
    display: block !important;
    background-color: transparent !important;
    padding: 0 !important;
    border-radius: 0 !important;
    font-size: 1em;
    white-space: inherit;
    word-wrap: inherit;
    word-break: inherit;
}

/* 目录 (nav.xhtml) 专属样式 */
#toc h1 {
    text-align: center;
    font-size: 1.4em;
    margin-bottom: 0.5em;
    border-bottom: 2px solid #333;
    padding-bottom: 0.3em;
}
#toc ol {
    list-style-type: none;
    margin: 0;
    padding: 0;
}
#toc li {
    margin: 0.8em 0;
}
#toc h2 {
    font-size: 1.2em !important;
    font-weight: bold !important;
    margin-top: 0.4em !important;
    margin-bottom: 0.2em !important;
    padding: 0 !important;
}
#toc .section-link {
  font-weight: bold !important;
  font-size: 1.2em !important;
  color: #111111 !important;
  display: block;
  text-decoration: none !important;
}
#toc h2 .section-link {
  font-size: 1em !important;
  font-weight: inherit !important;
  margin: 0 !important;
}

#toc .article-link { 
    font-weight: normal !important; 
    font-size: 1.0em !important; 
    color: #0066cc !important; 
    text-decoration: none !important;
}
#toc li ol { 
    margin-left: 1em; 
    list-style-type: none; 
    border-left: 2px solid #eee;
    padding-left: 0.6em;
    margin-top: 0.4em;
    margin-bottom: 0.4em;
}
#toc li ol li {
    margin: 0.4em 0;
}
""" + extra_css
        )
        book.add_item(css)

    def _save_book(self, book: epub.EpubBook) -> str:
        """
        保存 EPUB 文件

        Args:
            book: EPUB 书籍对象

        Returns:
            str: 文件路径
        """
        # 生成文件名
        from src.utils.helpers import sanitize_filename
        title = self.config.title.get_plain_text()
        # 建议：如果还是失败，尝试将文件名改为纯英文/数字
        filename = sanitize_filename(title) + ".epub"

        # 确保输出目录存在
        os.makedirs("output", exist_ok=True)

        output_path = os.path.join("output", filename)

        # 保存
        epub.write_epub(output_path, book, {})

        # 检查文件大小
        file_size = os.path.getsize(output_path)
        file_size_mb = file_size / (1024 * 1024)

        self.logger.info(f"EPUB file size: {file_size_mb:.2f} MB")

        if file_size_mb > 30:
            self.logger.warning(
                f"EPUB file size {file_size_mb:.2f} MB exceeds 30MB soft limit "
                f"(Kindle email delivery may fail)."
            )
        if file_size_mb > 50:
            self.logger.error(
                f"EPUB file size {file_size_mb:.2f} MB exceeds 50MB hard limit!"
            )

        return output_path
