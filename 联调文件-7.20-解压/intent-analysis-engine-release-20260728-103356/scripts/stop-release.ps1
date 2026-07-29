[CmdletBinding()]
param(
    [switch]$RemoveData
)

$ErrorActionPreference = "Stop"
$ProjectRoot = Split-Path -Parent $PSScriptRoot
$EnvironmentFile = Join-Path $ProjectRoot ".env.release"
$ComposeFile = Join-Path $ProjectRoot "docker-compose.release.yml"

if (-not (Get-Command docker -ErrorAction SilentlyContinue)) {
    throw "Docker Desktop is required."
}
if (-not (Test-Path -LiteralPath $EnvironmentFile)) {
    throw "Release environment file was not found: $EnvironmentFile"
}
if (-not (Test-Path -LiteralPath $ComposeFile)) {
    throw "Release Compose file was not found: $ComposeFile"
}

$ComposeArguments = @(
    "compose",
    "--env-file",
    ".env.release",
    "-f",
    "docker-compose.release.yml",
    "down"
)
if ($RemoveData) {
    $ComposeArguments += "--volumes"
}

Push-Location $ProjectRoot
try {
    & docker @ComposeArguments
    if ($LASTEXITCODE -ne 0) {
        throw "Docker Compose shutdown failed with exit code $LASTEXITCODE."
    }
}
finally {
    Pop-Location
}

if ($RemoveData) {
    Write-Output "Release services and PostgreSQL data volume were removed."
}
else {
    Write-Output "Release services stopped. PostgreSQL data volume was preserved."
}
