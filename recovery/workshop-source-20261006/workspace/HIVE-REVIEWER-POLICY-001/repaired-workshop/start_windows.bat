@echo off
cd /d "%~dp0"
if not exist ".venv\Scripts\python.exe" (
  echo Workshop is not set up yet.
  echo Run setup_windows.bat first.
  pause
  exit /b 1
)
start "" http://127.0.0.1:8765
".venv\Scripts\python.exe" app.py
pause
