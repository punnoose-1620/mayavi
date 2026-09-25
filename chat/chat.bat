@echo off
setlocal EnableExtensions
cd /d "%~dp0"

if exist "%~dp0..\.venv\Scripts\python.exe" (
  "%~dp0..\.venv\Scripts\python.exe" "%~dp0chat.py" %*
  exit /b %ERRORLEVEL%
)

where py >nul 2>nul
if %ERRORLEVEL%==0 (
  py -3 "%~dp0chat.py" %*
  exit /b %ERRORLEVEL%
)

python "%~dp0chat.py" %*
exit /b %ERRORLEVEL%
