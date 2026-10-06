@echo off
setlocal EnableExtensions
cd /d "%~dp0"

set "VPY=%LOCALAPPDATA%\usb-chat\venv\Scripts\python.exe"
if exist "%VPY%" (
  "%VPY%" "%~dp0scripts\chat.py" %*
  exit /b %ERRORLEVEL%
)

set "USBCHAT_MSG=USB chat is not set up on this PC. Run setup.bat first. It will use Python 3.11 or newer in a private host venv and will not change the system Python."
echo %USBCHAT_MSG%
powershell -NoProfile -Command "Add-Type -AssemblyName System.Windows.Forms; [void][System.Windows.Forms.MessageBox]::Show($env:USBCHAT_MSG, 'USB chat', 'OK', 'Warning')"
exit /b 1
