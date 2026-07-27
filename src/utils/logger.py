"""
日志系统模块
提供统一、高可读性、支持并发线程解耦与终端彩色的日志功能
"""

import logging
import os
import sys
import threading
import unicodedata
from datetime import datetime
from zoneinfo import ZoneInfo
from typing import Optional, List, Tuple, Any

# 默认时区：北京时间 UTC+8
DEFAULT_TZ = ZoneInfo("Asia/Shanghai")


def string_width(s: str) -> int:
    """计算字符串的视觉显示宽度（处理中英文混合宽字符）"""
    width = 0
    for char in str(s):
        if unicodedata.east_asian_width(char) in ('F', 'W'):
            width += 2
        else:
            width += 1
    return width


def pad_string(s: str, target_width: int, align: str = 'left') -> str:
    """按视觉宽度填充字符串"""
    s_str = str(s)
    w = string_width(s_str)
    padding = max(0, target_width - w)
    if align == 'right':
        return ' ' * padding + s_str
    elif align == 'center':
        left = padding // 2
        right = padding - left
        return ' ' * left + s_str + ' ' * right
    else:
        return s_str + ' ' * padding


def truncate_url(url: str, max_length: int = 80) -> str:
    """截断超长 URL / 文本，保留可读前缀与后缀"""
    if not url or len(url) <= max_length:
        return url
    half = (max_length - 5) // 2
    return f"{url[:half]}...{url[-half:]}"


class ColoredFormatter(logging.Formatter):
    """终端彩色控制台日志格式化器"""

    # ANSI 颜色转义码
    COLORS = {
        logging.DEBUG: "\033[36m",     # 青色
        logging.INFO: "\033[32m",      # 绿色
        logging.WARNING: "\033[33m",   # 黄色
        logging.ERROR: "\033[31m",     # 红色
        logging.CRITICAL: "\033[35;1m" # 紫色粗体
    }
    RESET = "\033[0m"

    def format(self, record: logging.LogRecord) -> str:
        # 复制 record 以免影响其他 handler
        log_fmt = "%(asctime)s | %(levelname)-7s | %(message)s"
        formatter = logging.Formatter(log_fmt, self.datefmt)
        formatted_message = formatter.format(record)

        # 判断是否在终端输出，若是则加色彩
        if sys.stdout.isatty():
            color = self.COLORS.get(record.levelno, "")
            if color:
                # 给日志级别部分着色
                level_str = record.levelname.ljust(7)
                colored_level = f"{color}{level_str}{self.RESET}"
                formatted_message = formatted_message.replace(level_str, colored_level, 1)

        return formatted_message


class TaskLogBuffer:
    """线程/任务独立的日志缓冲区，防止并发日志错乱"""

    _thread_buffers = {}
    _lock = threading.Lock()

    @classmethod
    def start(cls) -> 'TaskLogBuffer':
        """开始当前线程的日志缓冲"""
        buf = TaskLogBuffer()
        thread_id = threading.get_ident()
        with cls._lock:
            cls._thread_buffers[thread_id] = buf
        return buf

    @classmethod
    def stop(cls) -> List[Tuple[int, str]]:
        """停止当前线程的日志缓冲，并返回捕获的所有日志记录 [(level, message)]"""
        thread_id = threading.get_ident()
        with cls._lock:
            buf = cls._thread_buffers.pop(thread_id, None)
            return buf.records if buf else []

    @classmethod
    def get_current(cls) -> Optional['TaskLogBuffer']:
        """获取当前线程的日志缓冲区"""
        thread_id = threading.get_ident()
        with cls._lock:
            return cls._thread_buffers.get(thread_id)

    def __init__(self):
        self.records: List[Tuple[int, str]] = []

    def record(self, level: int, msg: str):
        self.records.append((level, msg))


class TaskBufferHandler(logging.Handler):
    """日志 Handler：当当前线程开启了 TaskLogBuffer 时，将日志定向截获到缓冲区"""

    def emit(self, record: logging.LogRecord):
        buf = TaskLogBuffer.get_current()
        if buf:
            try:
                msg = self.format(record)
                buf.record(record.levelno, msg)
            except Exception:
                self.handleError(record)


