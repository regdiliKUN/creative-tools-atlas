@echo off
setlocal
cd /d I:\workbuddy\.creative-atlas-build
rem Round 12: run all gates (ASCII-only: cmd mis-parses UTF-8 batch lines)
set PY=python
where python >nul 2>nul || set PY=I:\workbuddy\AI-Engine\portable\ComfyUI_windows_portable\python_embeded\python.exe
set PYTHONIOENCODING=utf-8
(
echo ===== build_manifest
%PY% build_manifest.py
echo ===== selftest [expect 28/28]
%PY% selftest.py
echo ===== v10_verify [expect 36/36]
%PY% v10_verify.py
echo ===== v11_verify [expect 21/21]
%PY% v11_verify.py
echo ===== test_e2e_automation [expect 7/7]
%PY% test_e2e_automation.py
echo ===== test_automation.js [expect JOB_SPEC_OK]
node test_automation.js
echo ===== verify_exec_buttons.js [expect BUTTON_RENDER_OK]
node verify_exec_buttons.js
) > gates_result.log 2>&1
findstr /C:"=====" /C:"RESULT" /C:"FAIL" /C:"_OK" gates_result.log
echo.
echo Full log: I:\workbuddy\.creative-atlas-build\gates_result.log
pause
