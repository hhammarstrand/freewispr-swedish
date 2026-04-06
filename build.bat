@echo off
setlocal
set PYTHON=C:\Users\prakh\AppData\Local\Python\pythoncore-3.14-64\python.exe

echo === freewispr build ===
echo.

echo Generating icon...
"%PYTHON%" make_icon.py

echo.
echo Building exe...
"%PYTHON%" -m PyInstaller ^
  --onefile ^
  --windowed ^
  --name freewispr ^
  --icon "assets/icon.ico" ^
  --hidden-import=faster_whisper ^
  --hidden-import=sounddevice ^
  --hidden-import=keyboard ^
  --hidden-import=pystray._win32 ^
  main.py

echo.
if exist dist\freewispr.exe (
    echo Build successful! dist\freewispr.exe is ready.
) else (
    echo Build FAILED. Check errors above.
)
pause
