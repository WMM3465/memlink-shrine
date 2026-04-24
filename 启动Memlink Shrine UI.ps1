param(
    [switch]$NoBrowser
)

$root = Split-Path -Parent $MyInvocation.MyCommand.Path
$healthUrl = "http://127.0.0.1:7861/health"

function Find-OpenMemoryEnv {
    $current = Get-Item $root
    while ($null -ne $current) {
        $candidate = Join-Path $current.FullName "__mem0_repo\openmemory\api\.env"
        if (Test-Path -LiteralPath $candidate) {
            return $candidate
        }
        $current = $current.Parent
    }
    return $null
}

function Test-LibraryRunning {
    try {
        $response = Invoke-WebRequest -UseBasicParsing -Uri $healthUrl -TimeoutSec 2
        return $response.StatusCode -eq 200
    }
    catch {
        return $false
    }
}

function Resolve-PythonCommand {
    $python = Get-Command python -ErrorAction SilentlyContinue
    if ($python) {
        return @($python.Source)
    }

    $py = Get-Command py -ErrorAction SilentlyContinue
    if ($py) {
        return @($py.Source, "-3")
    }

    return $null
}

if (-not (Test-LibraryRunning)) {
    $openMemoryEnv = Find-OpenMemoryEnv
    if ($openMemoryEnv -and (Test-Path -LiteralPath $openMemoryEnv)) {
        $googleLine = Select-String -LiteralPath $openMemoryEnv -Pattern '^GOOGLE_API_KEY=' | Select-Object -First 1
        if ($googleLine) {
            $env:GOOGLE_API_KEY = $googleLine.Line.Split('=', 2)[1]
        }
    }

    $env:MEMLINK_SHRINE_GEMINI_MODEL = "gemini-3-flash-preview"
    $env:OPENMEMORY_BASE_URL = "http://localhost:8765"
    $env:OPENMEMORY_USER_ID = "administrator-main"
    $env:OPENMEMORY_APP_NAME = "codex"
    $env:MEMLINK_SHRINE_DB = Join-Path $root "data\memlink_shrine.db"
    $env:PYTHONPATH = $root

    $pythonCommand = Resolve-PythonCommand
    if (-not $pythonCommand) {
        throw "Python interpreter was not found."
    }

    if ($pythonCommand -is [string]) {
        $program = $pythonCommand
        $args = @()
    }
    else {
        $program = $pythonCommand[0]
        $args = @()
        if ($pythonCommand.Count -gt 1) {
            $args += $pythonCommand[1..($pythonCommand.Count - 1)]
        }
    }
    $args += @(
        "-m",
        "uvicorn",
        "memlink_shrine.web:app",
        "--host",
        "127.0.0.1",
        "--port",
        "7861"
    )

    Start-Process -FilePath $program `
        -ArgumentList $args `
        -WorkingDirectory $root `
        -WindowStyle Minimized

    Start-Sleep -Seconds 3
}

if (-not $NoBrowser) {
    Start-Process "http://127.0.0.1:7861"
}


