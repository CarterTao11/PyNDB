"""
pyNDB - 启动器
解决"单文件隐藏窗口"打包模式的三大问题:
1. 重复启动: 不再新建后台进程, 而是直接打开已有实例的页面 (单实例激活)
2. 隐藏进程退出难: 托盘图标(可选) 提供 打开界面/退出 菜单
3. 启动出错无处显示: 打包模式下用 Windows 弹窗提示

环境变量:
- PORT=7007               监听端口
- PYNDDB_NO_BROWSER=1     不自动打开浏览器
- PYNDDB_NO_TRAY=1        不使用托盘图标(打包模式默认启用托盘)
- PYNDDB_TRAY=1           源码运行时强制启用托盘(调试用)
"""
import logging
import os
import socket
import sys
import threading
import urllib.request
import webbrowser

from utils.runtime import data_dir

logger = logging.getLogger(__name__)


def _fatal(msg: str):
    """记录日志; 打包(无窗口)模式下同时弹窗告知用户"""
    logger.error(msg)
    try:
        if getattr(sys, 'frozen', False):
            import ctypes
            ctypes.windll.user32.MessageBoxW(0, msg, 'pyNDB', 0x10)
    except Exception:
        pass


def _port_free(port: int) -> bool:
    probe = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    try:
        probe.bind(('127.0.0.1', port))
        return True
    except OSError:
        return False
    finally:
        probe.close()


def _is_pyndb_alive(port: int) -> bool:
    """探测该端口上是否运行着 pyNDB 实例"""
    try:
        with urllib.request.urlopen(f'http://127.0.0.1:{port}/health', timeout=2) as resp:
            return resp.status == 200
    except Exception:
        return False


def _open_browser_later(url: str, delay: float = 1.0):
    def _open():
        try:
            webbrowser.open(url)
            logger.info('已打开浏览器: %s', url)
        except Exception as e:
            logger.warning('打开浏览器失败: %s', e)
    threading.Timer(delay, _open).start()


def launch(app, default_port: int = 7007):
    """统一入口: 单实例检查 -> 自动开浏览器 -> (可选)托盘运行"""
    data_dir()  # 确保数据目录存在
    port = int(os.environ.get('PORT', default_port))
    url = f'http://127.0.0.1:{port}/'

    # ---- 单实例: 端口被占时区分"自己人"和"别的程序" ----
    if not _port_free(port):
        if _is_pyndb_alive(port):
            # 已经有一个 pyNDB 在跑: 本次启动仅打开页面后退出, 不新建后台进程
            logger.info('pyNDB 已在运行 (端口 %s), 直接打开页面', port)
            _open_browser_later(url, delay=0.3)
            return
        _fatal(f'端口 {port} 已被其他程序占用, 无法启动。\n'
               f'如需换端口, 请设置环境变量 PORT 后重新启动。')
        sys.exit(1)

    # ---- 自动打开浏览器 ----
    if os.environ.get('PYNDDB_NO_BROWSER') != '1':
        _open_browser_later(url)

    # ---- 托盘模式: 打包后默认启用, 源码模式可用 PYNDDB_TRAY=1 调试 ----
    want_tray = (getattr(sys, 'frozen', False) and os.environ.get('PYNDDB_NO_TRAY') != '1') \
        or os.environ.get('PYNDDB_TRAY') == '1'
    if want_tray:
        try:
            _run_with_tray(app, port, url)
            return
        except ImportError:
            logger.info('未安装 pystray/pillow, 以普通模式启动 (无托盘图标)')

    logger.info('Starting pyNDB on port %s', port)
    app.run(host='127.0.0.1', port=port, debug=False, use_reloader=False)


def _run_with_tray(app, port: int, url: str):
    """托盘模式: 服务在后台线程, 托盘菜单提供 打开界面/退出"""
    import werkzeug.serving
    srv = werkzeug.serving.make_server('127.0.0.1', port, app, threaded=True)
    t = threading.Thread(target=srv.serve_forever, daemon=True)
    t.start()
    logger.info('pyNDB 已后台运行: %s (可从托盘图标退出)', url)

    import pystray
    from PIL import Image, ImageDraw

    def _make_icon():
        img = Image.new('RGB', (64, 64), '#007acc')
        d = ImageDraw.Draw(img)
        for top in (14, 28, 42):  # 三条横杠模拟数据库
            d.rectangle([8, top, 55, top + 10], fill='white')
        return img

    def _on_open(icon, item):
        webbrowser.open(url)

    def _on_quit(icon, item):
        logger.info('收到退出请求, 正在停止服务...')
        srv.shutdown()
        icon.stop()

    menu = pystray.Menu(
        pystray.MenuItem('打开界面', _on_open, default=True),  # 双击托盘=打开界面
        pystray.MenuItem('退出', _on_quit),
    )
    icon = pystray.Icon('pyNDB', _make_icon(), 'pyNDB 数据库管理', menu)
    icon.run()
    t.join(timeout=5)
    logger.info('pyNDB 已退出')
