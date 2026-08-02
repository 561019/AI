$ErrorActionPreference = 'Stop'
$python = if ($env:CODEX_PYTHON) { $env:CODEX_PYTHON } else { 'python' }
$root = Split-Path -Parent $PSScriptRoot
$runDir = Join-Path $PSScriptRoot '.run'
New-Item -ItemType Directory -Path $runDir -Force | Out-Null

# Stop the old cluster before creating the next one, so workers do not compete
# for ports or the shared SQLite database.
& (Join-Path $PSScriptRoot 'stop_all.ps1') | Out-Null
& $python -c "from framework.core import initialize; initialize()"
if ($LASTEXITCODE -ne 0) { throw 'Shared database initialization failed.' }
$env:PLATFORM_DB_INITIALIZED = '1'
if (-not $env:PLATFORM_BIND_HOST) {
    $env:PLATFORM_BIND_HOST = '0.0.0.0'
}

# model.env is the only source allowed to select the model provider.
$modelEnvFile = Join-Path $PSScriptRoot 'config\model.env'
$envFiles = @($modelEnvFile)
$envFiles += Join-Path $PSScriptRoot 'config\module.env'
$loadedModelVars = 0
foreach ($envFile in $envFiles) {
    if (-not $envFile -or -not (Test-Path -LiteralPath $envFile)) { continue }
    foreach ($rawLine in Get-Content -LiteralPath $envFile) {
        $line = $rawLine.Trim()
        if (-not $line) { continue }
        if ($line.StartsWith('#')) {
            # Older local files may have a damaged comment directly before a
            # setting. Recover only known model settings from that same line.
            $embedded = [regex]::Match(
                $line,
                '(MODEL_PROVIDER|DOUBAO_API_KEY|DOUBAO_BASE_URL|DOUBAO_MODEL|DOUBAO_TIMEOUT_SECONDS|DEEPSEEK_API_KEY|DEEPSEEK_BASE_URL|DEEPSEEK_MODEL|DEEPSEEK_TIMEOUT_SECONDS)=([^\s#]+)'
            )
            if (-not $embedded.Success) { continue }
            $name = $embedded.Groups[1].Value
            $value = $embedded.Groups[2].Value.Trim().Trim('"').Trim("'")
        } else {
            if (-not $line.Contains('=')) { continue }
            $parts = $line.Split('=', 2)
            $name = $parts[0].Trim()
            $value = $parts[1].Trim().Trim('"').Trim("'")
        }
        if ($name -notmatch '^[A-Za-z_][A-Za-z0-9_]*$' -or -not $value) { continue }
        if ($name -eq 'MODEL_PROVIDER' -and $envFile -ne $modelEnvFile) { continue }
        [Environment]::SetEnvironmentVariable($name, $value, 'Process')
        $loadedModelVars++
    }
}

# Run the fleet in one cluster process. The cluster owns the service workers.
$launcher = Start-Process -FilePath $python -ArgumentList '-m','framework.run_cluster' -WorkingDirectory $root -WindowStyle Minimized -PassThru
Set-Content -LiteralPath (Join-Path $runDir 'cluster.launcher.pid') -Value $launcher.Id
Write-Output "Started unified backend cluster. Loaded $loadedModelVars settings from framework/config/model.env and framework/config/module.env."
