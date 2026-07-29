$ErrorActionPreference = "Stop"

$accountRoot = (Resolve-Path (Join-Path $PSScriptRoot "..")).Path
$permissionRoot = (Resolve-Path (Join-Path $accountRoot "..\permission-gateway")).Path
$layerRoot = (Resolve-Path (Join-Path $accountRoot "..\l1-layer-interface")).Path
$diagramRoot = (Resolve-Path (Join-Path $accountRoot "..\流程图")).Path
$dist = [System.IO.Path]::GetFullPath((Join-Path $accountRoot "dist"))
$stage = [System.IO.Path]::GetFullPath((Join-Path $dist "account_gateway_integration_v1_0"))
$zip = [System.IO.Path]::GetFullPath((Join-Path $dist "account_gateway_integration_v1_0.zip"))

if (-not $dist.StartsWith($accountRoot, [System.StringComparison]::OrdinalIgnoreCase) -or
    -not $stage.StartsWith($dist, [System.StringComparison]::OrdinalIgnoreCase) -or
    -not $zip.StartsWith($dist, [System.StringComparison]::OrdinalIgnoreCase)) {
    throw "Packaging paths escaped the account-gateway workspace."
}

New-Item -ItemType Directory -Force -Path $dist | Out-Null
if (Test-Path -LiteralPath $stage) {
    Remove-Item -LiteralPath $stage -Recurse -Force
}
if (Test-Path -LiteralPath $zip) {
    Remove-Item -LiteralPath $zip -Force
}

$accountStage = Join-Path $stage "account-gateway"
$permissionStage = Join-Path $stage "permission-gateway"
$layerStage = Join-Path $stage "l1-layer-interface"
$handoffStage = Join-Path $stage "handoff"
New-Item -ItemType Directory -Force -Path $accountStage, $permissionStage, $layerStage, $handoffStage | Out-Null

$diagramStage = Join-Path $handoffStage "diagrams"
New-Item -ItemType Directory -Force -Path $diagramStage | Out-Null
Get-ChildItem -LiteralPath $diagramRoot -File |
    Where-Object { $_.Name -match "^(账号网关模块|权限管理模块)(流程图|时序图)" -and $_.Extension -in @(".drawio", ".png") } |
    ForEach-Object { Copy-Item -LiteralPath $_.FullName -Destination $diagramStage -Force }

