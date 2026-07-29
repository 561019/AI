@echo off
title Rule Calculation Engine Test Console
cd /d "%~dp0"
echo ============================================================
echo Rule Calculation Engine Test Console is starting.
echo Open: http://127.0.0.1:8010/test-console
echo Keep this window open while testing.
echo ============================================================
echo.
python -m uvicorn app.main:app --host 127.0.0.1 --port 8010
echo.
echo The service has stopped. Press any key to close this window.
pause >nul
