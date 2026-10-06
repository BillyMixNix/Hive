$ErrorActionPreference = 'Stop'
$taskRoot = (Resolve-Path -LiteralPath $PSScriptRoot).Path
$sourceRoot = (Resolve-Path -LiteralPath (Join-Path $taskRoot 'repaired-workshop')).Path
$originalRoot = (Resolve-Path -LiteralPath (Join-Path $taskRoot '../HIVE-FACTORIAL-003/repaired-workshop')).Path
$outRoot = Join-Path $taskRoot 'evidence/regression-runtime-artifacts'
if (Test-Path -LiteralPath $outRoot) { throw 'Runtime artifacts already preserved' }
New-Item -ItemType Directory -Path $outRoot | Out-Null
$db = Join-Path $sourceRoot 'data/workshop.db'
$dbBackup = Join-Path $outRoot 'post-tests-workshop.db'
$dbBefore = (Get-FileHash -Algorithm SHA256 -LiteralPath $db).Hash
Copy-Item -LiteralPath $db -Destination $dbBackup
if ((Get-FileHash -Algorithm SHA256 -LiteralPath $dbBackup).Hash -ne $dbBefore) { throw 'Database preservation failed' }
$moves = @()
foreach ($name in @('4bbce47f72','cd24686e0b')) {
    $from = (Resolve-Path -LiteralPath (Join-Path $sourceRoot ('snapshots/' + $name))).Path
    $to = [IO.Path]::GetFullPath((Join-Path $outRoot $name))
    if (-not $from.StartsWith(($sourceRoot + [IO.Path]::DirectorySeparatorChar),[StringComparison]::OrdinalIgnoreCase)) { throw 'Move source escapes isolated source' }
    if (-not $to.StartsWith(($outRoot + [IO.Path]::DirectorySeparatorChar),[StringComparison]::OrdinalIgnoreCase)) { throw 'Move destination escapes evidence' }
    if (Test-Path -LiteralPath (Join-Path $originalRoot ('snapshots/' + $name))) { throw 'Unexpected original snapshot: preserve rather than clean' }
    Move-Item -LiteralPath $from -Destination $to
    $moves += @{Source=$from;PreservedAt=$to}
}
Copy-Item -LiteralPath (Join-Path $originalRoot 'data/workshop.db') -Destination $db
$restored = (Get-FileHash -Algorithm SHA256 -LiteralPath $db).Hash
if ($restored -ne (Get-FileHash -Algorithm SHA256 -LiteralPath (Join-Path $originalRoot 'data/workshop.db')).Hash) { throw 'Database restoration failed' }
$partial = Join-Path $taskRoot 'evidence/final-source-inventory.json'
Copy-Item -LiteralPath $partial -Destination (Join-Path $outRoot 'inventory-before-cleanup.json')
@{Reason='Inherited regression runtime outputs preserved, isolated copy restored; no production code or old evidence changed';DatabaseBefore=$dbBefore;DatabaseRestored=$restored;Moves=$moves} | ConvertTo-Json -Depth 6 | Set-Content -LiteralPath (Join-Path $outRoot 'preservation.json') -Encoding utf8
Write-Output 'Runtime test artifacts preserved; original copied database restored.'
