# Research Lab sanity checks on SYNTHETIC data with known truth:
#   efficient market -> the engine must find no robust edge
#   biased market    -> the engine should detect it (positive fair CLV)
. "$PSScriptRoot\_common.ps1"
Invoke-Engine simulate --scenario efficient
Invoke-Engine simulate --scenario biased
Invoke-Engine experiments
