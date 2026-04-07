@echo off
setlocal
set PYTHON=C:\Users\prakh\AppData\Local\Python\pythoncore-3.14-64\python.exe

echo === freewispr-swedish build ===
echo.

echo Genererar ikon...
"%PYTHON%" make_icon.py

echo.
echo Bygger exe...
"%PYTHON%" -m PyInstaller ^
  --onefile ^
  --windowed ^
  --name freewispr-swedish ^
  --icon "assets/icon.ico" ^
  --hidden-import=faster_whisper ^
  --hidden-import=sounddevice ^
  --hidden-import=keyboard ^
  --hidden-import=pystray._win32 ^
  main.py

echo.
if exist dist\freewispr-swedish.exe (
    echo Bygget klart! dist\freewispr-swedish.exe är redo.
) else (
    echo Bygget MISSLYCKADES. Kontrollera felen ovan.
)
pause
