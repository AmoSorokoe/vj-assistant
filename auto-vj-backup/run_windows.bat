@echo off
setlocal
cd /d "%~dp0"

where py >nul 2>nul
if errorlevel 1 (
  echo Python launcher "py" was not found.
  echo Install Python 3.11 or newer and try again.
  pause
  exit /b 1
)

if not exist ".venv\Scripts\python.exe" (
  echo [AUTO VJ] Creating virtual environment...
  py -3 -m venv .venv
  if errorlevel 1 goto :error
)

call ".venv\Scripts\activate.bat"

echo [AUTO VJ] Installing/updating dependencies...
python -m pip install --upgrade pip
python -m pip install -r requirements.txt
if errorlevel 1 goto :error

echo [AUTO VJ] Starting...
python main.py
exit /b 0

:error
echo.
echo AUTO VJ startup failed.
pause
exit /b 1
