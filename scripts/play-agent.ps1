param(
    [int]$GamePort = 8765,
    [int]$GatewayPort = 8766
)

$ErrorActionPreference = "Stop"
$root = Split-Path -Parent $PSScriptRoot
$example = Join-Path $root "examples\gomoku"
$venvPython = Join-Path $example ".venv\Scripts\python.exe"

if (-not (Test-Path $venvPython)) {
    throw "No example .venv found. Run scripts\dev.ps1 once (or create examples/gomoku/.venv with python -m venv)."
}

$game = Start-Process -FilePath $venvPython -ArgumentList @("-m", "gamelab", "serve", "--port", $GamePort) -WorkingDirectory $example -PassThru -WindowStyle Hidden
try {
    Write-Host "Game started: http://127.0.0.1:$GamePort"
    Write-Host "Turn Gateway starting: http://127.0.0.1:$GatewayPort"
    Push-Location $example
    try {
        & $venvPython -m gamelab.gateway --game "http://127.0.0.1:$GamePort" --port $GatewayPort
    }
    finally {
        Pop-Location
    }
}
finally {
    if (-not $game.HasExited) {
        Stop-Process -Id $game.Id -Force -ErrorAction SilentlyContinue
    }
}
