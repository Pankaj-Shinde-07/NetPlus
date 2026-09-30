@echo off
title NetPulse Cyber NOC v4.0 — Starting...
color 0A

echo.
echo  =====================================================
echo   NETPULSE CYBER NOC v4.0 — Campus Network Monitor
echo  =====================================================
echo.
echo  [*] Starting Gateway Proxy on 0.0.0.0:8080
echo  [*] Starting Web Dashboard  on http://localhost:5000
echo.
echo  Mobile Setup: Connect phone to PC Hotspot
echo               Proxy Host : 192.168.137.1
echo               Proxy Port : 8080
echo.
echo  Dashboard: Open http://localhost:5000 in browser
echo.
echo  =====================================================
echo.

cd /d "%~dp0"

:: Start server
start "NetPulse Server" /B python server.py

:: Wait 3 seconds then open browser
timeout /t 3 /nobreak >nul
start "" "http://localhost:5000"

echo  [OK] Server started. Browser opening...
echo  [OK] Press CTRL+C in this window to stop.
echo.

:: Keep window alive
python server.py
pause
