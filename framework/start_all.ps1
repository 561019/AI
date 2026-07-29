$ErrorActionPreference = 'Stop'
$python = if ($env:CODEX_PYTHON) { $env:CODEX_PYTHON } else { 'python' }
$root = Split-Path -Parent $PSScriptRoot
$runDir = Join-Path $PSScriptRoot '.run'
New-Item -ItemType Directory -Path $runDir -Force | Out-Null

# A second fleet would contend for ports and the shared SQLite writer. Always
# remove every old worker before recording a new process set.
& (Join-Path $PSScriptRoot 'stop_all.ps1') | Out-Null
& $python -c "from framework.core import initialize; initialize()"
if ($LASTEXITCODE -ne 0) { throw 'Shared database initialization failed.' }
$env:PLATFORM_DB_INITIALIZED = '1'
if (-not $env:PLATFORM_BIND_HOST) {
    $env:PLATFORM_BIND_HOST = '0.0.0.0'
}

# 自动加载本地模型配置。已在当前 PowerShell 显式设置的变量优先。
$envFiles = @()
$envFiles += Join-Path $PSScriptRoot 'config\model.env'
$envFiles += Join-Path $PSScriptRoot 'config\module.env'
$loadedModelVars = 0
$envFiles | ForEach-Object {
    $envFile = $_
    if (Test-Path -LiteralPath $envFile) {
        Get-Content -LiteralPath $envFile | ForEach-Object {
            $line = $_.Trim()
            if (-not $line -or $line.StartsWith('#') -or -not $line.Contains('=')) { return }
            $parts = $line.Split('=', 2)
            $name = $parts[0].Trim()
            $value = $parts[1].Trim().Trim('"').Trim("'")
            if ($name -notmatch '^[A-Za-z_][A-Za-z0-9_]*$') { return }
            if (-not $value) { return }
            if (-not [Environment]::GetEnvironmentVariable($name, 'Process')) {
                [Environment]::SetEnvironmentVariable($name, $value, 'Process')
                $loadedModelVars++
            }
        }
    }
}

# Run the fleet in one cluster process. The cluster owns the 37 service
# workers, so stop_all.ps1 can cleanly stop either the cluster or the ports.
$launcher = Start-Process -FilePath $python -ArgumentList '-m','framework.run_cluster' -WorkingDirectory $root -WindowStyle Minimized -PassThru
Set-Content -LiteralPath (Join-Path $runDir 'cluster.launcher.pid') -Value $launcher.Id
Write-Output "Started unified backend cluster. Loaded $loadedModelVars settings from framework/config/model.env and framework/config/module.env."
