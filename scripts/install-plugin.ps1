param(
    [string]$Profile = "desktop",
    [string]$Dsh = ""
)

# Development-only helper. Users should install dsh-turn-game from the DSH
# plugin market/mirror or `dsh plugin add dsh-turn-game`; no repo script needed.

$ErrorActionPreference = "Stop"
$root = Split-Path -Parent $PSScriptRoot

if (-not (Test-Path (Join-Path $root "package.json"))) {
    throw "Plugin package not found at repo root: $root"
}

if (-not $Dsh) {
    $bundled = Join-Path $env:LOCALAPPDATA "Programs\DeepSeek Harness\resources\runtime\cli\bin\dsh.cmd"
    if (Test-Path $bundled) {
        $Dsh = $bundled
    }
}
if (-not $Dsh) {
    $command = Get-Command dsh -ErrorAction SilentlyContinue
    if ($command) { $Dsh = $command.Source }
}
if (-not $Dsh) {
    throw "dsh command not found. Pass -Dsh <path to dsh.cmd>."
}

Write-Host "Installing dsh-turn-game from source into profile: $Profile"
Write-Host "Plugin root: $root"
Write-Host "Fully quit DeepSeek Harness (including the tray) first, then restart it after installation."
Write-Host ""

& $Dsh plugin --profile $Profile add $root
$code = $LASTEXITCODE
if ($code -eq 0) {
    Write-Host ""
    Write-Host "Installed. After restarting DSH:"
    Write-Host "  1) Start game + gateway: powershell -ExecutionPolicy Bypass -File scripts\play-agent.ps1"
    Write-Host "  2) Click 'Play the fish' on the web page, then say 'bind the game' in the chat."
}
exit $code
