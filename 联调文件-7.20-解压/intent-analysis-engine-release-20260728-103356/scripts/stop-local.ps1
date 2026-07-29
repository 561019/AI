[CmdletBinding()]
param()

$ErrorActionPreference = "Stop"
$ProjectRoot = Split-Path -Parent $PSScriptRoot
$PidFile = Join-Path $ProjectRoot ".runtime\local-processes.json"

try {
    Invoke-WebRequest -UseBasicParsing -Method Post -Uri "http://127.0.0.1:8011/shutdown" -TimeoutSec 2 | Out-Null
}
catch {
    # The worker may already have released itself after the idle timeout.
}

if (Test-Path -LiteralPath $PidFile) {
    $Processes = Get-Content -LiteralPath $PidFile -Encoding utf8 | ConvertFrom-Json
    foreach ($Property in $Processes.PSObject.Properties) {
        $ProcessId = [int]$Property.Value
        if (Get-Process -Id $ProcessId -ErrorAction SilentlyContinue) {
            & taskkill.exe /PID $ProcessId /T /F | Out-Null
        }
    }
    Remove-Item -LiteralPath $PidFile -Force
}

Write-Output "Local intent-analysis services stopped."
