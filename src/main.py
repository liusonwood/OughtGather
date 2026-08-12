#!/usr/bin/env python3
"""
Ought Gather 主入口
自动化信息聚合工具
"""

import argparse
import sys
import os
import re
import time
import concurrent.futures
from html import unescape
from typing import List, Tuple

# 添加项目根目录到 Python 路径
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from src.config import load_config, Config, ContentSource
from src.fetchers import BaseFetcher, FetchResult, get_fetcher_class
from src.fetchers.base import Article
from src.processors.content_processor import ContentProcessor
from src.dedup.tracker import DedupTracker
from src.epub.generator import EPUBGenerator
from src.mailer.smtp_sender import SMTPSender
from src.utils.logger import (
    get_logger,
    start_task_buffer,
    stop_task_buffer,
    flush_task_logs,
    truncate_url,
    log_stage,
    log_banner,
    log_summary_table,
)

# 纯文本最少字符数；只要有字（>=1）或包含图片即视为有效正文
_MIN_PLAIN_TEXT_LEN = 1
_TAG_RE = re.compile(r"<[^>]+>")


def get_fetcher(source: ContentSource, global_limit: int = 15) -> BaseFetcher:
    """
    根据内容源类型获取对应的抓取器

    Args:
        source: 内容源配置
        global_limit: 全局抓取限制

    Returns:
        BaseFetcher: 抓取器实例
    """
    fetcher_class = get_fetcher_class(source.type)
    if not fetcher_class:
        raise ValueError(f"Unknown source type: {source.type}")

    return fetcher_class(source, global_limit=global_limit)


def has_valid_content(article: Article) -> bool:
    """
    判断文章是否具备可推送的有效正文。

    规则：
    - content 为空 / 仅空白 / 仅无意义空标签 → 无效
    - 去掉 HTML 标签后的纯文本长度 >= 1（只要有字）→ 有效
    - 纯文本为空，但存在图片（article.images 或 content 内含 <img>）→ 有效
    """
    if not article.content or not str(article.content).strip():
        return False

    plain = unescape(_TAG_RE.sub("", article.content))
    plain = re.sub(r"\s+", " ", plain).strip()

    if len(plain) >= _MIN_PLAIN_TEXT_LEN:
        return True

    if article.images:
        return True

    if "<img" in article.content.lower():
        return True

    return False


def process_results(results: List[FetchResult], tracker: DedupTracker) -> List[FetchResult]:
    """
    处理抓取结果（去重、内容处理）

    仅当文章具备有效正文且对应抓取器开启去重时，才标记去重并纳入推送列表，
    避免全文抓取失败产生的空壳文章永久占用去重记录。

    Args:
        results: 抓取结果列表
        tracker: 去重追踪器

    Returns:
        List[FetchResult]: 处理后的结果列表
    """
    logger = get_logger()
    processed_results = []

    for result in results:
        short_src = truncate_url(result.source.src, 40)
        prefix = f"{result.source.type} | {short_src}"

        if not result.success:
            logger.warning(f"[{prefix}] 对应内容源之前抓取失败，已跳过去重处理")
            processed_results.append(result)
            continue

        fetcher_cls = get_fetcher_class(result.source.type)
        dedup_enabled = getattr(fetcher_cls, "dedup_enabled", True) if fetcher_cls else True

        original_count = len(result.articles)
        new_articles = []
        skipped_empty = 0
        skipped_dedup = 0

        for article in result.articles:
            if dedup_enabled and tracker.is_fetched(article.url):
                logger.debug(f"[{prefix}] 跳过已抓取文章: {article.title}")
                skipped_dedup += 1
                continue

            # 先做内容处理，再判断是否有效；处理失败则保留原文再校验
            try:
                processor = ContentProcessor(result.source)
                article = processor.process(article)
            except Exception as e:
                logger.error(
                    f"[{prefix}] 处理文章 '{article.title}' 失败: {e}，保留原始文章内容"
                )

            if not has_valid_content(article):
                skipped_empty += 1
                logger.warning(
                    f"[{prefix}] 跳过无效/空正文（不写入去重）: {article.title}"
                )
                continue

            # 仅在启用去重且正文有效时标记去重
            if dedup_enabled:
                tracker.mark_as_fetched(article.url)
            new_articles.append(article)

        # 更新结果
        result.articles = new_articles
        processed_results.append(result)

        extras = []
        if skipped_dedup:
            extras.append(f"跳过已抓取 {skipped_dedup} 篇")
        if skipped_empty:
            extras.append(f"跳过空正文 {skipped_empty} 篇")
        extra_str = f"，{', '.join(extras)}" if extras else ""
        logger.info(
            f"[{prefix}] 内容处理完成: {len(new_articles)}/{original_count} 篇新文章{extra_str}"
        )

    return processed_results


def has_new_content(results: List[FetchResult]) -> bool:
    """
    检查是否有新内容

    Args:
        results: 抓取结果列表

    Returns:
        bool: 是否有新内容
    """
    return any(result.success and len(result.articles) > 0 for result in results)


