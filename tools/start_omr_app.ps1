param([int]$Port = 8765)
$ErrorActionPreference = 'Stop'
$projectRoot = Split-Path -Parent $PSScriptRoot
$pythonRuntime = Join-Path $env:USERPROFILE '.cache/codex-runtimes/codex-primary-runtime/dependencies/python/python.exe'
if (-not (Test-Path -LiteralPath $pythonRuntime)) { throw 'Python runtime not found. See APP_RUNBOOK.md.' }
$previousPath = $env:PYTHONPATH
$previousEncoding = $env:PYTHONIOENCODING
try {
    $env:PYTHONPATH = (Join-Path $projectRoot '.local_model_deps') + ';' + (Join-Path $projectRoot '.local_cv_deps')
    $env:PYTHONIOENCODING = 'utf-8'
    & $pythonRuntime (Join-Path $projectRoot 'src/omr_app.py') --port $Port --open-browser
} finally {
    $env:PYTHONPATH = $previousPath
    $env:PYTHONIOENCODING = $previousEncoding
}
