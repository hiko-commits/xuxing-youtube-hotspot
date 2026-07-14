@echo off
cd /d "%~dp0\..\backend"
echo Running daily auto-refresh for 旭星-YouTube热点库...
echo.
python daily_refresh.py
echo.
echo Refresh completed. Window will close in 10 seconds.
timeout /t 10
