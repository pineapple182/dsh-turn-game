param(
    [string]$Node = ""
)

$ErrorActionPreference = "Stop"
$root = Split-Path -Parent $PSScriptRoot
$plugin = Join-Path $root "dsh-plugin"

if (-not $Node) {
    $bundled = Join-Path $env:USERPROFILE ".dsh\dsh-runtimes\dsh-primary-runtime\dependencies\node\bin\node.exe"
    if (Test-Path $bundled) { $Node = $bundled }
}
if (-not $Node) {
    $command = Get-Command node -ErrorAction SilentlyContinue
    if ($command) { $Node = $command.Source }
}
if (-not $Node) {
    throw "Node not found. Pass -Node <path to node.exe> (the DSH runtime bundles one)."
}

$code = 0
Push-Location $plugin
try {
    foreach ($file in @("test/gateway-client.test.mjs", "test/activation-controller.test.mjs", "test/host.test.mjs")) {
        & $Node $file
        if ($LASTEXITCODE -ne 0) {
            $code = $LASTEXITCODE
            break
        }
    }
}
finally {
    Pop-Location
}
exit $code
