[CmdletBinding()]
param(
    [switch]$WithFrontend,
    [ValidateRange(30, 600)]
    [int]$StartupTimeoutSeconds = 180
)

$ErrorActionPreference = "Stop"
$ProjectRoot = Split-Path -Parent $PSScriptRoot
$EnvironmentFile = Join-Path $ProjectRoot ".env.release"
$EnvironmentTemplate = Join-Path $ProjectRoot ".env.release.example"
$ComposeFile = Join-Path $ProjectRoot "docker-compose.release.yml"

if (-not (Get-Command docker -ErrorAction SilentlyContinue)) {
    throw "Docker Desktop is required. Install and start Docker Desktop, then run this script again."
}
if (-not (Test-Path -LiteralPath $ComposeFile)) {
    throw "Release Compose file was not found: $ComposeFile"
}
if (-not (Test-Path -LiteralPath $EnvironmentFile)) {
    if (-not (Test-Path -LiteralPath $EnvironmentTemplate)) {
        throw "Release environment template was not found: $EnvironmentTemplate"
    }
    Copy-Item -LiteralPath $EnvironmentTemplate -Destination $EnvironmentFile
    Write-Output "Created $EnvironmentFile. Edit it to configure a real L3 model before production use."
}

function Get-EnvironmentValue([string]$Name, [string]$DefaultValue) {
    $Pattern = "^\s*$([regex]::Escape($Name))\s*=\s*(?<value>.*)\s*$"
    $Line = Get-Content -LiteralPath $EnvironmentFile -Encoding utf8 |
        Where-Object { $_ -match $Pattern } |
        Select-Object -Last 1
    if (-not $Line) {
        return $DefaultValue
    }

    $Value = ([regex]::Match($Line, $Pattern)).Groups["value"].Value.Trim()
    if ([string]::IsNullOrWhiteSpace($Value)) {
        return $DefaultValue
    }
    return $Value.Trim('"').Trim("'")
}

function Test-HttpEndpoint([string]$Uri) {
    try {
        return (Invoke-WebRequest -UseBasicParsing -Uri $Uri -TimeoutSec 5).StatusCode -eq 200
    }
    catch {
        return $false
    }
}

$ComposeArguments = @(
    "compose",
    "--env-file",
    ".env.release",
    "-f",
    "docker-compose.release.yml"
)
if ($WithFrontend) {
    $ComposeArguments += @("--profile", "frontend")
}

Push-Location $ProjectRoot
try {
    & docker @ComposeArguments up -d --build
    if ($LASTEXITCODE -ne 0) {
        throw "Docker Compose startup failed with exit code $LASTEXITCODE."
    }
}
finally {
    Pop-Location
}

$BackendPort = Get-EnvironmentValue -Name "BACKEND_PORT" -DefaultValue "8000"
$HealthUri = "http://127.0.0.1:$BackendPort/health"
$Deadline = (Get-Date).AddSeconds($StartupTimeoutSeconds)
while ((Get-Date) -lt $Deadline) {
    if (Test-HttpEndpoint $HealthUri) {
        [PSCustomObject]@{
            Backend = "http://127.0.0.1:$BackendPort/"
            Health = $HealthUri
            Api = "http://127.0.0.1:$BackendPort/api/v1/intent/analyze"
            Docs = "http://127.0.0.1:$BackendPort/docs"
            Frontend = if ($WithFrontend) { "http://127.0.0.1:5173/" } else { $null }
            EnvironmentFile = $EnvironmentFile
            LLMProvider = Get-EnvironmentValue -Name "LLM_PROVIDER" -DefaultValue "mock"
        }
        return
    }
    Start-Sleep -Seconds 2
}

throw "Release services did not become ready within $StartupTimeoutSeconds seconds. Run 'docker compose --env-file .env.release -f docker-compose.release.yml logs' from $ProjectRoot."
