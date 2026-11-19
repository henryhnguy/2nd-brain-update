@echo off
title Second Brain AI
cd /d "%~dp0"
echo ========================================================
echo   KHOI DONG SECOND BRAIN AI (BO NAO THU HAI CA NHAN)
echo ========================================================
echo.
set HOST=127.0.0.1
set PORT=8001
echo Dang khoi chay may chu backend va giao dien web...
call "backend\.venv\Scripts\python.exe" run.py
pause