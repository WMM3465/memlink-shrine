param(
    [switch]$KeepOpenMemory
)

$root = Split-Path -Parent $MyInvocation.MyCommand.Path
$desktop = [Environment]::GetFolderPath("Desktop")
$openMemoryRepo = Join-Path $desktop "__mem0_repo\openmemory"

function Stop-PythonByNeedle {
    param([string]$Needle)
    $processes = Get-CimInstance Win32_Process -Filter "name = 'python.exe'" -ErrorAction SilentlyContinue
    foreach ($process in $processes) {
        if ($process.CommandLine -like "*$Needle*") {
            Write-Host "Stopping $Needle pid=$($process.ProcessId)"
            Stop-Process -Id $process.ProcessId -Force -ErrorAction SilentlyContinue
        }
    }
}

Stop-PythonByNeedle "memlink_shrine.shrine_overlay"
Stop-PythonByNeedle "memlink_shrine.cli*session-auto-watch"
Stop-PythonByNeedle "uvicorn*memlink_shrine.web:app"
Stop-PythonByNeedle "memlink_shrine.web:app"

if (-not $KeepOpenMemory -and (Test-Path -LiteralPath $openMemoryRepo)) {
    $docker = Get-Command docker -ErrorAction SilentlyContinue
    if ($docker) {
        Push-Location $openMemoryRepo
        try {
            & $docker.Source compose stop openmemory-mcp mem0_store openmemory-ui
        }
        finally {
            Pop-Location
        }
    }
}

Write-Host "Memlink Shrine runtime stopped."




