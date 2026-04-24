param(
    [switch]$NoOpenMemory,
    [switch]$NoUi,
    [switch]$NoWatcher,
    [switch]$NoOverlay,
    [switch]$NoBrowser
)

$root = Split-Path -Parent $MyInvocation.MyCommand.Path
$argsList = @()
if ($NoOpenMemory) { $argsList += "-NoOpenMemory" }
if ($NoUi) { $argsList += "-NoUi" }
if ($NoWatcher) { $argsList += "-NoWatcher" }
if ($NoOverlay) { $argsList += "-NoOverlay" }
if ($NoBrowser) { $argsList += "-NoBrowser" }

& (Join-Path $root "start_memlink_shrine_full.ps1") @argsList


