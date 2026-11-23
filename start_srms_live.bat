@echo off
title Student Resume Management System - Continuous Service
echo =======================================================================
echo   STUDENT RESUME MANAGEMENT SYSTEM (SRMS) - PERSISTENT SERVICE RUNNER
echo =======================================================================
cd /d "%~dp0"

echo [1/2] Checking and starting SRMS Python Web Server on port 8000...
start "SRMS-Server" /b "C:\Users\valla\AppData\Local\Python\bin\python.exe" run_server.py

timeout /t 3 >nul

echo [2/2] Launching Cloudflare Tunnel...
echo Access URLs:
echo   - Localhost:     http://localhost:8000/login
echo   - Local Wi-Fi:   http://192.168.1.11:8000/login
echo.
echo Launching public tunnel below:
.\cloudflared.exe tunnel --url http://127.0.0.1:8000 --no-autoupdate