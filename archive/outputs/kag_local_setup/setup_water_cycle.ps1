# Install this checkout's separate Python environment. No experiment is run.
param([string]$PythonVersion = '3.11')
$ErrorActionPreference = 'Stop'
Set-StrictMode -Version Latest
Push-Location $PSScriptRoot
try {
    if (-not (Test-Path -LiteralPath '.venv/Scripts/python.exe')) {
        & py "-$PythonVersion" -m venv .venv
        if ($LASTEXITCODE -ne 0) { throw 'Could not create the virtual environment. Install Python 3.10 or 3.11 first.' }
    }
    & ./.venv/Scripts/python.exe -m pip install -e . -r comparison/requirements.txt
    if ($LASTEXITCODE -ne 0) { throw 'Dependency installation failed.' }
    Write-Host 'Python dependencies installed. No pipeline or tests were run.'
    Write-Host 'Keep Ollama running, then use run_water_cycle.ps1. No Docker or OpenSPG server is needed.'
} finally {
    Pop-Location
}
