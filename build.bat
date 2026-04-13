@echo off
chcp 65001 >nul
setlocal
set PYTHON=python

echo === freewispr-swedish build ===
echo.

choice /C JN /M "Vill du installera/uppdatera beroenden?"
if %errorlevel%==1 (
    echo.
    echo Aktiverar Windows Long Paths...
    reg add "HKLM\SYSTEM\CurrentControlSet\Control\FileSystem" /v LongPathsEnabled /t REG_DWORD /d 1 /f >nul 2>&1
    echo.
    echo Installerar PyTorch med CUDA-stod...
    %PYTHON% -m pip install torch --index-url https://download.pytorch.org/whl/cu124
    echo.
    echo Installerar ovriga beroenden...
    %PYTHON% -m pip install -r requirements.txt pyinstaller
    echo.
)

REM Hitta faster_whisper assets-mapp for VAD-modellen
for /f "delims=" %%P in ('%PYTHON% -c "import faster_whisper,os;print(os.path.dirname(faster_whisper.__file__))"') do set FW_DIR=%%P

echo Genererar ikon...
%PYTHON% make_icon.py

echo.
echo Bygger exe...
%PYTHON% -m PyInstaller ^
  --onedir ^
  --windowed ^
  --name freewispr-swedish ^
  --icon "assets/icon.ico" ^
  --hidden-import=faster_whisper ^
  --hidden-import=sounddevice ^
  --hidden-import=keyboard ^
  --hidden-import=pystray._win32 ^
  --add-data "%FW_DIR%\assets;faster_whisper\assets" ^
  main.py

echo.
if exist dist\freewispr-swedish\freewispr-swedish.exe (
    echo Bygget klart! dist\freewispr-swedish\freewispr-swedish.exe ar redo.
) else (
    echo Bygget MISSLYCKADES. Kontrollera felen ovan.
)
pause
