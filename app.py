"""
pyNDB - 数据库管理工具
主应用入口
"""
import logging
import os
import sys
from flask import Flask, render_template, request
from api.routes import api
from utils.log_config import setup_logging
from utils.runtime import resource_dir

# 初始化日志:控制台 + logs/pyndb.log 同时输出
logger = setup_logging()

# 模板等只读资源: 源码=项目目录, PyInstaller打包=_MEIPASS 解压目录
app = Flask(__name__,
            template_folder=os.path.join(resource_dir(), 'templates'),
            static_folder=os.path.join(resource_dir(), 'static'))
app.secret_key = os.urandom(24)

# 注册蓝图
app.register_blueprint(api)

# 请求日志中间件
@app.before_request
def before_request():
    logger.info("> %s %s", request.method, request.path)


@app.after_request
def after_request(response):
    logger.info("< %s %s - %s", request.method, request.path, response.status_code)
    return response

@app.route('/')
def index():
    return render_template('index.html')


@app.route('/health')
def health():
    return {'status': 'ok'}

# 测试日志端点
@app.route('/test-log')
def test_log():
    logger.info('Test log endpoint called')
    return {'message': 'logged'}


if __name__ == '__main__':
    from utils.launcher import launch
    launch(app)
