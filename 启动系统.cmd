@echo off
setlocal DisableDelayedExpansion
set "PYTHONUTF8=1"
cd /d "%~dp0"
if errorlevel 1 goto folder_failed

if exist ".venv\Scripts\python.exe" goto check_environment

where py >nul 2>&1
if errorlevel 1 goto use_python
py -3 -c "import sys; raise SystemExit(sys.version_info < (3, 11))" >nul 2>&1
if errorlevel 1 goto use_python
py -3 -m venv .venv
if errorlevel 1 goto failed
goto check_environment

:use_python
python -c "import sys; raise SystemExit(sys.version_info < (3, 11))" >nul 2>&1
if errorlevel 1 goto python_missing
python -m venv .venv
if errorlevel 1 goto failed

:check_environment
".venv\Scripts\python.exe" -c "import sys; raise SystemExit(sys.version_info < (3, 11))" >nul 2>&1
if errorlevel 1 goto environment_failed
".venv\Scripts\python.exe" -c "import flask; from importlib.metadata import version; raise SystemExit(version('Flask') != '3.1.3')" >nul 2>&1
if not errorlevel 1 goto start_server
echo Installing project requirements...
".venv\Scripts\python.exe" -m pip install -r "%~dp0requirements.txt"
if errorlevel 1 goto failed

:start_server
echo.
echo Starting LabReserve. Default address: http://127.0.0.1:8783
echo Accounts: student / teacher / keeper / admin / auditor / multi
echo Password: Lab@2026!
echo Keep this window open. Press Ctrl+C to stop the server.
echo.
".venv\Scripts\python.exe" "%~dp0run.py" %*
set "launcher_exit=%errorlevel%"
if not "%launcher_exit%"=="0" goto server_failed
exit /b 0

:folder_failed
echo Cannot open the project folder.
goto failed
:python_missing
echo Python 3.11 or newer is required. Install Python and add it to PATH.
goto failed
:environment_failed
echo The existing .venv is unavailable or uses an unsupported Python version.
echo Recreate it with Python 3.11 or newer, then run this launcher again.
goto failed
:server_failed
echo.
echo Server exited with an error. Review the message above.
pause
exit /b %launcher_exit%
:failed
echo.
echo Startup failed. Review the message above.
pause
exit /b 1
