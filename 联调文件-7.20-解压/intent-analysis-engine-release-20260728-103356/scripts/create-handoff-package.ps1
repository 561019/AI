[CmdletBinding()]
param(
    [string]$OutputDirectory,
    [string]$PackageName = "intent-analysis-engine-handoff",
    [switch]$DryRun
)

$ErrorActionPreference = "Stop"
$ProjectRoot = Split-Path -Parent $PSScriptRoot

if (-not $OutputDirectory) {
    $OutputDirectory = Join-Path $ProjectRoot "dist"
}
elseif (-not [System.IO.Path]::IsPathRooted($OutputDirectory)) {
    $OutputDirectory = Join-Path $ProjectRoot $OutputDirectory
}

$ExcludedDirectories = @(
    ".git",
    ".codex",
    ".agents",
    ".venv",
    ".pytest_cache",
    ".runtime",
    "__pycache__",
    "node_modules",
    "dist",
    ".vite",
    "build",
    "README.md.empty-dir.bak"
)

$ExcludedFiles = @(
    ".env",
    ".env.local",
    ".env.release",
    "intent_capability_vectors.npz",
    "local-processes.json",
    "*.log",
    "*.pyc",
    "*.pyo"
)

if ($DryRun) {
    [PSCustomObject]@{
        ProjectRoot = $ProjectRoot
        OutputDirectory = $OutputDirectory
        PackageName = $PackageName
        ExcludedDirectories = $ExcludedDirectories
        ExcludedFiles = $ExcludedFiles
    }
    return
}

$Timestamp = Get-Date -Format "yyyyMMdd-HHmmss"
$StagingRoot = Join-Path $ProjectRoot ".runtime\handoff-package"
$PackageRoot = Join-Path $StagingRoot $PackageName
$ZipPath = Join-Path $OutputDirectory "$PackageName-$Timestamp.zip"
$ResolvedProjectRoot = (Resolve-Path -LiteralPath $ProjectRoot).Path

function Assert-PathInsideProject([string]$PathToCheck) {
    $FullPath = [System.IO.Path]::GetFullPath($PathToCheck)
    if (-not $FullPath.StartsWith($ResolvedProjectRoot, [System.StringComparison]::OrdinalIgnoreCase)) {
        throw "Refusing to operate outside project root: $FullPath"
    }
}

Assert-PathInsideProject $StagingRoot

if (Test-Path -LiteralPath $StagingRoot) {
    Assert-PathInsideProject $StagingRoot
    Remove-Item -LiteralPath $StagingRoot -Recurse -Force
}

New-Item -ItemType Directory -Force -Path $PackageRoot | Out-Null
New-Item -ItemType Directory -Force -Path $OutputDirectory | Out-Null

$RobocopyArgs = @(
    $ProjectRoot,
    $PackageRoot,
    "/E",
    "/XD"
) + $ExcludedDirectories + @(
    "/XF"
) + $ExcludedFiles + @(
    "/NFL",
    "/NDL",
    "/NJH",
    "/NJS",
    "/NP"
)

& robocopy @RobocopyArgs | Out-Null
$RobocopyExitCode = $LASTEXITCODE
if ($RobocopyExitCode -ge 8) {
    throw "robocopy failed with exit code $RobocopyExitCode"
}

if (Test-Path -LiteralPath $ZipPath) {
    Remove-Item -LiteralPath $ZipPath -Force
}

Add-Type -AssemblyName System.IO.Compression.FileSystem
[System.IO.Compression.ZipFile]::CreateFromDirectory($PackageRoot, $ZipPath)

Assert-PathInsideProject $StagingRoot
Remove-Item -LiteralPath $StagingRoot -Recurse -Force

[PSCustomObject]@{
    Package = $ZipPath
    ExcludedDirectories = $ExcludedDirectories
    ExcludedFiles = $ExcludedFiles
}
