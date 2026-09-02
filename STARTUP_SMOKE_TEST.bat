@echo off
setlocal
cd /d "%~dp0"
set QT_QPA_PLATFORM=offscreen
python startup_smoke_test.py
if errorlevel 1 (
  echo.
  echo [FAIL] Startup smoke test failed.
  pause
  exit /b 1
)
echo.
echo [PASS] DVS AI Alpha 2.18.1 startup smoke test passed.
pause
