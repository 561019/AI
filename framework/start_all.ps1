$ErrorActionPreference = 'Stop'
$python = if ($env:CODEX_PYTHON) { $env:CODEX_PYTHON } else { 'python' }
$root = Split-Path -Parent $PSScriptRoot
$runDir = Join-Path $PSScriptRoot '.run'
New-Item -ItemType Directory -Path $runDir -Force | Out-Null

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

$services = @(
    'application', 'engine', 'foundation',
    'intent', 'intent_original', 'workflow', 'workflow_original',
    'rule', 'rule_original', 'content', 'content_original',
    'document_table_parsing', 'data_operation', 'analysis_prediction', 'monitoring_reminder', 'project_management',
    'external_system_integration', 'knowledge_qa', 'digital_asset', 'knowledge_map', 'multimedia_generation',
    'permission', 'model', 'template', 'registry',
    'context_prompt_management', 'foundation_data', 'account_gateway', 'human_collaboration', 'evolution_mechanism',
    'control_mechanism', 'knowledge_base', 'execution_sandbox', 'memory_management', 'device_system_interface',
    'security_compliance', 'cost_control'
)
foreach ($service in $services) {
    $start = [Diagnostics.ProcessStartInfo]::new()
    $start.FileName = $python
    $start.Arguments = "-m framework.run_services $service"
    $start.WorkingDirectory = $root
    $start.UseShellExecute = $false
    $start.CreateNoWindow = $true
    $process = [Diagnostics.Process]::Start($start)
    Set-Content -LiteralPath (Join-Path $runDir "$service.pid") -Value $process.Id
}
Write-Output "Started $($services.Count) services. Loaded $loadedModelVars settings from framework/config/model.env and framework/config/module.env."
