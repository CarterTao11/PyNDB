"""
pyNDB - 数据库管理工具
启动脚本
"""
import os
import sys
import logging

# 添加当前目录到Python路径
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from utils.log_config import setup_logging

# 在导入app之前配置日志:控制台 + logs/pyndb.log 同时输出
setup_logging()
logger = logging.getLogger(__name__)

log_file = os.path.join(os.path.dirname(__file__), 'logs', 'pyndb.log')

logger.info('Server starting...')

from app import app

if __name__ == '__main__':
    from utils.launcher import launch
    launch(app)
