param()

$ErrorActionPreference = "Stop"
$root = Split-Path -Parent $PSScriptRoot
$venvPython = Join-Path $root ".venv\Scripts\python.exe"

if (-not (Test-Path $venvPython)) {
    throw "No .venv found. Run scripts\dev.ps1 first (or create one with python -m venv .venv)."
}

Push-Location $root
try {
    & $venvPython -m unittest discover -s tests -t . -v
    $code = $LASTEXITCODE
}
finally {
    Pop-Location
}
exit $code
