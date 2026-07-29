[CmdletBinding()]
param(
    [switch]$KeepBGEWarm,
    [switch]$WithDemoLLM,
    [switch]$NoFrontend
)

$ErrorActionPreference = "Stop"
$ProjectRoot = Split-Path -Parent $PSScriptRoot
$RuntimeDirectory = Join-Path $ProjectRoot ".runtime"
$Python = Join-Path $ProjectRoot ".venv\Scripts\python.exe"
$Node = (Get-Command node.exe -ErrorAction Stop).Source
$Vite = Join-Path $ProjectRoot "frontend\node_modules\vite\bin\vite.js"
$PidFile = Join-Path $RuntimeDirectory "local-processes.json"

if (-not (Test-Path -LiteralPath $Python)) {
    throw "Project virtual environment was not found: $Python"
}
if (-not $NoFrontend -and -not (Test-Path -LiteralPath $Vite)) {
    throw "Frontend dependencies were not found. Run npm.cmd --prefix frontend install first."
}

New-Item -ItemType Directory -Path $RuntimeDirectory -Force | Out-Null

# Some managed shells expose both Path and PATH; Start-Process requires one canonical entry.
$PathValue = [Environment]::GetEnvironmentVariable("Path", [EnvironmentVariableTarget]::Process)
[Environment]::SetEnvironmentVariable("PATH", $null, [EnvironmentVariableTarget]::Process)
[Environment]::SetEnvironmentVariable("Path", $PathValue, [EnvironmentVariableTarget]::Process)

$env:BGE_KEEP_WARM = if ($KeepBGEWarm) { "true" } else { "false" }
$Processes = [ordered]@{}

function Test-HttpEndpoint([string]$Uri) {
    try {
        return (Invoke-WebRequest -UseBasicParsing -Uri $Uri -TimeoutSec 2).StatusCode -eq 200
    }
    catch {
        return $false
    }
}

if (-not (Test-HttpEndpoint "http://127.0.0.1:8000/health")) {
    $BackendOptions = @{
        FilePath = $Python
        ArgumentList = @("-m", "uvicorn", "app.main:app", "--app-dir", "backend", "--host", "127.0.0.1", "--port", "8000")
        WorkingDirectory = $ProjectRoot
        WindowStyle = "Hidden"
        RedirectStandardOutput = Join-Path $RuntimeDirectory "backend.stdout.log"
        RedirectStandardError = Join-Path $RuntimeDirectory "backend.stderr.log"
        PassThru = $true
    }
    $Backend = Start-Process @BackendOptions
    $Processes.backend = $Backend.Id
}

if ($WithDemoLLM -and -not (Test-HttpEndpoint "http://127.0.0.1:8001/health")) {
    $DemoModelOptions = @{
        FilePath = $Python
        ArgumentList = @("local-model-service\server.py")
        WorkingDirectory = $ProjectRoot
        WindowStyle = "Hidden"
        RedirectStandardOutput = Join-Path $RuntimeDirectory "model.stdout.log"
        RedirectStandardError = Join-Path $RuntimeDirectory "model.stderr.log"
        PassThru = $true
    }
    $DemoModel = Start-Process @DemoModelOptions
    $Processes.demo_model = $DemoModel.Id
}

if (-not $NoFrontend -and -not (Test-HttpEndpoint "http://127.0.0.1:5173/")) {
    $FrontendOptions = @{
        FilePath = $Node
        ArgumentList = @($Vite, "--host", "127.0.0.1")
        WorkingDirectory = Join-Path $ProjectRoot "frontend"
        WindowStyle = "Hidden"
        RedirectStandardOutput = Join-Path $RuntimeDirectory "frontend.stdout.log"
        RedirectStandardError = Join-Path $RuntimeDirectory "frontend.stderr.log"
        PassThru = $true
    }
    $Frontend = Start-Process @FrontendOptions
    $Processes.frontend = $Frontend.Id
}

$Processes | ConvertTo-Json | Set-Content -LiteralPath $PidFile -Encoding utf8

$BackendReady = $false
$FrontendReady = $NoFrontend
for ($Attempt = 0; $Attempt -lt 30; $Attempt += 1) {
    $BackendReady = Test-HttpEndpoint "http://127.0.0.1:8000/health"
    if (-not $NoFrontend) {
        $FrontendReady = Test-HttpEndpoint "http://127.0.0.1:5173/"
    }
    if ($BackendReady -and $FrontendReady) {
        break
    }
    Start-Sleep -Seconds 1
}

if (-not $BackendReady -or -not $FrontendReady) {
    throw "Local services did not become ready. Check logs in $RuntimeDirectory."
}

[PSCustomObject]@{
    Backend = "http://127.0.0.1:8000/"
    Frontend = if ($NoFrontend) { $null } else { "http://127.0.0.1:5173/" }
    BGEKeepWarm = [bool]$KeepBGEWarm
    DemoLLM = [bool]$WithDemoLLM
}
