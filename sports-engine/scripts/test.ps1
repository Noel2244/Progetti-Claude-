# Full test-suite (unit, integration, property, temporal/leakage). -Audit also audits dependencies.
param([switch]$Audit, [switch]$LeakageOnly)
. "$PSScriptRoot\_common.ps1"
if ($LeakageOnly) {
    & $Py -m pytest -q tests/test_temporal_leakage.py tests/test_feature_leakage.py tests/test_point_in_time.py tests/test_future_information.py
} else {
    & $Py -m pytest -q
}
if ($LASTEXITCODE -ne 0) { throw "tests failed" }
if ($Audit) {
    & $Py -m pip install --quiet pip-audit
    & $Py -m pip_audit
}
