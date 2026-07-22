$ErrorActionPreference = 'SilentlyContinue'
$ports = @{
    application = 8100; engine = 8200; foundation = 8300
    intent = 8000; intent_original = 8003
    workflow = 8020; workflow_original = 8021
    rule = 8010; rule_original = 8012
    content = 8011; content_original = 8013
    document_table_parsing = 8036; data_operation = 8031; analysis_prediction = 8030
    monitoring_reminder = 8034; project_management = 8033
    external_system_integration = 8037; knowledge_qa = 8038; digital_asset = 8032
    knowledge_map = 8039; multimedia_generation = 8035
    permission = 8001; model = 8002; template = 8004; registry = 8400
    context_prompt_management = 8059; foundation_data = 8060; account_gateway = 8050
    human_collaboration = 8052; evolution_mechanism = 8054; control_mechanism = 8061
    knowledge_base = 8055; execution_sandbox = 8053; memory_management = 8062
    device_system_interface = 8063; security_compliance = 8051; cost_control = 8064
}

$netstat = netstat -ano
$rows = foreach ($item in $ports.GetEnumerator() | Sort-Object Name) {
    $pidValue = ''
    $pattern = "127\.0\.0\.1:$($item.Value)\s+.*\s+LISTENING\s+(\d+)"
    foreach ($line in $netstat) {
        if ($line -match $pattern) {
            $pidValue = $Matches[1]
            break
        }
    }
    [PSCustomObject]@{
        Service = $item.Name
        Port = $item.Value
        Status = if ($pidValue) { 'LISTENING' } else { 'STOPPED' }
        Pid = $pidValue
    }
}
$rows | Format-Table -AutoSize
