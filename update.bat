@echo off
rem Get the latest Alpha Harness v2 and build it. Run this after every change I push.
cd /d "%~dp0"
echo Getting the latest version...
git pull || goto :fail
echo Installing the backend...
cd backend
call uv sync || goto :fail
cd ..\frontend
echo Installing and building the website (about a minute)...
call pnpm install || goto :fail
call pnpm build || goto :fail
cd ..
echo.
echo Done. Double-click start.bat to run it.
pause
exit /b 0
:fail
echo.
echo Something failed above. Send a screenshot of this window.
pause
exit /b 1
