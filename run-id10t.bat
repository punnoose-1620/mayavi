@echo off
setlocal
cd /d "%~dp0"
title Mayavi ui
set PYTHONUNBUFFERED=1
set PYTHONIOENCODING=utf-8

set PY=python
if exist ".venv\Scripts\python.exe" set PY=.venv\Scripts\python.exe

echo Starting Mayavi on http://127.0.0.1:9001/
echo Close this window to stop the server.
echo.
start "" cmd /c "timeout /t 2 /nobreak >nul & start http://127.0.0.1:9001/"
"%PY%" -u app.py --port 9001
echo.
echo Exit code: %ERRORLEVEL%
pause
