[CmdletBinding()]
param(
    [string]$OutputDirectory,
    [string]$PackageName = "intent-analysis-engine-release",
    [switch]$DryRun
)

$ErrorActionPreference = "Stop"
$HandoffScript = Join-Path $PSScriptRoot "create-handoff-package.ps1"

if (-not (Test-Path -LiteralPath $HandoffScript)) {
    throw "Source packaging script was not found: $HandoffScript"
}

$ForwardParameters = @{
    PackageName = $PackageName
}
if ($OutputDirectory) {
    $ForwardParameters.OutputDirectory = $OutputDirectory
}
if ($DryRun) {
    $ForwardParameters.DryRun = $true
}

& $HandoffScript @ForwardParameters
