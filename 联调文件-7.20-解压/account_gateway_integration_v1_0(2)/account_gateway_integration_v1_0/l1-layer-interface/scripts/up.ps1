param([switch]$Detach)

$root = Split-Path -Parent $PSScriptRoot
Push-Location $root
try {
    if ($Detach) { docker compose up --build -d } else { docker compose up --build }
} finally { Pop-Location }
