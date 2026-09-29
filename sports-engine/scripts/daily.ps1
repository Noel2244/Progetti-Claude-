# Daily pipeline: download -> import -> ingest -> quality -> PIT audit -> reconcile -> paper predictions -> report.
param([int]$Horizon = 7)
. "$PSScriptRoot\_common.ps1"
Invoke-Engine daily --horizon $Horizon
$report = Get-ChildItem "reports\daily\*.md" | Sort-Object LastWriteTime -Descending | Select-Object -First 1
if ($report) { Write-Host "Report: $($report.FullName)" -ForegroundColor Green }
