@echo off
chcp 65001 >nul
setlocal
set PYTHON=python

echo === freewispr-swedish (dev) ===
echo.

choice /C JN /M "Vill du installera/uppdatera beroenden forst? [J/N]"
if %errorlevel%==1 (
    echo.
    echo Installerar PyTorch med CUDA-stod...
    %PYTHON% -m pip install torch --index-url https://download.pytorch.org/whl/cu124
    echo.
    echo Installerar ovriga beroenden...
    %PYTHON% -m pip install -r requirements.txt
    echo.
)

echo Startar freewispr-swedish...
echo Tryck Ctrl+C har for att avsluta.
echo.
%PYTHON% main.py
pause