class Logger:
    """单例日志记录器"""

    _instance: Optional['Logger'] = None
    _logger: Optional[logging.Logger] = None

    def __new__(cls):
        if cls._instance is None:
            cls._instance = super().__new__(cls)
            cls._instance._initialize()
        return cls._instance

    def _initialize(self):
        """初始化日志系统"""
        log_dir = "logs"
        os.makedirs(log_dir, exist_ok=True)

        log_file = os.path.join(
            log_dir,
            f"gather_{datetime.now(DEFAULT_TZ).strftime('%Y%m%d_%H%M%S')}.log"
        )

        log_format = "%(asctime)s | %(levelname)-7s | %(message)s"
        date_format = "%Y-%m-%d %H:%M:%S"

        self._logger = logging.getLogger("ought_gather")
        self._logger.setLevel(logging.DEBUG)

        if not self._logger.handlers:
            # 1. 任务缓冲 Handler (最高优先级)
            buffer_handler = TaskBufferHandler()
            buffer_handler.setLevel(logging.DEBUG)
            # plain msg format for task buffer
            buffer_formatter = logging.Formatter("%(message)s")
            buffer_handler.setFormatter(buffer_formatter)
            self._logger.addHandler(buffer_handler)

            # 2. 文件 Handler (按文件无色彩对齐)
            file_handler = logging.FileHandler(log_file, encoding='utf-8')
            file_handler.setLevel(logging.DEBUG)
            file_formatter = logging.Formatter(log_format, date_format)
            file_handler.setFormatter(file_formatter)
            self._logger.addHandler(file_handler)

            # 3. 控制台 Handler (支持 ANSI 彩色)
            console_handler = logging.StreamHandler(sys.stdout)
            console_handler.setLevel(logging.INFO)
            console_formatter = ColoredFormatter(log_format, date_format)
            console_handler.setFormatter(console_formatter)
            self._logger.addHandler(console_handler)

    def get_logger(self) -> logging.Logger:
        return self._logger


def get_logger() -> logging.Logger:
    """获取全局日志记录器"""
    return Logger().get_logger()


def start_task_buffer() -> TaskLogBuffer:
    """开启当前线程的日志缓冲"""
    return TaskLogBuffer.start()


def stop_task_buffer() -> List[Tuple[int, str]]:
    """结束当前线程的日志缓冲并获取捕获到的日志"""
    return TaskLogBuffer.stop()


def flush_task_logs(prefix: str, records: List[Tuple[int, str]]):
    """将缓冲的日志记录顺序刷写入全局 Logger，带上统一的源前缀"""
    logger = get_logger()
    for level, msg in records:
        logger.log(level, f"[{prefix}] {msg}")


def log_stage(stage_num: int, total_stages: int, title: str):
    """记录阶段划分符"""
    logger = get_logger()
    sep = "=" * 60
    logger.info(sep)
    logger.info(f"[{stage_num}/{total_stages}] {title}")
    logger.info(sep)


def log_banner(title: str):
    """记录标题横幅"""
    logger = get_logger()
    sep = "=" * 60
    logger.info(sep)
    logger.info(title)
    logger.info(sep)


def log_summary_table(headers: List[str], rows: List[List[Any]]):
    """输出美观且中英文对齐的 ASCII 总结表格"""
    if not rows:
        return

    logger = get_logger()
    str_rows = [[str(cell) for cell in row] for row in rows]

    # 计算每列的最大显示宽度
    col_widths = [string_width(h) for h in headers]
    for row in str_rows:
        for idx, cell in enumerate(row):
            if idx < len(col_widths):
                col_widths[idx] = max(col_widths[idx], string_width(cell))

    # 构建表格分隔线
    border_line = "+" + "+".join("-" * (w + 2) for w in col_widths) + "+"

    # 表头
    header_cells = [f" {pad_string(h, col_widths[i], 'center')} " for i, h in enumerate(headers)]
    header_line = "|" + "|".join(header_cells) + "|"

    logger.info(border_line)
    logger.info(header_line)
    logger.info(border_line)

    # 数据行
    for row in str_rows:
        row_cells = []
        for i, cell in enumerate(row):
            w = col_widths[i]
            # 数字或状态居中/居右，其他居左
            align = 'center' if cell in ('SUCCESS', 'FAILED', 'PARTIAL', 'SKIPPED') or cell.isdigit() else 'left'
            row_cells.append(f" {pad_string(cell, w, align)} ")
        logger.info("|" + "|".join(row_cells) + "|")

    logger.info(border_line)


# 便捷日志函数
def debug(message: str):
    get_logger().debug(message)


def info(message: str):
    get_logger().info(message)


def warning(message: str):
    get_logger().warning(message)


def error(message: str):
    get_logger().error(message)


def critical(message: str):
    get_logger().critical(message)


def exception(message: str):
    get_logger().exception(message)
