@echo off
rem Run Alpha Harness v2: one window, the app at http://localhost:8000 (the fast, built website).
rem First time, or after an update: run update.bat first.
cd /d "%~dp0backend"
if not exist "src\alpha_harness\web\index.html" (
  echo The website is not built yet. Run update.bat first.
  pause
  exit /b 1
)
start "" http://localhost:8000
echo Alpha Harness is running. Keep this window open; close it (or press Ctrl+C) to stop.
uv run uvicorn alpha_harness.main:app --port 8000
pause
