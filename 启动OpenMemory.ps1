param(
    [switch]$WithUi
)

$desktop = [Environment]::GetFolderPath("Desktop")
$repo = Join-Path $desktop "__mem0_repo\openmemory"
if (-not (Test-Path $repo)) {
    throw "OpenMemory repo not found: $repo"
}

try {
    $response = Invoke-WebRequest -Uri "http://127.0.0.1:8765/docs" -UseBasicParsing -TimeoutSec 3
    if ($response.StatusCode -ge 200 -and $response.StatusCode -lt 500) {
        Write-Host "OpenMemory 8765 is already reachable."
        exit 0
    }
}
catch {
    Write-Host "OpenMemory 8765 is not reachable, trying docker compose..."
}

$docker = Get-Command docker -ErrorAction SilentlyContinue
if (-not $docker) {
    throw "Docker command was not found. Start Docker Desktop or install Docker Engine first."
}

$services = @("mem0_store", "openmemory-mcp")
if ($WithUi) {
    $services += "openmemory-ui"
}

Push-Location $repo
try {
    & $docker.Source compose up -d @services
}
finally {
    Pop-Location
}

Write-Host "OpenMemory start command sent. Check http://127.0.0.1:8765/docs"

