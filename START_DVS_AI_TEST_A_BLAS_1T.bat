@echo off
setlocal
cd /d "%~dp0"
title DVS AI RC6.1 - TEST A - BLAS SINGLE THREAD

rem =============================================================
rem TEST A: Force native numerical libraries to one thread only.
rem No Python source code, scanner logic, PERF/NET logic is changed.
rem =============================================================
set OMP_NUM_THREADS=1
set MKL_NUM_THREADS=1
set OPENBLAS_NUM_THREADS=1
set NUMEXPR_NUM_THREADS=1

if not exist "logs" mkdir "logs"
(
  echo TEST_A_BLAS_SINGLE_THREAD=1
  echo OMP_NUM_THREADS=%OMP_NUM_THREADS%
  echo MKL_NUM_THREADS=%MKL_NUM_THREADS%
  echo OPENBLAS_NUM_THREADS=%OPENBLAS_NUM_THREADS%
  echo NUMEXPR_NUM_THREADS=%NUMEXPR_NUM_THREADS%
  echo STARTED_LOCAL=%DATE% %TIME%
) > "logs\test_a_blas_single_thread.txt"

echo ==========================================
echo   DVS AI RC6.1 - TEST A - BLAS SINGLE THREAD
echo ==========================================
echo OMP_NUM_THREADS=%OMP_NUM_THREADS%
echo MKL_NUM_THREADS=%MKL_NUM_THREADS%
echo OPENBLAS_NUM_THREADS=%OPENBLAS_NUM_THREADS%
echo NUMEXPR_NUM_THREADS=%NUMEXPR_NUM_THREADS%
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

echo Dang khoi dong DVS AI Test A...
python run.py
set EXIT_CODE=%ERRORLEVEL%

echo.
echo DVS AI da ket thuc. Exit code: %EXIT_CODE%
if not "%EXIT_CODE%"=="0" (
    echo [ERROR] Chuong trinh dung do loi/crash.
)
echo Hay giu nguyen thu muc session trong artifacts\runtime\freeze_dumps.
pause
exit /b %EXIT_CODE%
