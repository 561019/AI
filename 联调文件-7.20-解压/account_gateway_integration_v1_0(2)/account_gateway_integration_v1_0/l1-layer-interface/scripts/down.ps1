$root = Split-Path -Parent $PSScriptRoot
Push-Location $root
try { docker compose down } finally { Pop-Location }
