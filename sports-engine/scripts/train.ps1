# "Training" = walk-forward backtest that refits every model point-in-time and saves the live
# calibrators; then evaluates promotion gates (runs the leakage test-suite) for the primary model.
param([string]$Competitions = "ITA1", [string]$Start = "2005-07-01", [string]$End = "2025-06-30",
      [string]$Model = "dixon_coles", [string]$Reference = "elo", [switch]$Promote)
. "$PSScriptRoot\_common.ps1"
$out = & $Py -m sports_engine backtest --competitions $Competitions --start $Start --end $End --primary $Model | Out-String
Write-Host $out
$run = ($out | ConvertFrom-Json).run_id
$g = @("gates", "--run-id", $run, "--model", $Model, "--reference", $Reference)
if ($Promote) { $g += "--promote" }
Invoke-Engine @g
