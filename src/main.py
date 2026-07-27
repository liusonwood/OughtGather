#!/usr/bin/env python3
"""
Ought Gather 主入口
自动化信息聚合工具
"""

import sys
import os
import time
import concurrent.futures
from typing import List, Tuple

# 添加项目根目录到 Python 路径
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from src.config import load_config, Config, ContentSource
from src.fetchers import BaseFetcher, FetchResult, get_fetcher_class
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


def process_results(results: List[FetchResult], tracker: DedupTracker) -> List[FetchResult]:
    """
    处理抓取结果（去重、内容处理）

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

        # 过滤已抓取的文章（trending/web 使用带日期的哈希，每日刷新）
        original_count = len(result.articles)
        new_articles = []
        for article in result.articles:
            if not tracker.is_fetched(article.url, article.title, article.published_date):
                # 只要读取就标记为已处理，无论后续处理是否成功
                tracker.mark_as_fetched(article.url, article.title, article.published_date)

                # 应用内容处理规则，处理失败则保留原文
                try:
                    processor = ContentProcessor(result.source)
                    article = processor.process(article)
                except Exception as e:
                    logger.error(
                        f"[{prefix}] 处理文章 '{article.title}' 失败: {e}，保留原始文章内容"
                    )
                new_articles.append(article)
            else:
                logger.debug(f"[{prefix}] 跳过已抓取文章: {article.title}")

        # 更新结果
        result.articles = new_articles
        processed_results.append(result)

        logger.info(
            f"[{prefix}] 内容处理完成: {len(new_articles)}/{original_count} 篇新文章"
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


def main():
    """主函数"""
    logger = get_logger()
    start_time = time.time()

    log_banner("Ought Gather - 自动化信息聚合工具")

    try:
        # 1. 加载配置与去重记录
        log_stage(1, 5, "加载配置与初始化去重追踪器")
        config = load_config()
        logger.info(f"成功加载 {len(config.body)} 个内容源配置")
        tracker = DedupTracker()

        # 2. 抓取内容（并发处理 + 任务日志隔离缓冲）
        log_stage(2, 5, "并发抓取内容源（开启独立日志缓冲）")
        results: List[FetchResult] = []
        error_log: List[str] = []
        # 用于保存 (source, raw_count) 便于结尾计算
        raw_counts = {}

        def fetch_source_task(source: ContentSource) -> Tuple[FetchResult, List[Tuple[int, str]]]:
            start_task_buffer()
            try:
                fetcher = get_fetcher(source, global_limit=config.limit)
                res = fetcher.fetch_with_retry()
                records = stop_task_buffer()
                return res, records
            except Exception as e:
                logger.error(f"抓取异常失败 {source.src}: {e}")
                res = FetchResult(source=source, articles=[], success=False, error=str(e))
                records = stop_task_buffer()
                return res, records

        max_workers = min(len(config.body), 10) if config.body else 1
        with concurrent.futures.ThreadPoolExecutor(max_workers=max_workers) as executor:
            future_to_source = {
                executor.submit(fetch_source_task, source): source
                for source in config.body
            }

            # 按 config.body 原始顺序收集并一次性刷写每个源的完整日志，保证日志顺序连续不交错
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
            logger.info("未发现新文章内容，跳过 EPUB 生成并退出。")
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
