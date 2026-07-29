$ErrorActionPreference = "Stop"

$root = (Resolve-Path (Join-Path $PSScriptRoot "..")).Path
$diagramRoot = (Resolve-Path (Join-Path $root "..\流程图")).Path
$dist = [System.IO.Path]::GetFullPath((Join-Path $root "dist"))
$stage = [System.IO.Path]::GetFullPath((Join-Path $dist "permission_gateway_v1_0"))
$zip = [System.IO.Path]::GetFullPath((Join-Path $dist "permission_gateway_v1_0.zip"))

if (-not $dist.StartsWith($root, [System.StringComparison]::OrdinalIgnoreCase) -or
    -not $stage.StartsWith($dist, [System.StringComparison]::OrdinalIgnoreCase) -or
    -not $zip.StartsWith($dist, [System.StringComparison]::OrdinalIgnoreCase)) {
    throw "Packaging paths escaped the permission-gateway workspace."
}

New-Item -ItemType Directory -Force -Path $dist | Out-Null
if (Test-Path -LiteralPath $stage) {
    Remove-Item -LiteralPath $stage -Recurse -Force
}
if (Test-Path -LiteralPath $zip) {
    Remove-Item -LiteralPath $zip -Force
}
New-Item -ItemType Directory -Path $stage | Out-Null

$entries = @(
    "app",
    "tests",
    "docs",
    "examples",
    "migrations",
    "scripts",
    "requirements.txt",
    ".env.example",
    ".gitignore",
    ".dockerignore",
    "alembic.ini",
    "pytest.ini",
    "Dockerfile",
    "README.md",
    "交付清单.md"
)
foreach ($entry in $entries) {
    Copy-Item -LiteralPath (Join-Path $root $entry) -Destination $stage -Recurse -Force
}

$diagramStage = Join-Path $stage "docs\diagrams"
New-Item -ItemType Directory -Force -Path $diagramStage | Out-Null
Get-ChildItem -LiteralPath $diagramRoot -File |
    Where-Object { $_.Name -match "^(账号网关模块|权限管理模块)(流程图|时序图)" -and $_.Extension -in @(".drawio", ".png") } |
    ForEach-Object { Copy-Item -LiteralPath $_.FullName -Destination $diagramStage -Force }

# Delivery uses the coordination template's plain-text format. Keep Markdown
# in the source tree for maintenance, but include only the .txt handoff copy.
$preparationMarkdown = Join-Path $stage "docs\权限模块联调准备表.md"
$preparationText = Join-Path $stage "docs\权限模块联调准备表.txt"
if (Test-Path -LiteralPath $preparationMarkdown) {
    Copy-Item -LiteralPath $preparationMarkdown -Destination $preparationText -Force
    Remove-Item -LiteralPath $preparationMarkdown -Force
}

Get-ChildItem -LiteralPath $stage -Directory -Recurse -Filter "__pycache__" |
    ForEach-Object { Remove-Item -LiteralPath $_.FullName -Recurse -Force }
Get-ChildItem -LiteralPath $stage -File -Recurse |
    Where-Object { $_.Extension -eq ".pyc" -or $_.Name -eq ".coverage" } |
    ForEach-Object { Remove-Item -LiteralPath $_.FullName -Force }

Compress-Archive -LiteralPath $stage -DestinationPath $zip -CompressionLevel Optimal
Write-Output $zip
