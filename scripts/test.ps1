param()

$ErrorActionPreference = "Stop"
$root = Split-Path -Parent $PSScriptRoot
$example = Join-Path $root "examples\gomoku"
$venvPython = Join-Path $example ".venv\Scripts\python.exe"

if (-not (Test-Path $venvPython)) {
    throw "No example .venv found. Run scripts\dev.ps1 first (or create examples/gomoku/.venv with python -m venv)."
}

Push-Location $example
try {
    & $venvPython -m unittest discover -s tests -t . -v
    $code = $LASTEXITCODE
}
finally {
    Pop-Location
}
exit $code
