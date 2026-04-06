@echo off
echo === freewispr build ===
echo.

REM Install deps
pip install -r requirements.txt
pip install pyinstaller

echo.
echo Building exe...
pyinstaller ^
  --onefile ^
  --windowed ^
  --name freewispr ^
  --icon assets/icon.ico ^
  --add-data "assets;assets" ^
  main.py

echo.
echo Done! Exe is in dist\freewispr.exe
pause