def main(argv=None):
    """主函数"""
    parser = argparse.ArgumentParser(description="Ought Gather - 自动化信息聚合工具")
    parser.add_argument("--config", help="配置文件路径", default="config.json")
    parser.add_argument("--fresh-start", action="store_true", help="清空去重日志并全量标记当前所有 URL，不进行推送")
    args, _ = parser.parse_known_args(argv)

    logger = get_logger()
    start_time = time.time()

    log_banner("Ought Gather - 自动化信息聚合工具")

    try:
        # 1. 加载配置与初始化去重追踪器
        log_stage(1, 5, "加载配置与初始化去重追踪器")
        config = load_config(args.config)
        logger.info(f"成功加载 {len(config.body)} 个内容源配置")
        tracker = DedupTracker()

        # ------------------------------------------------------------------
        # Fresh Start 工作流处理
        # ------------------------------------------------------------------
        if args.fresh_start:
            log_stage(2, 5, "执行 Fresh Start 全量标记去重记录")
            tracker.clear()

            def fresh_start_task(source: ContentSource) -> Tuple[FetchResult, List[Tuple[int, str]]]:
                start_task_buffer()
                try:
                    fetcher = get_fetcher(source, global_limit=999999)
                    if not fetcher.dedup_enabled:
                        logger.info(f"[Fresh Start] 跳过不参与去重的源: {source.type} | {truncate_url(source.src, 40)}")
                        res = FetchResult(source=source, articles=[], success=True)
                    elif fetcher.supports_two_phase:
                        candidates = fetcher.fetch_list()
                        if candidates:
                            marked_count = 0
                            for c in candidates:
                                if c.get("url"):
                                    tracker.mark_as_fetched(c["url"])
                                    marked_count += 1
                            logger.info(
                                f"[Fresh Start 两阶段] {source.type} | {truncate_url(source.src, 40)}: "
                                f"标记 {marked_count} 条候选 URL"
                            )
                        res = FetchResult(source=source, articles=[], success=True)
                    else:
                        res = fetcher.fetch_with_retry()
                        if res.success and res.articles:
                            marked_count = 0
                            for article in res.articles:
                                if article.url:
                                    tracker.mark_as_fetched(article.url)
                                    marked_count += 1
                            logger.info(
                                f"[Fresh Start 单阶段] {source.type} | {truncate_url(source.src, 40)}: "
                                f"标记 {marked_count} 条文章 URL"
                            )
                            res.articles = []
                    records = stop_task_buffer()
                    return res, records
                except Exception as e:
                    logger.error(f"[Fresh Start] 异常失败 {source.src}: {e}")
                    res = FetchResult(source=source, articles=[], success=False, error=str(e))
                    records = stop_task_buffer()
                    return res, records

            max_workers = min(len(config.body), 20) if config.body else 1
            fresh_results = []
            with concurrent.futures.ThreadPoolExecutor(max_workers=max_workers) as executor:
                future_to_source = {
                    executor.submit(fresh_start_task, source): source
                    for source in config.body
                }
                for future in future_to_source:
                    source = future_to_source[future]
                    result, records = future.result()
                    fresh_results.append(result)
                    short_src = truncate_url(source.src, 40)
                    prefix = f"{source.type} | {short_src}"
                    flush_task_logs(prefix, records)

            tracker.save()
            stats = tracker.get_stats()
            logger.info(f"[Fresh Start 完成] 已全量标记当前内容源，共入库 {stats['total_fetched']} 条记录，未生成或发送 EPUB。")
            return

        # ------------------------------------------------------------------
        # 常规抓取流程
        # ------------------------------------------------------------------
        # 2. 抓取内容（并发处理 + 任务日志隔离缓冲）
        log_stage(2, 5, "并发抓取内容源（开启独立日志缓冲）")
        results: List[FetchResult] = []
        error_log: List[str] = []
        raw_counts = {}

        def fetch_source_task(source: ContentSource) -> Tuple[FetchResult, List[Tuple[int, str]]]:
            start_task_buffer()
            try:
                fetcher = get_fetcher(source, global_limit=config.limit)

                if fetcher.supports_two_phase:
                    candidates = fetcher.fetch_list()
                    if candidates is None:
                        logger.warning(
                            f"fetch_list 返回 None，回退单阶段抓取: {source.src}"
                        )
                        res = fetcher.fetch_with_retry()
                    else:
                        if fetcher.dedup_enabled:
                            new_candidates = [
                                c for c in candidates
                                if c.get("url") and not tracker.is_fetched(c["url"])
                            ]
                            limit = fetcher.get_limit()
                            to_fetch = new_candidates[:limit]
                            limit_skipped = new_candidates[limit:]

                            # 核心要点：将限额截断丢弃的候选 URL 立刻标记去重，防止循环重复
                            for c in limit_skipped:
                                if c.get("url"):
                                    tracker.mark_as_fetched(c["url"])

                            skipped_dedup = len(candidates) - len(new_candidates)
                            logger.info(
                                f"[两阶段] {source.type} | {truncate_url(source.src, 40)}: "
                                f"{len(to_fetch)}/{len(candidates)} 篇待抓取"
                                + (f"，跳过已抓取 {skipped_dedup} 篇" if skipped_dedup else "")
                                + (f"，自动标记超额弃用 {len(limit_skipped)} 篇" if limit_skipped else "")
                            )
                            res = fetcher.fetch_items(to_fetch)
                        else:
                            limit = fetcher.get_limit()
                            to_fetch = candidates[:limit]
                            logger.info(
                                f"[两阶段(无去重)] {source.type} | {truncate_url(source.src, 40)}: "
                                f"{len(to_fetch)}/{len(candidates)} 篇待抓取"
                            )
                            res = fetcher.fetch_items(to_fetch)
                else:
                    res = fetcher.fetch_with_retry()

                records = stop_task_buffer()
                return res, records
            except Exception as e:
                logger.error(f"抓取异常失败 {source.src}: {e}")
                res = FetchResult(source=source, articles=[], success=False, error=str(e))
                records = stop_task_buffer()
                return res, records

        max_workers = min(len(config.body), 20) if config.body else 1
        with concurrent.futures.ThreadPoolExecutor(max_workers=max_workers) as executor:
            future_to_source = {
                executor.submit(fetch_source_task, source): source
                for source in config.body
            }

            for future in future_to_source:
                source = future_to_source[future]
                try:
                    result, records = future.result()
                    results.append(result)
                    raw_counts[source] = len(result.articles) if result.success else 0

                    short_src = truncate_url(source.src, 40)
                    prefix = f"{source.type} | {short_src}"
                    flush_task_logs(prefix, records)

                    if not result.success:
                        error_log.append(f"[{source.type}] {source.src}: {result.error}")
                except Exception as e:
                    logger.error(f"线程执行失败 [{source.type}] {source.src}: {e}")
                    error_log.append(f"[{source.type}] {source.src}: {str(e)}")
                    res = FetchResult(source=source, articles=[], success=False, error=str(e))
                    results.append(res)
                    raw_counts[source] = 0

        # 3. 处理结果（去重、内容过滤处理）
        log_stage(3, 5, "去重与内容过滤处理")
        processed_results = process_results(results, tracker)

        # 4. 检查是否有新内容并生成 EPUB
        log_stage(4, 5, "检查新内容并生成 EPUB")
        if not has_new_content(processed_results):
            logger.info("未发现新文章内容，跳过 EPUB 生成。")
        else:
            epub_generator = EPUBGenerator(config)
            epub_path = epub_generator.generate(processed_results, error_log, start_time=start_time)

            # 5. 发送邮件与 WebDAV 上传
            log_stage(5, 5, "推送分发与保存记录")
            logger.info("正在发送 EPUB 至 Kindle 邮箱...")
            try:
                sender = SMTPSender()
                subject = config.title.get_plain_text()
                sender.send_epub(epub_path, subject)
            except Exception as e:
                logger.error(f"发送邮件失败: {e}")
                error_log.append(f"Email sending failed: {str(e)}")

            logger.info("正在上传 EPUB 至 WebDAV...")
            try:
                from src.uploader.webdav_uploader import WebDavUploader
                uploader = WebDavUploader()
                if uploader.upload_epub(epub_path):
                    logger.info("EPUB 成功上传至 WebDAV")
            except Exception as e:
                logger.error(f"WebDAV 上传失败: {e}")
                error_log.append(f"WebDAV upload failed: {str(e)}")

        # 始终保存去重数据库（确保 limit 截断标记以及新增抓取的记录得到持久化）
        logger.info("保存去重数据库...")
        tracker.save()

        # 6. 输出执行数据汇总表格
        summary_headers = ["#", "类型", "内容源 / URL", "状态", "抓取数", "新增数", "备注 / 错误"]
        summary_rows = []
        for idx, res in enumerate(processed_results, start=1):
            s = res.source
            raw_c = raw_counts.get(s, len(res.articles) if res.success else 0)
            new_c = len(res.articles) if res.success else 0
            if not res.success:
                status = "FAILED"
                note = truncate_url(res.error or "Unknown error", 30)
            elif new_c > 0:
                status = "SUCCESS"
                note = ""
            else:
                status = "SKIPPED"
                note = "无新文章"

            summary_rows.append([
                idx,
                s.type,
                truncate_url(s.src, 35),
                status,
                raw_c,
                new_c,
                note
            ])

        log_banner("执行数据汇总表")
        log_summary_table(summary_headers, summary_rows)

        stats = tracker.get_stats()
        logger.info(f"历史累计抓取: {stats['total_fetched']} | 本次新增入库: {stats['new_fetched']}")

    except Exception as e:
        logger.exception(f"Fatal error: {e}")
        sys.exit(1)


if __name__ == "__main__":
    main()

