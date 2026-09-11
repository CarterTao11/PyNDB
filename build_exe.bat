@echo off
chcp 65001 >nul
cd /d %~dp0

set PY=python
if exist ".venv\Scripts\python.exe" set PY=.venv\Scripts\python.exe

echo === pyNDB 打包: 单文件 + 隐藏窗口 (使用 %PY%) ===
%PY% -m pip install --quiet --disable-pip-version-check pyinstaller pystray pillow || goto :err
%PY% -m PyInstaller --clean --noconfirm pyNDB.spec || goto :err

echo.
echo 打包完成: dist\pyNDB.exe
echo 运行说明:
echo   - 双击启动, 自动打开浏览器; 再次双击只打开页面, 不会重复起进程
echo   - 托盘图标: 双击=打开界面, 右键=退出
echo   - data\ 和 logs\ 生成在 exe 同目录, 升级前注意备份 data\
pause
exit /b 0

:err
echo 打包失败, 请检查上方错误信息
pause
exit /b 1
