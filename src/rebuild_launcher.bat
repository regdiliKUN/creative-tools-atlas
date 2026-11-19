@echo off
rem Rebuild the desktop launcher exe (ASCII-only: cmd mis-parses UTF-8 batch lines)
cd /d "%~dp0"
python rebuild_launcher.py
echo.
pause
