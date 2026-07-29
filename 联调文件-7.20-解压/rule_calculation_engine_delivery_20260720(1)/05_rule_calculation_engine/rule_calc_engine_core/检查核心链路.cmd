@echo off
chcp 65001 >nul
cd /d "%~dp0"
echo ============================================================
echo Rule Calculation Engine Core Check is starting.
echo 1. Run all automated tests.
echo 2. Run the two-stage platform-instruction smoke test.
echo ============================================================
echo.
python -m unittest discover -s tests
if errorlevel 1 goto failed
echo.
python -m scripts.smoke_two_stage
if errorlevel 1 goto failed
echo.
echo Core checks passed.
pause
exit /b 0

:failed
echo.
echo Core checks failed. Review the output above.
pause
exit /b 1
