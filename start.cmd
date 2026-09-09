@echo off
setlocal
cd /d "%~dp0"
if not exist ".venv\Scripts\python.exe" (
  echo First install the application using the setup commands in README.md.
  pause
  exit /b 1
)
".venv\Scripts\python.exe" manage.py migrate
if errorlevel 1 (
  pause
  exit /b 1
)
echo Open http://127.0.0.1:8000 in your browser. Press Ctrl+C to stop.
".venv\Scripts\python.exe" manage.py runserver 127.0.0.1:8000 --insecure --noreload
if errorlevel 1 pause
