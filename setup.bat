@echo off
setlocal EnableExtensions EnableDelayedExpansion
cd /d "%~dp0"

echo USB chat setup
echo Needs Python 3.11 or newer. Will not replace or upgrade the system interpreter.
echo.

set "PY="
set "FOUND=none"

call :try py -3.13
if not defined PY call :try py -3.12
if not defined PY call :try py -3.11
if not defined PY call :try py -3
if not defined PY call :try python
if not defined PY call :try python3
if not defined PY call :try py -2
if not defined PY call :try python2

if defined PY (
  echo Using compatible interpreter: !PY!
  !PY! "%~dp0setup.py"
  exit /b !ERRORLEVEL!
)

if /I "!FOUND!"=="none" (
  set "USBCHAT_MSG=USB chat needs Python 3.11 or newer to run. This PC has no Python on PATH. The setup will not install or replace a system Python. Install Python 3.11 or newer alongside any existing projects, then run setup.bat again."
) else (
  set "USBCHAT_MSG=USB chat needs Python 3.11 or newer to run. This PC has Python !FOUND!. That interpreter will not be replaced or upgraded, so other projects keep using it. Install Python 3.11 or newer alongside, then run setup.bat again."
)
echo !USBCHAT_MSG!
echo.
powershell -NoProfile -Command "Add-Type -AssemblyName System.Windows.Forms; [void][System.Windows.Forms.MessageBox]::Show($env:USBCHAT_MSG, 'USB chat setup', 'OK', 'Warning')"
exit /b 1

:try
set "CAND=%*"
%CAND% -c "import sys; print('%%d.%%d.%%d' %% sys.version_info[:3])" >"%TEMP%\usbchat_ver.txt" 2>nul
if errorlevel 1 goto :eof
set /p VER=<"%TEMP%\usbchat_ver.txt"
if "!FOUND!"=="none" set "FOUND=!VER!"
%CAND% -c "import sys; raise SystemExit(0 if sys.version_info>=(3,11) else 1)" >nul 2>nul
if errorlevel 1 goto :eof
if not defined PY set "PY=%CAND%"
goto :eof
