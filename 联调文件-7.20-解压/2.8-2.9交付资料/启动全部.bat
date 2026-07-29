@echo off
setlocal
set "ROOT=%~dp0"

echo Starting local knowledge base on 8012...
start "KB 8012" cmd /k "cd /d ""%ROOT%engines\local_knowledge_base_v0_1"" && python -m uvicorn backend.main:app --host 127.0.0.1 --port 8012"

echo Starting content engine on 8011...
start "Content 8011" cmd /k "cd /d ""%ROOT%engines\content_engine_v0_2"" && python -m uvicorn backend.main:app --host 127.0.0.1 --port 8011"

echo Starting multimedia engine on 8013...
start "Multimedia 8013" cmd /k "cd /d ""%ROOT%engines\multimedia_engine_v1_1"" && python -m uvicorn backend.main:app --host 127.0.0.1 --port 8013"

echo Starting flow execution engine on 8020...
start "Flow 8020" cmd /k "cd /d ""%ROOT%engines\local_flow_execution_engine"" && python -m uvicorn backend.main:app --host 127.0.0.1 --port 8020"

echo.
echo Services are starting. Wait a few seconds, then open all pages:
echo Knowledge base: http://127.0.0.1:8012
echo Content engine: http://127.0.0.1:8011
echo Multimedia engine: http://127.0.0.1:8013
echo Flow engine: http://127.0.0.1:8020
timeout /t 4 >nul
start "" "http://127.0.0.1:8012"
start "" "http://127.0.0.1:8011"
start "" "http://127.0.0.1:8013"
start "" "http://127.0.0.1:8020"
exit /b 0
