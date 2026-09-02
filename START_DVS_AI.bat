@echo off
setlocal
cd /d "%~dp0"
title DVS AI V2.4.3 - Process Lifetime Forensics Supervisor

echo ==========================================
echo   DVS AI - Process Lifetime Forensics
 echo   External supervisor enabled
 echo ==========================================
echo.

where python >nul 2>nul
if errorlevel 1 (
    echo [ERROR] Khong tim thay Python trong PATH.
    echo Hay cai Python va chon "Add Python to PATH".
    pause
    exit /b 1
)

python -c "import PySide6, pandas, ccxt" >nul 2>nul
if errorlevel 1 (
    echo Dang cai thu vien can thiet...
    python -m pip install -r requirements.txt
    if errorlevel 1 (
        echo [ERROR] Cai thu vien that bai.
        pause
        exit /b 1
    )
)

echo Dang khoi dong DVS AI qua PLF supervisor...
python plf_supervisor.py
set "DVS_EXIT=%ERRORLEVEL%"

echo.
if not "%DVS_EXIT%"=="0" (
    echo [WARNING] DVS AI ket thuc voi exit code %DVS_EXIT%.
    echo Kiem tra artifacts\process_lifetime\plf_session_*.json
) else (
    echo DVS AI da ket thuc binh thuong.
)
echo.
pause
endlocal & exit /b %DVS_EXIT%
