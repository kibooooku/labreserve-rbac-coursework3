@echo off
chcp 65001 >nul
cd /d "%~dp0"
if not exist ".venv\Scripts\python.exe" (
  python -m venv .venv
  if errorlevel 1 goto failed
)
".venv\Scripts\python.exe" -m pip install -r requirements.txt
if errorlevel 1 goto failed
echo.
echo 系统地址 http://127.0.0.1:8783
echo 演示账号 student / teacher / keeper / admin / auditor / multi
echo 统一密码 Lab@2026!
echo 关闭此窗口或按 Ctrl+C 停止服务。
".venv\Scripts\python.exe" run.py
goto end
:failed
echo 启动失败，请确认 Python 3.11 或以上版本已安装并可连接依赖下载源。
:end
pause
