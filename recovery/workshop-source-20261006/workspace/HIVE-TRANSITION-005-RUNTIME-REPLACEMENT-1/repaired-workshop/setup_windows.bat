@echo off
setlocal
cd /d "%~dp0"
where python >nul 2>nul
if errorlevel 1 (
  echo Python was not found. Install Python 3.11+ from python.org, then rerun this file.
  pause
  exit /b 1
)
if not exist ".venv" python -m venv .venv
call ".venv\Scripts\activate.bat"
python -m pip install --upgrade pip
pip install -r requirements.txt
echo.
echo Setup complete.
echo Optional local models: install Ollama, then run e.g.  ollama pull qwen3.5:9b
echo.
pause
