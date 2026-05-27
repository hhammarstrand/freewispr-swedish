@echo off
chcp 65001 >nul
setlocal
set PYTHON=python

echo === freewispr-swedish build ===
echo.

choice /C JN /M "Vill du installera/uppdatera beroenden?"
if %errorlevel%==1 (
    echo.
    REM NOTE: Windows Long Paths must be enabled BEFORE running this script.
    REM We no longer write to HKLM here (requires admin and silently no-ops
    REM without it). Enable once via an elevated PowerShell:
    REM   New-ItemProperty -Path "HKLM:\SYSTEM\CurrentControlSet\Control\FileSystem" ^
    REM     -Name LongPathsEnabled -Value 1 -PropertyType DWord -Force
    echo Installerar PyTorch med CUDA-stöd...
    %PYTHON% -m pip install torch --index-url https://download.pytorch.org/whl/cu124
    echo.
    echo Installerar övriga beroenden...
    %PYTHON% -m pip install -r requirements.txt pyinstaller
    echo.
)

REM Hitta faster_whisper assets-mapp för VAD-modellen
for /f "delims=" %%P in ('%PYTHON% -c "import faster_whisper,os;print(os.path.dirname(faster_whisper.__file__))"') do set FW_DIR=%%P

REM Hitta customtkinter-paketet
for /f "delims=" %%P in ('%PYTHON% -c "import customtkinter,os;print(os.path.dirname(customtkinter.__file__))"') do set CTK_DIR=%%P

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
  --hidden-import=keyring.backends.Windows ^
  --hidden-import=customtkinter ^
  --add-data "%FW_DIR%\assets;faster_whisper\assets" ^
  --add-data "%CTK_DIR%;customtkinter" ^
  main.py

echo.
if exist dist\freewispr-swedish\freewispr-swedish.exe (
    echo Bygget klart! dist\freewispr-swedish\freewispr-swedish.exe är redo.
) else (
    echo Bygget MISSLYCKADES. Kontrollera felen ovan.
)
pause
