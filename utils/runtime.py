"""
pyNDB - 运行时路径工具
兼容两种运行方式:
- 源码运行:   python run.py            -> 一切以项目根目录为准
- PyInstaller --onefile 打包:          -> 可写数据在 exe 旁边, 只读资源在 _MEIPASS
"""
import os
import sys


def is_frozen() -> bool:
    """是否运行在 PyInstaller 打包环境中"""
    return getattr(sys, 'frozen', False)


def base_dir() -> str:
    """可写数据根目录: 打包后=exe所在目录, 源码运行=项目根目录"""
    if is_frozen():
        return os.path.dirname(sys.executable)
    return os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def resource_dir() -> str:
    """只读资源目录(templates等): 打包后=sys._MEIPASS 解压目录, 源码=项目根目录"""
    if is_frozen():
        return getattr(sys, '_MEIPASS', os.path.dirname(sys.executable))
    return os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def data_dir() -> str:
    """data 目录(数据库/密钥), 自动创建"""
    d = os.path.join(base_dir(), 'data')
    os.makedirs(d, exist_ok=True)
    return d


def logs_dir() -> str:
    """logs 目录, 自动创建"""
    d = os.path.join(base_dir(), 'logs')
    os.makedirs(d, exist_ok=True)
    return d
