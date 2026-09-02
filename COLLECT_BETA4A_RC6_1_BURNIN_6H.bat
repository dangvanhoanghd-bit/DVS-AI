@echo off
setlocal
cd /d "%~dp0"
title DVS AI Beta 4A RC6.1 - Burn-in Evidence Collector

echo ==================================================
echo  DVS AI Beta 4A RC6.1 - Thu thap burn-in 6 gio
echo  Hay giu phan mem DVS AI dang chay trong luc nay.
echo ==================================================

python beta4a_burnin_collector.py --duration-minutes 360 --interval-seconds 60 --runtime-dir artifacts\runtime
if errorlevel 1 (
  echo.
  echo Collector gap loi. Hay gui anh man hinh va file log.
  pause
  exit /b 1
)

echo.
echo Da hoan tat. Gui file ZIP moi nhat trong artifacts\beta4a_burnin\
pause
