# Acquire historical data into the immutable raw lake (polite, resumable, never re-downloads closed seasons).
param([string]$Competitions = "", [string]$Providers = "", [string]$Seasons = "", [switch]$Force)
. "$PSScriptRoot\_common.ps1"
$a = @("download-history")
if ($Competitions) { $a += @("--competitions", $Competitions) }
if ($Providers) { $a += @("--providers", $Providers) }
if ($Seasons) { $a += @("--seasons", $Seasons) }
if ($Force) { $a += "--force" }
Invoke-Engine @a
Invoke-Engine import-inbox
