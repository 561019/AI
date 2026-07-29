@echo off
setlocal
set "ROOT=%~dp0"

echo [1/4] Installing local knowledge base requirements...
python -m pip install -r "%ROOT%engines\local_knowledge_base_v0_1\requirements.txt"
if errorlevel 1 goto fail

echo [2/4] Installing content engine requirements...
python -m pip install -r "%ROOT%engines\content_engine_v0_2\requirements.txt"
if errorlevel 1 goto fail

echo [3/4] Installing multimedia engine requirements...
python -m pip install -r "%ROOT%engines\multimedia_engine_v1_1\requirements.txt"
if errorlevel 1 goto fail

echo [4/4] Installing flow execution engine requirements...
python -m pip install -r "%ROOT%engines\local_flow_execution_engine\requirements.txt"
if errorlevel 1 goto fail

echo.
echo Dependencies installed.
pause
exit /b 0

:fail
echo.
echo Dependency installation failed. Please check Python and network/pip access.
pause
exit /b 1
