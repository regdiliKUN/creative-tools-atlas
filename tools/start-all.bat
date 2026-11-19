@echo off
rem Creator Atlas - start everything the one-click executor needs (manual only, no autostart).
rem   1) local tool bridge (port 7843)   2) ComfyUI portable (port 8188)   3) open the studio
rem ASCII-only source: cmd mis-parses UTF-8 batch lines.
rem Everything is also written to start-all.log next to this file (for troubleshooting).
setlocal
set LOG=%~dp0start-all.log
echo Starting the tool bridge and ComfyUI, please wait (10-40 seconds) ...
echo The full result will be shown here when it is done.
call :main > "%LOG%" 2>&1
type "%LOG%"
echo.
pause
exit /b

:main
echo [start-all] %date% %time%
set COMFY=I:\workbuddy\AI-Engine\portable\ComfyUI_windows_portable

echo [1/3] Tool bridge ...
powershell -NoProfile -ExecutionPolicy Bypass -File "%~dp0start-tool-bridge.ps1"
rem A bridge started before an update keeps running old code: if its code stamp differs from the files on disk, restart it.
powershell -NoProfile -ExecutionPolicy Bypass -File "%~dp0check-bridge-fresh.ps1"
if %errorlevel%==0 goto bridge_ok
echo Restarting the bridge so it runs the current code ...
powershell -NoProfile -ExecutionPolicy Bypass -File "%~dp0start-tool-bridge.ps1" -Stop
powershell -NoProfile -ExecutionPolicy Bypass -File "%~dp0start-tool-bridge.ps1"
powershell -NoProfile -ExecutionPolicy Bypass -File "%~dp0check-bridge-fresh.ps1"
if %errorlevel%==0 goto bridge_ok
echo BRIDGE_PAGE_FAILED - the bridge cannot serve the studio page; see tool-bridge.log
goto comfy
:bridge_ok
echo BRIDGE_OK

:comfy
echo [2/3] ComfyUI ...
powershell -NoProfile -Command "try { Invoke-RestMethod 'http://127.0.0.1:8188/system_stats' -TimeoutSec 2 | Out-Null; exit 0 } catch { exit 1 }"
if %errorlevel%==0 goto comfy_running
if not exist "%COMFY%\python_embeded\python.exe" goto comfy_missing
rem --cache-classic: the default RAM-pressure cache drops the loaded checkpoint when free RAM is low,
rem   so the next workflow loads a second copy (VRAM fills up, variants stall). Classic cache reuses it.
rem --disable-dynamic-vram: ComfyUI 0.45 streams weights from disk every step by default ("dynamic VRAM").
rem On this machine (24GB GPU) one SDXL step took 148s while the same disk was busy; load whole models into VRAM instead.
rem Start-Process (not cmd start) so ComfyUI gets its own console and does not inherit the log redirection.
powershell -NoProfile -Command "Start-Process -FilePath '%COMFY%\python_embeded\python.exe' -ArgumentList '-s','ComfyUI\main.py','--windows-standalone-build','--disable-auto-launch','--disable-dynamic-vram','--cache-classic' -WorkingDirectory '%COMFY%' -WindowStyle Minimized"
echo COMFYUI_STARTING  (minimized window; first start takes about 30 seconds)
goto open
:comfy_running
echo COMFYUI_ALREADY_RUNNING
goto open
:comfy_missing
echo COMFYUI_NOT_FOUND: %COMFY%

:open
echo [3/3] Opening the studio: http://127.0.0.1:7843/studio.html
rem Opened from the bridge (same origin) so the security check passes; file:// pages never send a Referer.
start "" "http://127.0.0.1:7843/studio.html"
echo If ComfyUI is still loading, wait about 30 seconds and click "Refresh status" on the page.
exit /b 0
