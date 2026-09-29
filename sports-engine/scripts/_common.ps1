# Shared helpers for the PowerShell scripts. Dot-source: . "$PSScriptRoot\_common.ps1"
$ErrorActionPreference = "Stop"
$Root = Split-Path $PSScriptRoot -Parent
Set-Location $Root
$Py = Join-Path $Root ".venv\Scripts\python.exe"
if (-not (Test-Path $Py)) {
    Write-Host "Virtual environment missing - run scripts\setup.ps1 first." -ForegroundColor Yellow
    exit 1
}
# Simple function (no param block): arguments such as --competitions are passed through verbatim.
function Invoke-Engine {
    & $Py -m sports_engine @args
    if ($LASTEXITCODE -ne 0) { throw "sports_engine $($args -join ' ') failed with exit code $LASTEXITCODE" }
}
