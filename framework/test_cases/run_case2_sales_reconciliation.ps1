param(
    [string]$ApplicationBaseUrl = "http://127.0.0.1:8100",
    [string]$EngineBaseUrl = "http://127.0.0.1:8200",
    [string]$FoundationBaseUrl = "http://127.0.0.1:8300"
)

$ErrorActionPreference = "Stop"
$TraceId = [guid]::NewGuid().ToString()
$Actor = @{
    tenant_id = "hanhe-demo"
    user_id = "fu_shengxian"
    actor_id = "fu_shengxian"
    person_id = "fu_shengxian"
    display_name = "FuShengxian"
    position_ids = @("sales_staff")
    authenticated = $true
}

function New-Envelope {
    param(
        [string]$Capability,
        [string]$TargetLayer,
        [string]$TargetModule,
        [hashtable]$Payload,
        [string]$SourceLayer = "business_engine",
        [string]$SourceModule = "workflow-execution"
    )
    return @{
        protocol_version = "1.0"
        message_id = [guid]::NewGuid().ToString()
        request_id = [guid]::NewGuid().ToString()
        trace_id = $TraceId
        parent_request_id = $null
        source = @{ layer = $SourceLayer; module = $SourceModule }
        target = @{ layer = $TargetLayer; module = $TargetModule; capability = $Capability }
        actor = $Actor
        context = @{ project_id = "case2-sales-reconciliation"; conversation_id = "case2-$TraceId"; locale = "zh-CN" }
        request_type = "execute"
        action = $Capability
        payload = $Payload
        expected_response = @{ mode = "sync" }
        idempotency_key = "case2-$Capability-$([guid]::NewGuid())"
        deadline_at = [DateTimeOffset]::UtcNow.AddMinutes(2).ToString("o")
    }
}

function Invoke-Json {
    param(
        [string]$Method,
        [string]$Url,
        [object]$Body
    )
    try {
        if ($Method -eq "GET") {
            $response = Invoke-WebRequest -Method $Method -Uri $Url -TimeoutSec 90
        } else {
            $json = $Body | ConvertTo-Json -Depth 30
            $response = Invoke-WebRequest -Method $Method -Uri $Url -ContentType "application/json; charset=utf-8" -Body $json -TimeoutSec 90
        }
        $bodyText = $response.Content
        $bodyJson = if ($bodyText) { $bodyText | ConvertFrom-Json } else { $null }
        return @{ status = [int]$response.StatusCode; body = $bodyJson; ok = $true }
    } catch {
        $status = 599
        $bodyJson = @{ error = @{ code = "REQUEST_FAILED"; message = $_.Exception.Message } }
        if ($_.Exception.Response) {
            $status = [int]$_.Exception.Response.StatusCode
            $reader = New-Object System.IO.StreamReader($_.Exception.Response.GetResponseStream())
            $bodyText = $reader.ReadToEnd()
            if ($bodyText) {
                try { $bodyJson = $bodyText | ConvertFrom-Json } catch { $bodyJson = @{ raw = $bodyText } }
            }
        }
        return @{ status = $status; body = $bodyJson; ok = $false }
    }
}

function Add-StepResult {
    param(
        [System.Collections.ArrayList]$Results,
        [string]$Name,
        [string]$Url,
        [object]$Request,
        [object]$Response
    )
    [void]$Results.Add([ordered]@{
        name = $Name
        url = $Url
        request = $Request
        http_status = $Response.status
        response = $Response.body
    })
    Write-Output ("[{0}] HTTP {1} -> {2}" -f $Name, $Response.status, $Url)
}

$Results = New-Object System.Collections.ArrayList

Write-Output "Case2: sales reconciliation parallel checks and decisions"
Write-Output "Trace ID: $TraceId"

$utterance = "Handle current month sales reconciliation: check payment flow vs finance data, contract ledger, and invoice consistency in parallel; send doubts to me for decisions and auto-pass matched items."
$intentEnvelope = New-Envelope `
    -Capability "intent.analyze" `
    -TargetLayer "business_engine" `
    -TargetModule "engine-gateway" `
    -SourceLayer "business_application" `
    -SourceModule "case2-test-client" `
    -Payload @{ utterance = $utterance }
$url = "$ApplicationBaseUrl/api/v1/application/instructions"
$response = Invoke-Json -Method "POST" -Url $url -Body $intentEnvelope
Add-StepResult -Results $Results -Name "1-submit-natural-language-request" -Url $url -Request $intentEnvelope -Response $response

