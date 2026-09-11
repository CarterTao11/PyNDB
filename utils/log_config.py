"""
pyNDB - 统一日志配置
控制台 + 文件 双输出,所有模块的 logger 自动生效
"""
import logging
import os
import sys
from logging.handlers import RotatingFileHandler

from utils.runtime import logs_dir

LOG_FORMAT = '%(asctime)s [%(levelname)s] %(name)s: %(message)s'
DATE_FORMAT = '%Y-%m-%d %H:%M:%S'

_configured = False


def setup_logging(level=logging.INFO, log_file=None):
    """
    配置根 logger:控制台输出 + logs/pyndb.log 文件输出(滚动,1MB x 5)。
    幂等:重复调用不会叠加 handler。
    打包为无窗口程序时 (stdout/stderr 为 None) 自动跳过控制台输出。
    """
    global _configured
    root = logging.getLogger()
    if _configured:
        return root

    log_dir = logs_dir()
    if log_file is None:
        log_file = os.path.join(log_dir, 'pyndb.log')

    root.setLevel(level)
    formatter = logging.Formatter(LOG_FORMAT, DATE_FORMAT)

    # 1. 控制台输出 (无窗口打包模式下 sys.stdout 为 None, 跳过)
    if sys.stdout is not None or sys.stderr is not None:
        console = logging.StreamHandler(sys.stdout if sys.stdout is not None else sys.stderr)
        console.setFormatter(formatter)
        root.addHandler(console)

    # 2. 文件输出
    file_handler = RotatingFileHandler(
        log_file, maxBytes=1024 * 1024, backupCount=5, encoding='utf-8'
    )
    file_handler.setFormatter(formatter)
    root.addHandler(file_handler)

    _configured = True
    return root
