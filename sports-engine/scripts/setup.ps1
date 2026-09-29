# One-time setup: virtual environment, dependencies, folders, environment audit.
$ErrorActionPreference = "Stop"
$Root = Split-Path $PSScriptRoot -Parent
Set-Location $Root
if (Get-Command py -ErrorAction SilentlyContinue) { $python = "py -3.11" } else { $python = "python" }  # PS 5.1 compatible
if (-not (Test-Path ".venv")) { Invoke-Expression "$python -m venv .venv" }
$Py = Join-Path $Root ".venv\Scripts\python.exe"
& $Py -m pip install --upgrade pip
& $Py -m pip install -e ".[api,analytics,dev]"
foreach ($d in "data\raw","data\normalized","data\snapshots","data\features","data\metadata","data\manifests","data\conflicts","data\inbox\football_data","reports","models") {
    New-Item -ItemType Directory -Force -Path $d | Out-Null
}
if (-not (Test-Path ".env")) { Copy-Item ".env.example" ".env" }
& $Py -m sports_engine audit-env
Write-Host "Setup complete. Next: scripts\download_history.ps1" -ForegroundColor Green
