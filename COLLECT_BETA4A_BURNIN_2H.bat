@echo off
setlocal
cd /d "%~dp0"
title DVS AI Beta 4A - Burn-in Evidence Collector

echo =====================================================
echo   DVS AI Beta 4A - Thu thap bang chung burn-in 2 gio

echo   Hay giu phan mem DVS AI dang chay trong luc nay.
echo =====================================================
echo.
python beta4a_burnin_collector.py --duration-minutes 120 --interval-seconds 60
if errorlevel 1 (
  echo.
  echo [ERROR] Thu thap burn-in that bai.
  pause
  exit /b 1
)
echo.
echo Da tao file ZIP trong artifacts\beta4a_burnin\
pause
endlocal
