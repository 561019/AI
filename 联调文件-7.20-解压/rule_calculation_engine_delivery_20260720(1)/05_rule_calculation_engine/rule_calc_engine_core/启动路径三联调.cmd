@echo off
chcp 65001 >nul
cd /d "%~dp0"
echo Running Flow-mediated path-three contract smoke test.
python -m scripts.smoke_path_three
echo.
pause
