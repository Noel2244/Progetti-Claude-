# Walk-forward backtest (final holdout protected unless -UseHoldout with a reason).
param([string]$Competitions = "ITA1", [string]$Start = "1995-07-01", [string]$End = "2025-06-30",
      [string]$Models = "", [string]$Primary = "dixon_coles", [switch]$UseHoldout, [string]$HoldoutReason = "")
. "$PSScriptRoot\_common.ps1"
$a = @("backtest", "--competitions", $Competitions, "--start", $Start, "--end", $End, "--primary", $Primary)
if ($Models) { $a += @("--models", $Models) }
if ($UseHoldout) { $a += @("--use-holdout", "--holdout-reason", $HoldoutReason) }
Invoke-Engine @a
