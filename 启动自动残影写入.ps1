param(
    [double]$Interval = 8,
    [int]$SessionLimit = 4
)

$root = Split-Path -Parent $MyInvocation.MyCommand.Path
$env:PYTHONPATH = $root
$env:MEMLINK_SHRINE_DB = Join-Path $root "data\memlink_shrine.db"

function Test-WatcherRunning {
    $processes = Get-CimInstance Win32_Process -Filter "name = 'python.exe'" -ErrorAction SilentlyContinue
    foreach ($process in $processes) {
        if ($process.CommandLine -like "*memlink_shrine.cli*session-auto-watch*") {
            return $true
        }
    }
    return $false
}

if (Test-WatcherRunning) {
    Write-Host "Memlink Shrine session auto writer is already running."
    exit 0
}

$python = Get-Command python -ErrorAction SilentlyContinue
if ($python) {
    $program = $python.Source
    $args = @("-m", "memlink_shrine.cli", "session-auto-watch", "--interval", "$Interval", "--session-limit", "$SessionLimit")
}
else {
    $py = Get-Command py -ErrorAction SilentlyContinue
    if (-not $py) {
        throw "Python interpreter was not found."
    }
    $program = $py.Source
    $args = @("-3", "-m", "memlink_shrine.cli", "session-auto-watch", "--interval", "$Interval", "--session-limit", "$SessionLimit")
}

Start-Process -FilePath $program `
    -ArgumentList $args `
    -WorkingDirectory $root `
    -WindowStyle Minimized




