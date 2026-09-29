# Ingest + validate: contracts, entity resolution, conflicts, coverage, point-in-time audit.
param([switch]$Force)
. "$PSScriptRoot\_common.ps1"
if ($Force) { Invoke-Engine ingest --force } else { Invoke-Engine ingest }
Invoke-Engine validate-data
Invoke-Engine coverage
Invoke-Engine pit-audit
