@echo off
cd /d "%~dp0"
title SPY GREEKS DASHBOARD
color 0D

echo.
echo ============================================
echo    SPY GREEKS DASHBOARD
echo    Greeks Analysis - Strikes 1$ intervals
echo ============================================
echo.
echo Demarrage du serveur...
echo.

python app.py

pause
