# Explicit launch only. Nothing starts automatically when the project is opened.
$ErrorActionPreference = 'Stop'
$pythonPath = Join-Path $PSScriptRoot '.venv/Scripts/python.exe'
if (-not (Test-Path -LiteralPath $pythonPath)) {
    throw 'Run setup_water_cycle.ps1 first to create this project''s separate environment.'
}
& $pythonPath (Join-Path $PSScriptRoot 'run_water_cycle.py') @args
exit $LASTEXITCODE
