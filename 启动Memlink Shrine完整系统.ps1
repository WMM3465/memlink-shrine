param(
    [switch]$NoBrowser
)

$root = Split-Path -Parent $MyInvocation.MyCommand.Path
$argsList = @()
if ($NoBrowser) { $argsList += "-NoBrowser" }

& (Join-Path $root "start_memlink_shrine_full.ps1") @argsList


