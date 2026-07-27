import logging
import pytest
from src.utils.logger import (
    string_width,
    pad_string,
    truncate_url,
    ColoredFormatter,
    TaskLogBuffer,
    start_task_buffer,
    stop_task_buffer,
    flush_task_logs,
    log_stage,
    log_banner,
    log_summary_table,
    get_logger,
)


def test_string_width_and_pad():
    assert string_width("abc") == 3
    assert string_width("测试") == 4
    assert string_width("AI测试123") == 9

    assert pad_string("test", 8, "left") == "test    "
    assert pad_string("test", 8, "right") == "    test"
    assert pad_string("test", 8, "center") == "  test  "


def test_truncate_url():
    short = "https://sspai.com/feed"
    assert truncate_url(short, max_length=50) == short

    long_url = "https://example.com/very/long/path/name/with/extra/parameters?token=1234567890abcdef"
    truncated = truncate_url(long_url, max_length=30)
    assert len(truncated) <= 30
    assert "..." in truncated


def test_colored_formatter():
    formatter = ColoredFormatter("%(asctime)s | %(levelname)-7s | %(message)s")
    record = logging.LogRecord("test", logging.INFO, "path", 1, "test message", (), None)
    formatted = formatter.format(record)
    assert "INFO" in formatted
    assert "test message" in formatted


def test_task_log_buffer_and_flush(caplog):
    # 开启任务日志缓冲
    start_task_buffer()
    logger = get_logger()

    logger.info("Thread log line 1")
    logger.warning("Thread log line 2")

    records = stop_task_buffer()
    assert len(records) == 2
    assert records[0] == (logging.INFO, "Thread log line 1")
    assert records[1] == (logging.WARNING, "Thread log line 2")

    # 测试刷写
    with caplog.at_level(logging.INFO):
        flush_task_logs("rss | sspai.com", records)

    assert "[rss | sspai.com] Thread log line 1" in caplog.text
    assert "[rss | sspai.com] Thread log line 2" in caplog.text


def test_log_stage_banner_table(caplog):
    with caplog.at_level(logging.INFO):
        log_stage(1, 5, "阶段测试")
        log_banner("横幅测试")
        headers = ["#", "源", "状态"]
        rows = [[1, "sspai", "SUCCESS"]]
        log_summary_table(headers, rows)

    assert "[1/5] 阶段测试" in caplog.text
    assert "横幅测试" in caplog.text
    assert "| # |  源   |  状态   |" in caplog.text
    assert "| 1 | sspai | SUCCESS |" in caplog.text
