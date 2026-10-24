param(
    [int]$Port = 8765,
    [string]$Python = ""
)

$ErrorActionPreference = "Stop"
$root = Split-Path -Parent $PSScriptRoot
$example = Join-Path $root "examples\gomoku"
$venvPython = Join-Path $example ".venv\Scripts\python.exe"

if (-not (Test-Path $venvPython)) {
    if (-not $Python) { $Python = $env:GAMELAB_PYTHON }
    if (-not $Python) {
        $bundled = Join-Path $env:USERPROFILE ".dsh\dsh-runtimes\dsh-primary-runtime\dependencies\python\python.exe"
        if (Test-Path $bundled) { $Python = $bundled }
    }
    if (-not $Python) {
        $command = Get-Command python -ErrorAction SilentlyContinue
        if ($command) { $Python = $command.Source }
    }
    if (-not $Python) {
        throw "Python not found. Pass -Python <path to python.exe> (the DSH bundled interpreter works)."
    }
    Write-Host "Creating virtual environment: $example\.venv"
    & $Python -m venv (Join-Path $example ".venv")
}

Push-Location $example
try {
    Write-Host "Starting game example: http://127.0.0.1:$Port"
    & $venvPython -m gamelab serve --port $Port
}
finally {
    Pop-Location
}