$confirmedTasks = @(
    @{
        task_id = "case2-t1-payment-flow-check"
        description = "Check payment flow against finance receivable data for owned projects"
        capability_code = "data.search"
        next_capability_code = "rule.calculate"
        dependencies = @()
        parallel_group = "sales_reconciliation_parallel_checks"
        parameters = @{
            data_scope = "owned_projects_current_month"
            datasets = @("payment_flow", "finance_receivable")
            comparison_rule = "payment_vs_receivable_amount_match"
        }
    },
    @{
        task_id = "case2-t2-contract-ledger-check"
        description = "Check receivable and actual received fields in owned contract ledger"
        capability_code = "data.search"
        next_capability_code = "rule.calculate"
        dependencies = @()
        parallel_group = "sales_reconciliation_parallel_checks"
        parameters = @{
            data_scope = "owned_contracts_current_month"
            datasets = @("contract_ledger")
            comparison_rule = "contract_receivable_vs_actual_received"
        }
    },
    @{
        task_id = "case2-t3-invoice-consistency-check"
        description = "Check invoice title and amount consistency"
        capability_code = "external.api.call"
        next_capability_code = "rule.calculate"
        dependencies = @()
        parallel_group = "sales_reconciliation_parallel_checks"
        parameters = @{
            external_system = "finance_or_tax_invoice_system"
            query_scope = "owned_invoices_current_month"
            comparison_rule = "invoice_title_and_amount_match"
        }
    }
)

$workflowEnvelope = New-Envelope `
    -Capability "workflow.execute" `
    -TargetLayer "business_engine" `
    -TargetModule "engine-gateway" `
    -SourceLayer "business_application" `
    -SourceModule "application-gateway" `
    -Payload @{
        execution_kind = "case2_sales_reconciliation"
        confirmed_intent_tasks = $confirmedTasks
        parallel_policy = @{ mode = "parallel_if_no_dependencies"; group = "sales_reconciliation_parallel_checks" }
        platform_task_id = "case2-$TraceId"
    }
$url = "$EngineBaseUrl/api/v1/engine/instructions"
$response = Invoke-Json -Method "POST" -Url $url -Body $workflowEnvelope
Add-StepResult -Results $Results -Name "2-workflow-receives-three-parallel-tasks" -Url $url -Request $workflowEnvelope -Response $response

foreach ($resourceId in @("data.search.payment_flow", "data.search.contract_ledger", "external.api.call.invoice", "human.task.create.doubt_cards", "data.update.reconciliation_status")) {
    $permissionEnvelope = New-Envelope `
        -Capability "permissions.check" `
        -TargetLayer "foundation" `
        -TargetModule "foundation-gateway" `
        -Payload @{ resource = @{ type = "capability"; id = $resourceId }; scope = @{ purpose = "case2-sales-reconciliation"; trace_id = $TraceId } }
    $url = "$FoundationBaseUrl/api/v1/foundation/instructions"
    $response = Invoke-Json -Method "POST" -Url $url -Body $permissionEnvelope
    Add-StepResult -Results $Results -Name "permission-check-$resourceId" -Url $url -Request $permissionEnvelope -Response $response
}

$dataChecks = @(
    @{ name = "3A-fetch-payment-flow-data"; payload = @{ verification_mode = $true; adapter_timeout_seconds = 0.6; data_scope = "owned_projects_current_month"; datasets = @("payment_flow", "finance_receivable"); sample_expected = "mark payment vs balance difference" } },
    @{ name = "3B-fetch-contract-ledger-data"; payload = @{ verification_mode = $true; adapter_timeout_seconds = 0.6; data_scope = "owned_contracts_current_month"; datasets = @("contract_ledger"); sample_expected = "mark receivable vs received difference" } }
)
foreach ($item in $dataChecks) {
    $envelope = New-Envelope -Capability "data.search" -TargetLayer "business_engine" -TargetModule "engine-gateway" -Payload $item.payload
    $url = "$EngineBaseUrl/api/v1/engine/instructions"
    $response = Invoke-Json -Method "POST" -Url $url -Body $envelope
    Add-StepResult -Results $Results -Name $item.name -Url $url -Request $envelope -Response $response
}

$externalEnvelope = New-Envelope `
    -Capability "external.api.call" `
    -TargetLayer "business_engine" `
    -TargetModule "engine-gateway" `
    -Payload @{ verification_mode = $true; adapter_timeout_seconds = 0.6; external_system = "finance_or_tax_invoice_system"; operation = "query_invoice_consistency"; query_scope = "owned_invoices_current_month" }
