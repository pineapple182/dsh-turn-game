param(
    [int]$Port = 8765,
    [string]$Python = ""
)

$ErrorActionPreference = "Stop"
$root = Split-Path -Parent $PSScriptRoot
$venvPython = Join-Path $root ".venv\Scripts\python.exe"

if (-not (Test-Path $venvPython)) {
    if (-not $Python) { $Python = $env:GAMELAB_PYTHON }
    if (-not $Python) {
        $command = Get-Command python -ErrorAction SilentlyContinue
        if ($command) { $Python = $command.Source }
    }
    if (-not $Python) {
        throw "Python not found. Pass -Python <path to python.exe> (the DSH bundled interpreter works)."
    }
    Write-Host "Creating virtual environment: $root\.venv"
    & $Python -m venv (Join-Path $root ".venv")
}

Push-Location $root
try {
    Write-Host "Starting game-lab: http://127.0.0.1:$Port"
    & $venvPython -m gamelab serve --port $Port
}
finally {
    Pop-Location
}
