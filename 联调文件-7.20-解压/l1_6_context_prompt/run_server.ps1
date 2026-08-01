$ErrorActionPreference = "Stop"

$BundledPython = Join-Path $env:USERPROFILE ".cache\codex-runtimes\codex-primary-runtime\dependencies\python\python.exe"

if (Test-Path $BundledPython) {
  & $BundledPython "$PSScriptRoot\server.py"
} else {
  python "$PSScriptRoot\server.py"
}

