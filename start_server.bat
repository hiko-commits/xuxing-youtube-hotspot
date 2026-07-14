@echo off
cd /d "%~dp0\backend"
echo Starting 旭星-YouTube热点库 server...
echo.
echo Server will be available at: http://127.0.0.1:5000/starroad
echo Press Ctrl+C to stop the server.
echo.
"C:\Users\admin\.workbuddy\binaries\python\envs\default\Scripts\python.exe" app.py
pause
