@echo off
setlocal
cd /d "%~dp0"
title DVS AI Alpha 4.1.0-C - Outcome Analytics Export
if exist ".venv\Scripts\python.exe" (
  ".venv\Scripts\python.exe" EXPORT_OUTCOME_ANALYTICS.py
) else (
  python EXPORT_OUTCOME_ANALYTICS.py
)
echo.
pause
