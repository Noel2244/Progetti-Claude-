# Incremental update without predictions: new data + ingest + reconcile.
. "$PSScriptRoot\_common.ps1"
Invoke-Engine download-history
Invoke-Engine import-inbox
Invoke-Engine ingest
Invoke-Engine paper reconcile
