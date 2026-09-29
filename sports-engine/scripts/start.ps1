# Local dashboard + API (http://127.0.0.1:8000). Never exposed to the network without a token.
param([int]$Port = 8000)
. "$PSScriptRoot\_common.ps1"
Start-Process "http://127.0.0.1:$Port/"
Invoke-Engine serve --host 127.0.0.1 --port $Port
