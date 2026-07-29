Set-Location (Split-Path $PSScriptRoot -Parent)
python -m unittest test_engine.py
if ($LASTEXITCODE -ne 0) { exit $LASTEXITCODE }
node --check .\web\app.js
