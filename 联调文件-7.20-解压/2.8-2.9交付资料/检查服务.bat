@echo off
setlocal

echo Checking local knowledge base...
powershell -NoProfile -ExecutionPolicy Bypass -Command "try { (Invoke-WebRequest -UseBasicParsing -Uri 'http://127.0.0.1:8012/api/health' -TimeoutSec 2).StatusCode } catch { 'FAILED' }"

echo Checking content engine...
powershell -NoProfile -ExecutionPolicy Bypass -Command "try { (Invoke-WebRequest -UseBasicParsing -Uri 'http://127.0.0.1:8011/api/health' -TimeoutSec 2).StatusCode } catch { 'FAILED' }"

echo Checking multimedia engine...
powershell -NoProfile -ExecutionPolicy Bypass -Command "try { (Invoke-WebRequest -UseBasicParsing -Uri 'http://127.0.0.1:8013/api/health' -TimeoutSec 2).StatusCode } catch { 'FAILED' }"

echo Checking flow execution engine...
powershell -NoProfile -ExecutionPolicy Bypass -Command "try { (Invoke-WebRequest -UseBasicParsing -Uri 'http://127.0.0.1:8020/health' -TimeoutSec 2).StatusCode } catch { 'FAILED' }"

pause
