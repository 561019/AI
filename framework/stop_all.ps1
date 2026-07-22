$ErrorActionPreference = 'SilentlyContinue'
$runDir = Join-Path $PSScriptRoot '.run'

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

$ports = @(
    8100, 8200, 8300,
    8000, 8003, 8020, 8021,
    8010, 8012, 8011, 8013,
    8036, 8031, 8030, 8034, 8033,
    8037, 8038, 8032, 8039, 8035,
    8001, 8002, 8004, 8400,
    8059, 8060, 8050, 8052, 8054,
    8061, 8055, 8053, 8062, 8063,
    8051, 8064
)

$candidatePids = New-Object System.Collections.Generic.HashSet[int]

if (Test-Path -LiteralPath $runDir) {
    Get-ChildItem -LiteralPath $runDir -Filter '*.pid' | ForEach-Object {
        $raw = Get-Content -LiteralPath $_.FullName -ErrorAction SilentlyContinue
        if ($raw -match '^\d+$') { [void]$candidatePids.Add([int]$raw) }
    }
}

$netstat = netstat -ano
foreach ($port in $ports) {
    $pattern = "127\.0\.0\.1:$port\s+.*\s+LISTENING\s+(\d+)"
    foreach ($line in $netstat) {
        if ($line -match $pattern) { [void]$candidatePids.Add([int]$Matches[1]) }
    }
}

$stopped = 0
foreach ($pidValue in $candidatePids) {
    $proc = Get-CimInstance Win32_Process -Filter "ProcessId=$pidValue"
    if (-not $proc) { continue }
    if ($proc.CommandLine -notmatch 'framework\.run_services') { continue }
    Stop-Process -Id $pidValue -Force
    $stopped++
}

if (Test-Path -LiteralPath $runDir) {
    Remove-Item -LiteralPath (Join-Path $runDir '*.pid') -Force
}

Write-Output "Stopped $stopped framework services."