foreach ($directory in @("cmd", "internal", "infra", "scripts")) {
    Copy-Item -LiteralPath (Join-Path $accountRoot $directory) -Destination $accountStage -Recurse -Force
}
# The web console is part of the gateway delivery. Include source and lockfile,
# never node_modules or generated dev/build artifacts.
$webStage = Join-Path $accountStage "web"
New-Item -ItemType Directory -Force -Path $webStage | Out-Null
foreach ($directory in @("src", "public")) {
    Copy-Item -LiteralPath (Join-Path $accountRoot ("web\" + $directory)) -Destination $webStage -Recurse -Force
}
foreach ($file in @("index.html", "package.json", "package-lock.json", "vite.config.js")) {
    Copy-Item -LiteralPath (Join-Path $accountRoot ("web\" + $file)) -Destination $webStage -Force
}
foreach ($directory in @("e2e", "mocks", "perf")) {
    $source = Join-Path $accountRoot ("tests\" + $directory)
    if (Test-Path -LiteralPath $source) {
        New-Item -ItemType Directory -Force -Path (Join-Path $accountStage "tests") | Out-Null
        Copy-Item -LiteralPath $source -Destination (Join-Path $accountStage "tests") -Recurse -Force
    }
}
New-Item -ItemType Directory -Force -Path (Join-Path $accountStage "docs") | Out-Null
foreach ($file in @("architecture.md", "runtime-validation-contract.md", "quickstart.md", "delivery-verification-20260720.md")) {
    Copy-Item -LiteralPath (Join-Path $accountRoot ("docs\" + $file)) -Destination (Join-Path $accountStage "docs") -Force
}
foreach ($file in @("go.mod", "go.sum", "Dockerfile", "docker-compose.yml", "Makefile", "README.md", ".env.example", ".gitignore", "pytest.ini")) {
    $source = Join-Path $accountRoot $file
    if (Test-Path -LiteralPath $source) {
        Copy-Item -LiteralPath $source -Destination $accountStage -Force
    }
}

foreach ($directory in @("app", "tests", "examples", "migrations", "scripts")) {
    Copy-Item -LiteralPath (Join-Path $permissionRoot $directory) -Destination $permissionStage -Recurse -Force
}
New-Item -ItemType Directory -Force -Path (Join-Path $permissionStage "docs") | Out-Null
foreach ($file in @("api.md", "architecture.md", "database.md", "error-codes.md", "l1-layer-interface-security.md", "platform-integration.md", "delivery-verification-20260720.md", "权限模块联调准备表.md")) {
    Copy-Item -LiteralPath (Join-Path $permissionRoot ("docs\" + $file)) -Destination (Join-Path $permissionStage "docs") -Force
}
foreach ($file in @("requirements.txt", ".env.example", ".gitignore", ".dockerignore", "alembic.ini", "pytest.ini", "Dockerfile", "README.md", "交付清单.md")) {
    Copy-Item -LiteralPath (Join-Path $permissionRoot $file) -Destination $permissionStage -Force
}
$permissionPreparationMarkdown = Join-Path $permissionStage "docs\权限模块联调准备表.md"
$permissionPreparationText = Join-Path $permissionStage "docs\权限模块联调准备表.txt"
if (Test-Path -LiteralPath $permissionPreparationMarkdown) {
    Copy-Item -LiteralPath $permissionPreparationMarkdown -Destination $permissionPreparationText -Force
    Remove-Item -LiteralPath $permissionPreparationMarkdown -Force
}

foreach ($directory in @("app", "tests", "scripts")) {
    Copy-Item -LiteralPath (Join-Path $layerRoot $directory) -Destination $layerStage -Recurse -Force
}
New-Item -ItemType Directory -Force -Path (Join-Path $layerStage "docs") | Out-Null
foreach ($file in @("api.md", "service-registry.md")) {
    Copy-Item -LiteralPath (Join-Path $layerRoot ("docs\" + $file)) -Destination (Join-Path $layerStage "docs") -Force
}
foreach ($file in @("requirements.txt", ".env.example", "docker-compose.yml", "Dockerfile", "README.md")) {
    Copy-Item -LiteralPath (Join-Path $layerRoot $file) -Destination $layerStage -Force
}

foreach ($file in @("README.md", "接口说明.md", "网关模块边界与权限接口映射.md", "账号岗位权限对应关系.md", "账号网关模块联调准备表.md", "联调检查表.md", "VERSION.txt")) {
    Copy-Item -LiteralPath (Join-Path $accountRoot ("handoff\" + $file)) -Destination $handoffStage -Force
}
$tableStage = Join-Path $handoffStage "tables"
New-Item -ItemType Directory -Force -Path $tableStage | Out-Null
foreach ($file in @("api_catalog.csv", "database_dictionary.csv", "error_codes.csv", "gateway_module_boundaries.csv", "gateway_permission_field_mapping.csv", "schema_relationships.csv", "account_position_permission_example.csv")) {
    Copy-Item -LiteralPath (Join-Path $accountRoot ("handoff\tables\" + $file)) -Destination $tableStage -Force
}
$preparationMarkdown = Join-Path $handoffStage "账号网关模块联调准备表.md"
$preparationText = Join-Path $handoffStage "账号网关模块联调准备表.txt"
if (Test-Path -LiteralPath $preparationMarkdown) {
    Copy-Item -LiteralPath $preparationMarkdown -Destination $preparationText -Force
    Remove-Item -LiteralPath $preparationMarkdown -Force
}
Copy-Item -LiteralPath (Join-Path $accountRoot "handoff\README.md") -Destination (Join-Path $stage "README.md") -Force
Copy-Item -LiteralPath (Join-Path $accountRoot "handoff\联调检查表.md") -Destination (Join-Path $stage "联调检查表.md") -Force
Copy-Item -LiteralPath (Join-Path $accountRoot "handoff\VERSION.txt") -Destination (Join-Path $stage "VERSION.txt") -Force

Get-ChildItem -LiteralPath $stage -Directory -Recurse -Filter "__pycache__" |
    ForEach-Object { Remove-Item -LiteralPath $_.FullName -Recurse -Force }
Get-ChildItem -LiteralPath $stage -File -Recurse |
    Where-Object {
        $_.Extension -in @(".pyc", ".db", ".sqlite", ".sqlite3", ".log", ".out", ".test") -or
        $_.Name -in @(".coverage", ".env")
    } |
    ForEach-Object { Remove-Item -LiteralPath $_.FullName -Force }

Compress-Archive -LiteralPath $stage -DestinationPath $zip -CompressionLevel Optimal
Write-Output $zip
