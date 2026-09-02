@echo off
setlocal
cd /d "%~dp0"
python EXPORT_LEARNING_DATASET.py
pause
endlocal
