$ErrorActionPreference = 'Stop'
$targetRoot = 'C:\Users\miche\Desktop\KAG-water-cycle'
$backupRoot = Join-Path $targetRoot ('comparison\setup_backups\' + (Get-Date -Format 'yyyyMMdd_HHmmss_fff'))
$files = @('comparison/cli.py', 'comparison/native.py', 'comparison/local_storage.py',
    'comparison/local_generation.py',
    'comparison/local_embeddings.py',
    'comparison/observation.py', 'comparison/presentation.py', 'comparison/projection.py',
    'comparison/config.json', 'comparison/README.md', 'comparison/BACKEND.md',
    'comparison/test_local_pipeline.py', 'setup_water_cycle.ps1', 'run_water_cycle.ps1')
foreach ($relative in $files) {
    $source = Join-Path $PSScriptRoot $relative
    if (-not (Test-Path -LiteralPath $source)) { throw "Missing staged file: $source" }
    $destination = [IO.Path]::GetFullPath((Join-Path $targetRoot $relative))
    if (-not $destination.StartsWith($targetRoot + '\', [StringComparison]::OrdinalIgnoreCase)) {
        throw "Destination outside KAG checkout: $destination"
    }
    if (Test-Path -LiteralPath $destination) {
        $backup = Join-Path $backupRoot $relative
        New-Item -ItemType Directory -Force -Path (Split-Path -Parent $backup) | Out-Null
        Copy-Item -LiteralPath $destination -Destination $backup
    }
    Copy-Item -LiteralPath $source -Destination $destination
}
Write-Host "Updated local KAG runner. Previous files backed up at $backupRoot"
