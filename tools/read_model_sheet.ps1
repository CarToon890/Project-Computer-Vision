param(
    [Parameter(Mandatory = $true)]
    [ValidatePattern('^S[0-9]{4}$')]
    [string]$Sheet,
    [string]$ModelDir = 'models'
)
$ErrorActionPreference = 'Stop'
$projectRoot = Split-Path -Parent $PSScriptRoot
$bundledPython = Join-Path $env:USERPROFILE '.cache/codex-runtimes/codex-primary-runtime/dependencies/python/python.exe'
if (-not (Test-Path -LiteralPath $bundledPython)) {
    throw 'Bundled Python was not found. See models/README.md for the standard Python command.'
}
$previousPythonPath = $env:PYTHONPATH
$previousEncoding = $env:PYTHONIOENCODING
try {
    $env:PYTHONPATH = (Join-Path $projectRoot '.local_model_deps') + ';' + (Join-Path $projectRoot '.local_cv_deps')
    $env:PYTHONIOENCODING = 'utf-8'
    $modelPath = if ([System.IO.Path]::IsPathRooted($ModelDir)) { $ModelDir } else { Join-Path $projectRoot $ModelDir }
    $resultFolder = if ($ModelDir -eq 'models') { 'model_inference' } else { 'model_inference_v2' }
    & $bundledPython (Join-Path $projectRoot 'src/omr_inference.py') --data-root $projectRoot --model-dir $modelPath --sheet $Sheet --output-dir (Join-Path $projectRoot "presentation_build/$resultFolder/$Sheet")
    if ($LASTEXITCODE -ne 0) { throw "Reading $Sheet failed. See the error above." }
    Write-Output (Join-Path $projectRoot "presentation_build/$resultFolder/$Sheet/report.html")
} finally {
    $env:PYTHONPATH = $previousPythonPath
    $env:PYTHONIOENCODING = $previousEncoding
}
