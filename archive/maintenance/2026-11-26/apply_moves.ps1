$ErrorActionPreference = 'Stop'
$operationDirectory = Split-Path -Parent $MyInvocation.MyCommand.Path
$plan = Get-Content -LiteralPath (Join-Path $operationDirectory 'move_plan.json') -Raw | ConvertFrom-Json
$workspaceRoot = [System.IO.Path]::GetFullPath($plan.root).TrimEnd('\')
$workspacePrefix = $workspaceRoot + '\'
$ledgerPath = Join-Path $operationDirectory 'moves.jsonl'
if (Test-Path -LiteralPath $ledgerPath) { throw 'Move ledger already exists; inspect it before applying again.' }
$failedMoves = 0
foreach ($move in $plan.moves) {
    $sourcePath = [System.IO.Path]::GetFullPath((Join-Path $workspaceRoot $move.source))
    $destinationPath = [System.IO.Path]::GetFullPath((Join-Path $workspaceRoot $move.destination))
    if (-not $sourcePath.StartsWith($workspacePrefix, [System.StringComparison]::OrdinalIgnoreCase) -or
        -not $destinationPath.StartsWith($workspacePrefix, [System.StringComparison]::OrdinalIgnoreCase)) {
        throw 'A move target escaped the checked workspace root.'
    }
    if ($destinationPath.StartsWith($sourcePath + '\', [System.StringComparison]::OrdinalIgnoreCase)) {
        throw 'Cannot move a directory inside itself.'
    }
    try {
        if (-not (Test-Path -LiteralPath $sourcePath)) { throw 'Source is missing.' }
        if (Test-Path -LiteralPath $destinationPath) { throw 'Destination already exists.' }
        $resolvedSource = (Resolve-Path -LiteralPath $sourcePath).Path
        if (-not $resolvedSource.StartsWith($workspacePrefix, [System.StringComparison]::OrdinalIgnoreCase)) {
            throw 'Resolved source escaped the workspace.'
        }
        [System.IO.Directory]::CreateDirectory((Split-Path -Parent $destinationPath)) | Out-Null
        Move-Item -LiteralPath $sourcePath -Destination $destinationPath
        if ((Test-Path -LiteralPath $sourcePath) -or -not (Test-Path -LiteralPath $destinationPath)) {
            throw 'Post-move location verification failed.'
        }
        $entry = @{ source = $move.source; destination = $move.destination; status = 'moved' }
    } catch {
        $failedMoves += 1
        $entry = @{ source = $move.source; destination = $move.destination; status = 'failed'; error = $_.Exception.Message }
        Write-Output ($entry | ConvertTo-Json -Compress)
    }
    Add-Content -LiteralPath $ledgerPath -Value ($entry | ConvertTo-Json -Compress) -Encoding UTF8
}
Write-Output "Moved $($plan.moves.Count - $failedMoves) of $($plan.moves.Count) planned entries."
if ($failedMoves -gt 0) { exit 1 }
