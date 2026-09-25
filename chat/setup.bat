@echo off
setlocal EnableExtensions
cd /d "%~dp0"

echo USB chat setup
echo This PC needs Python 3.11+ and llama-cpp-python, or llama-cli in chat\bin\
echo This script will not create a venv on the USB stick.
echo.

set "PY="
where py >nul 2>nul
if %ERRORLEVEL%==0 (
  py -3 -c "import sys; raise SystemExit(0 if sys.version_info >= (3, 11) else 1)" >nul 2>nul
  if %ERRORLEVEL%==0 set "PY=py -3"
)

if not defined PY (
  where python >nul 2>nul
  if %ERRORLEVEL%==0 (
    python -c "import sys; raise SystemExit(0 if sys.version_info >= (3, 11) else 1)" >nul 2>nul
    if %ERRORLEVEL%==0 set "PY=python"
  )
)

if not defined PY (
  echo Python 3.11+ was not found on PATH.
  echo Install it from https://www.python.org/downloads/ and tick "Add python.exe to PATH".
  echo Then run setup.bat again.
  echo This script cannot install Python for you.
  exit /b 1
)

%PY% "%~dp0setup.py"
exit /b %ERRORLEVEL%
