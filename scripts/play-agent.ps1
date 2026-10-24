param(
    [int]$GamePort = 8765,
    [int]$GatewayPort = 8766
)

$ErrorActionPreference = "Stop"
$root = Split-Path -Parent $PSScriptRoot
$venvPython = Join-Path $root ".venv\Scripts\python.exe"

if (-not (Test-Path $venvPython)) {
    throw "No .venv found. Run scripts\dev.ps1 first (or create one with python -m venv .venv)."
}

$game = Start-Process -FilePath $venvPython -ArgumentList @("-m", "gamelab", "serve", "--port", $GamePort) -WorkingDirectory $root -PassThru -WindowStyle Hidden
try {
    Write-Host "Game started: http://127.0.0.1:$GamePort"
    Write-Host "Turn Gateway starting: http://127.0.0.1:$GatewayPort"
    & $venvPython -m gamelab.gateway --game "http://127.0.0.1:$GamePort" --port $GatewayPort
}
finally {
    if (-not $game.HasExited) {
        Stop-Process -Id $game.Id -Force -ErrorAction SilentlyContinue
    }
}