$url = "$EngineBaseUrl/api/v1/engine/instructions"
$response = Invoke-Json -Method "POST" -Url $url -Body $externalEnvelope
Add-StepResult -Results $Results -Name "3C-fetch-invoices-from-external-system" -Url $url -Request $externalEnvelope -Response $response

$ruleChecks = @(
    @{ name = "4A-rule-compare-payment-difference"; values = @(10200, -10000); note = "simulate 200 CNY freight difference" },
    @{ name = "4B-rule-compare-contract-receivable"; values = @(50000, -50000); note = "simulate matched values" },
    @{ name = "4C-rule-compare-invoice-amount"; values = @(8800, -8800); note = "amount matched; title doubt is carried in payload" }
)
foreach ($item in $ruleChecks) {
    $envelope = New-Envelope `
        -Capability "rule.calculate" `
        -TargetLayer "business_engine" `
        -TargetModule "engine-gateway" `
        -Payload @{
            rule_ref = @{ id = "case2.reconciliation.compare"; version = "1.0" }
            data_refs = @(@{ id = "case2.inline-values"; authorized = $true })
            parameters = @{ values = $item.values; note = $item.note }
            expected_unit = "CNY"
        }
    $url = "$EngineBaseUrl/api/v1/engine/instructions"
    $response = Invoke-Json -Method "POST" -Url $url -Body $envelope
    Add-StepResult -Results $Results -Name $item.name -Url $url -Request $envelope -Response $response
}

$humanEnvelope = New-Envelope `
    -Capability "human.task.create" `
    -TargetLayer "foundation" `
    -TargetModule "foundation-gateway" `
    -Payload @{
        verification_mode = $true
        adapter_timeout_seconds = 0.6
        assignee = "fu_shengxian"
        task_type = "case2_reconciliation_doubt_confirmation"
        cards = @(
            @{ doubt_id = "case2-doubt-001"; title = "Payment amount differs from contract balance by freight charge"; suggested_decision = "Confirm difference and mark as freight difference" },
            @{ doubt_id = "case2-doubt-002"; title = "One invoice title is inconsistent"; suggested_decision = "Confirm doubt and return invoice for correction" }
        )
    }
$url = "$FoundationBaseUrl/api/v1/foundation/instructions"
$response = Invoke-Json -Method "POST" -Url $url -Body $humanEnvelope
Add-StepResult -Results $Results -Name "5-create-two-human-confirmation-cards" -Url $url -Request $humanEnvelope -Response $response

$writeBackEnvelope = New-Envelope `
    -Capability "data.update" `
    -TargetLayer "business_engine" `
    -TargetModule "engine-gateway" `
    -Payload @{
        verification_mode = $true
        adapter_timeout_seconds = 0.6
        target = "sales_reconciliation_record"
        decisions = @(
            @{ doubt_id = "case2-doubt-001"; decision = "confirmed_freight_difference" },
            @{ doubt_id = "case2-doubt-002"; decision = "confirmed_invoice_title_mismatch" }
        )
        final_state = "completed_with_two_confirmed_doubts"
    }
$url = "$EngineBaseUrl/api/v1/engine/instructions"
$response = Invoke-Json -Method "POST" -Url $url -Body $writeBackEnvelope
Add-StepResult -Results $Results -Name "6-write-back-reconciliation-status-after-decisions" -Url $url -Request $writeBackEnvelope -Response $response

$traceUrl = "$ApplicationBaseUrl/api/v1/traces/$TraceId/calls"
$traceResponse = Invoke-Json -Method "GET" -Url $traceUrl -Body @{}
Add-StepResult -Results $Results -Name "7-read-full-trace-calls" -Url $traceUrl -Request @{ trace_id = $TraceId } -Response $traceResponse

$output = [ordered]@{
    case_id = "architecture-v3.9-case2-sales-reconciliation"
    trace_id = $TraceId
    trace_url = $traceUrl
    monitor_url = "$ApplicationBaseUrl/monitor?trace_id=$TraceId"
    steps = $Results
}

$outFile = Join-Path $PSScriptRoot "case2_sales_reconciliation.last_run.json"
$output | ConvertTo-Json -Depth 50 | Set-Content -LiteralPath $outFile -Encoding UTF8

Write-Output ""
Write-Output "Trace URL: $traceUrl"
Write-Output "Monitor URL: $ApplicationBaseUrl/monitor?trace_id=$TraceId"
Write-Output "Saved result: $outFile"
