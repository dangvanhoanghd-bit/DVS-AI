@echo off
setlocal
cd /d "%~dp0"
title DVS AI Alpha 4.3.0E-3-QBP-4-RC7-BETA4A-RC6.4.7H-r2 - TS12 PFT Single Flight - Outcome Intelligence Foundation - Runtime Stable - Quantum Observe-only

echo ==========================================
echo   DVS AI Alpha 4.3.0E-3-QBP-4-RC7 Performance and Stability - Delta Finalization - Outcome Intelligence Foundation - Runtime Stable - Quantum Observe-only
echo ==========================================
echo.

where python >nul 2>nul
if errorlevel 1 (
    echo [ERROR] Khong tim thay Python trong PATH.
    echo Hay cai Python 3.12 va chon "Add Python to PATH".
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

echo Dang khoi dong DVS AI...
python run.py

if errorlevel 1 (
    echo.
    echo [ERROR] Chuong trinh da dung do loi.
    echo Hay chup lai toan bo noi dung cua so nay.
    pause
)
endlocal
