$ErrorActionPreference = "Stop"

$sourceRoot = $PSScriptRoot
$date = Get-Date -Format "yyyyMMdd"
$outputPath = Join-Path (Split-Path -Parent $sourceRoot) "rule_calculation_engine_delivery_${date}.zip"
$stagingRoot = Join-Path ([System.IO.Path]::GetTempPath()) ("rule-calc-delivery-" + [guid]::NewGuid().ToString("N"))
$deliveryRoot = Join-Path $stagingRoot "05_rule_calculation_engine"

try {
    New-Item -ItemType Directory -Path $deliveryRoot -Force | Out-Null
    & robocopy $sourceRoot $deliveryRoot /E /XD "__pycache__" ".git" "artifacts" /XF "*.pyc" "rule_engine.db" ".env" | Out-Null
    if ($LASTEXITCODE -gt 7) {
        throw "Delivery copy failed, robocopy exit code: $LASTEXITCODE"
    }

    if (Test-Path -LiteralPath $outputPath) {
        Remove-Item -LiteralPath $outputPath -Force
    }
    Compress-Archive -Path $deliveryRoot -DestinationPath $outputPath -CompressionLevel Optimal
    Write-Host "Delivery archive created: $outputPath"
}
finally {
    if (Test-Path -LiteralPath $stagingRoot) {
        Remove-Item -LiteralPath $stagingRoot -Recurse -Force
    }
}
