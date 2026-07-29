@echo off
cd /d "%~dp0"
set PORT=8020

powershell -NoProfile -ExecutionPolicy Bypass -Command "try { $r = Invoke-WebRequest -UseBasicParsing -Uri 'http://127.0.0.1:%PORT%/health' -TimeoutSec 2; if ($r.StatusCode -eq 200) { exit 0 } else { exit 1 } } catch { exit 1 }"
if %ERRORLEVEL%==0 (
  echo Local flow execution engine is already running:
  echo http://127.0.0.1:%PORT%
  pause
  exit /b 0
)

set PYTHONDONTWRITEBYTECODE=1
python -m uvicorn backend.main:app --host 127.0.0.1 --port %PORT%
pause
