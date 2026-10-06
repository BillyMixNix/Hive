$ErrorActionPreference = 'Stop'
$taskArea = [System.IO.Path]::GetFullPath($PSScriptRoot)
$copyRoot = [System.IO.Path]::GetFullPath((Join-Path $taskArea 'Hive/recovery/workshop-source-20261006'))
$quarantineRoot = [System.IO.Path]::GetFullPath((Join-Path $taskArea 'excluded-local-copies'))
$moves = Get-Content -LiteralPath (Join-Path $taskArea 'quarantine-moves.json') -Raw | ConvertFrom-Json
function Assert-Within([string]$path, [string]$root) {
    $resolved = [System.IO.Path]::GetFullPath($path)
    if (-not $resolved.StartsWith($root + [System.IO.Path]::DirectorySeparatorChar, [StringComparison]::OrdinalIgnoreCase)) { throw "Outside recovery boundary: $resolved" }
    return $resolved
}
# Move only copied cache trees, with absolute source and destination containment checked.
$cacheRoots = @($moves | ForEach-Object {
    $source = Assert-Within $_.source $copyRoot
    $marker = '\approved-gradle-caches\'
    $index = $source.IndexOf($marker, [StringComparison]::OrdinalIgnoreCase)
    if ($index -ge 0) { $source.Substring(0, $index + $marker.Length - 1) }
} | Sort-Object -Unique)
foreach ($sourcePath in $cacheRoots) {
    $source = Assert-Within $sourcePath $copyRoot
    $relative = $source.Substring($copyRoot.Length + 1)
    $destination = Assert-Within (Join-Path $quarantineRoot $relative) $quarantineRoot
    New-Item -ItemType Directory -Path (Split-Path -Parent $destination) -Force | Out-Null
    if (Test-Path -LiteralPath $destination) { throw 'Destination already exists' }
    Move-Item -LiteralPath $source -Destination $destination
}
$individual = 0
foreach ($entry in $moves) {
    $source = Assert-Within $entry.source $copyRoot
    $destination = Assert-Within $entry.destination $quarantineRoot
    if (Test-Path -LiteralPath $source -PathType Leaf) {
        New-Item -ItemType Directory -Path (Split-Path -Parent $destination) -Force | Out-Null
        Move-Item -LiteralPath $source -Destination $destination
        $individual++
    } elseif (-not (Test-Path -LiteralPath $destination -PathType Leaf)) { throw "Missing copied exclusion: $source" }
}
# Restore only the included provenance records from unchanged original files.
$restored = 0
Get-Content -LiteralPath (Join-Path $copyRoot 'INCLUDED-FILES.jsonl') | ForEach-Object {
    $entry = $_ | ConvertFrom-Json
    if ($entry.path.Contains('/approved-gradle-caches/')) {
        $destination = Assert-Within (Join-Path $copyRoot $entry.path) $copyRoot
        New-Item -ItemType Directory -Path (Split-Path -Parent $destination) -Force | Out-Null
        Copy-Item -LiteralPath $entry.origin -Destination $destination
        $restored++
    }
}
[PSCustomObject]@{cacheTreesMoved=$cacheRoots.Count; individualCopiesMoved=$individual; provenanceRecordsRestored=$restored} | ConvertTo-Json
