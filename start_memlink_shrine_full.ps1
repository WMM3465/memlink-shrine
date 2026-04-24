param(
    [switch]$NoOpenMemory,
    [switch]$NoUi,
    [switch]$NoWatcher,
    [switch]$NoOverlay,
    [switch]$NoBrowser,
    [switch]$WithOpenMemoryUi,
    [double]$WatcherInterval = 8,
    [int]$SessionLimit = 4
)

$root = Split-Path -Parent $MyInvocation.MyCommand.Path
$desktop = [Environment]::GetFolderPath("Desktop")
$openMemoryRepo = Join-Path $desktop "__mem0_repo\openmemory"
$libraryHealthUrl = "http://127.0.0.1:7861/health"
$libraryUrl = "http://127.0.0.1:7861"
$openMemoryDocsUrl = "http://127.0.0.1:8765/docs"

if (-not $env:MEMLINK_SHRINE_HOST_ID) { $env:MEMLINK_SHRINE_HOST_ID = "codex-desktop" }
if (-not $env:MEMLINK_SHRINE_HOST_WINDOW_TITLE) { $env:MEMLINK_SHRINE_HOST_WINDOW_TITLE = "Codex" }
if (-not $env:MEMLINK_SHRINE_HOST_REGION_LEFT) { $env:MEMLINK_SHRINE_HOST_REGION_LEFT = "304" }
if (-not $env:MEMLINK_SHRINE_HOST_REGION_TOP) { $env:MEMLINK_SHRINE_HOST_REGION_TOP = "52" }
if (-not $env:MEMLINK_SHRINE_HOST_REGION_RIGHT) { $env:MEMLINK_SHRINE_HOST_REGION_RIGHT = "20" }
if (-not $env:MEMLINK_SHRINE_HOST_REGION_BOTTOM) { $env:MEMLINK_SHRINE_HOST_REGION_BOTTOM = "18" }

function Test-HttpOk {
    param([string]$Url)
    try {
        $response = Invoke-WebRequest -UseBasicParsing -Uri $Url -TimeoutSec 2
        return ($response.StatusCode -ge 200 -and $response.StatusCode -lt 500)
    }
    catch {
        return $false
    }
}

function Resolve-PythonProgram {
    if ($env:MEMLINK_SHRINE_PYTHON -and (Test-Path -LiteralPath $env:MEMLINK_SHRINE_PYTHON)) {
        return @($env:MEMLINK_SHRINE_PYTHON)
    }
    $python = Get-Command python -ErrorAction SilentlyContinue
    if ($python -and $python.Source -and (Test-Path -LiteralPath $python.Source)) {
        return @($python.Source)
    }
    $py = Get-Command py -ErrorAction SilentlyContinue
    if ($py -and $py.Source -and (Test-Path -LiteralPath $py.Source)) {
        return @($py.Source, "-3")
    }
    $wherePython = & where.exe python 2>$null | Select-Object -First 1
    if ($wherePython -and (Test-Path -LiteralPath $wherePython)) {
        return @($wherePython)
    }
    $wherePy = & where.exe py 2>$null | Select-Object -First 1
    if ($wherePy -and (Test-Path -LiteralPath $wherePy)) {
        return @($wherePy, "-3")
    }
    throw "Python interpreter was not found."
}

function Start-PythonModule {
    param(
        [string]$Module,
        [string[]]$ModuleArgs = @(),
        [System.Diagnostics.ProcessWindowStyle]$WindowStyle = [System.Diagnostics.ProcessWindowStyle]::Hidden
    )
    $pythonCommand = @(Resolve-PythonProgram)
    $program = $pythonCommand[0]
    $args = @()
    if ($pythonCommand.Count -gt 1) {
        $args += $pythonCommand[1..($pythonCommand.Count - 1)]
    }
    $args += @("-m", $Module)
    $args += $ModuleArgs
    Start-Process -FilePath $program -ArgumentList $args -WorkingDirectory $root -WindowStyle $WindowStyle
}

function Test-PythonModuleRunning {
    param([string]$Needle)
    $processes = Get-CimInstance Win32_Process -ErrorAction SilentlyContinue | Where-Object { $_.Name -in @('python.exe', 'pythonw.exe') }
    foreach ($process in $processes) {
        if ($process.CommandLine -like "*$Needle*") {
            return $true
        }
    }
    return $false
}

function Load-OpenMemoryEnv {
    $candidate = Join-Path $openMemoryRepo "api\.env"
    if (-not (Test-Path -LiteralPath $candidate)) {
        return
    }
    $googleLine = Select-String -LiteralPath $candidate -Pattern '^GOOGLE_API_KEY=' | Select-Object -First 1
    if ($googleLine) {
        $env:GOOGLE_API_KEY = $googleLine.Line.Split('=', 2)[1]
    }
}

function Load-VcpBridgeEnv {
    $candidate = Join-Path $desktop "__inspect_vcp_toolbox\config.env"
    if (-not (Test-Path -LiteralPath $candidate)) {
        return
    }

    $vcpRoot = Split-Path -Parent $candidate
    $env:VCP_ROOT_PATH = $vcpRoot

    $values = @{}
    Get-Content -LiteralPath $candidate | ForEach-Object {
        if ($_ -match '^\s*([A-Za-z0-9_]+)=(.*)$') {
            $key = $matches[1]
            $value = $matches[2].Trim().Trim('"')
            $values[$key] = $value
        }
    }

    if ($values.ContainsKey('PORT') -and $values['PORT']) {
        $env:VCP_BASE_URL = "http://127.0.0.1:$($values['PORT'])/admin_api/dailynotes"
    }
    if ($values.ContainsKey('AdminUsername') -and $values['AdminUsername']) {
        $env:VCP_ADMIN_USERNAME = $values['AdminUsername']
    }
    if ($values.ContainsKey('AdminPassword') -and $values['AdminPassword']) {
        $env:VCP_ADMIN_PASSWORD = $values['AdminPassword']
    }
    if ($values.ContainsKey('KNOWLEDGEBASE_ROOT_PATH') -and $values['KNOWLEDGEBASE_ROOT_PATH']) {
        $bridgeRoot = $values['KNOWLEDGEBASE_ROOT_PATH']
        if (-not [System.IO.Path]::IsPathRooted($bridgeRoot)) {
            $bridgeRoot = Join-Path $vcpRoot $bridgeRoot
        }
        $env:VCP_BRIDGE_ROOT_PATH = (Resolve-Path -LiteralPath $bridgeRoot).Path
    }
    if (-not $env:VCP_BRIDGE_NAMESPACE) {
        $env:VCP_BRIDGE_NAMESPACE = "MemlinkShrineBridge"
    }
    if (-not $env:VCP_TIMEOUT_SECONDS) {
        $env:VCP_TIMEOUT_SECONDS = "15"
    }
}

function Start-OpenMemoryLayer {
    if (Test-HttpOk $openMemoryDocsUrl) {
        Write-Host "OpenMemory 8765 is already reachable."
        return
    }
    if (-not (Test-Path -LiteralPath $openMemoryRepo)) {
        Write-Host "OpenMemory repo not found, skipping OpenMemory startup: $openMemoryRepo"
        return
    }
    $docker = Get-Command docker -ErrorAction SilentlyContinue
    if (-not $docker) {
        Write-Host "Docker command not found, skipping OpenMemory startup."
        return
    }
    $services = @("mem0_store", "openmemory-mcp")
    if ($WithOpenMemoryUi) {
        $services += "openmemory-ui"
    }
    Push-Location $openMemoryRepo
    try {
        & $docker.Source compose up -d @services
    }
    finally {
        Pop-Location
    }
    Start-Sleep -Seconds 3
}

function Start-WebUi {
    if (-not (Test-HttpOk $libraryHealthUrl)) {
        Load-OpenMemoryEnv
        Load-VcpBridgeEnv
        $env:MEMLINK_SHRINE_GEMINI_MODEL = "gemini-3-flash-preview"
        $env:OPENMEMORY_BASE_URL = "http://localhost:8765"
        $env:OPENMEMORY_USER_ID = "administrator-main"
        $env:OPENMEMORY_APP_NAME = "codex"
        $env:MEMLINK_SHRINE_DB = Join-Path $root "data\memlink_shrine.db"
        $env:PYTHONPATH = $root
        Start-PythonModule -Module "uvicorn" -ModuleArgs @(
            "memlink_shrine.web:app",
            "--host",
            "127.0.0.1",
            "--port",
            "7861"
        )
        Start-Sleep -Seconds 3
    }
    if (-not $NoBrowser) {
        Start-Process $libraryUrl
    }
}

function Set-DefaultSessionMemoryGate {
    if (-not (Test-HttpOk $libraryHealthUrl)) {
        return
    }
    $payload = @{
        mode = "passive"
        confirm_before_write = $true
    } | ConvertTo-Json -Compress
    try {
        $headers = @{ "X-Memory-Host" = $env:MEMLINK_SHRINE_HOST_ID }
        Invoke-RestMethod -Method Put -Uri "http://127.0.0.1:7861/api/session-memory-gate" -Headers $headers -ContentType "application/json" -Body $payload -TimeoutSec 3 | Out-Null
        Write-Host "Memlink Shrine startup default set to passive write; recall stays online."
    }
    catch {
        Write-Host "Could not set Memlink Shrine default mode: $($_.Exception.Message)"
    }
}

function Start-SessionWatcher {
    if (Test-PythonModuleRunning "memlink_shrine.cli*session-auto-watch") {
        Write-Host "Memlink Shrine session auto writer is already running."
        return
    }
    $env:PYTHONPATH = $root
    $env:MEMLINK_SHRINE_DB = Join-Path $root "data\memlink_shrine.db"
    Start-PythonModule -Module "memlink_shrine.cli" -ModuleArgs @(
        "session-auto-watch",
        "--interval",
        "$WatcherInterval",
        "--session-limit",
        "$SessionLimit"
    )
}

function Start-MemlinkShrineOverlay {
    if (Test-PythonModuleRunning "memlink_shrine.shrine_overlay") {
        Write-Host "Memlink Shrine desktop overlay is already running."
        $existing = Get-CimInstance Win32_Process -ErrorAction SilentlyContinue | Where-Object {
            $_.Name -in @('python.exe', 'pythonw.exe') -and $_.CommandLine -like '*memlink_shrine.shrine_overlay*'
        } | Select-Object -First 1
        if ($existing) {
            $script:MemlinkShrineOverlayPid = [int]$existing.ProcessId
        }
        return
    }
    $env:PYTHONPATH = $root
    $env:MEMLINK_SHRINE_API_BASE = "http://127.0.0.1:7861"
    $pythonCommand = @(Resolve-PythonProgram)
    $pythonExe = $pythonCommand[0]
    $pythonwExe = Join-Path (Split-Path -Parent $pythonExe) "pythonw.exe"
    if (Test-Path -LiteralPath $pythonwExe) {
        $process = Start-Process -FilePath $pythonwExe -ArgumentList @("-m", "memlink_shrine.shrine_overlay") -WorkingDirectory $root -WindowStyle Hidden -PassThru
    } else {
        $process = Start-Process -FilePath $pythonExe -ArgumentList @("-m", "memlink_shrine.shrine_overlay") -WorkingDirectory $root -WindowStyle Hidden -PassThru
    }
    if ($process) {
        $script:MemlinkShrineOverlayPid = [int]$process.Id
    }
}

function Repair-MemlinkShrineOverlayOwnership {
    $pythonCommand = @(Resolve-PythonProgram)
    $program = $pythonCommand[0]
    $hostTitle = $env:MEMLINK_SHRINE_HOST_WINDOW_TITLE
    $overlayPid = [int]($script:MemlinkShrineOverlayPid | ForEach-Object { $_ } | Select-Object -First 1)
    if (-not $overlayPid) {
        $existing = Get-CimInstance Win32_Process -ErrorAction SilentlyContinue | Where-Object {
            $_.Name -in @('python.exe', 'pythonw.exe') -and $_.CommandLine -like '*memlink_shrine.shrine_overlay*'
        } | Select-Object -First 1
        if ($existing) {
            $overlayPid = [int]$existing.ProcessId
        }
    }
@"
import ctypes
import time
from ctypes import wintypes

host_hint = r"$hostTitle".strip() or "Codex"
overlay_pid = int($overlayPid)
USER32 = ctypes.windll.user32
GWLP_HWNDPARENT = -8
HWND_TOP = 0
SWP_NOSIZE = 0x0001
SWP_NOMOVE = 0x0002
SWP_NOACTIVATE = 0x0010
SWP_FRAMECHANGED = 0x0020
GetWindowTextLengthW = USER32.GetWindowTextLengthW
GetWindowTextW = USER32.GetWindowTextW
GetWindowThreadProcessId = USER32.GetWindowThreadProcessId
EnumWindows = USER32.EnumWindows
IsWindowVisible = USER32.IsWindowVisible
SetWindowLongPtrW = USER32.SetWindowLongPtrW
SetWindowPos = USER32.SetWindowPos
EnumProc = ctypes.WINFUNCTYPE(wintypes.BOOL, wintypes.HWND, wintypes.LPARAM)

def find_windows():
    found = {"host": 0, "overlay": 0, "candidates": []}
    hint = host_hint.lower()
    @EnumProc
    def cb(hwnd, _lparam):
        length = GetWindowTextLengthW(hwnd)
        if length <= 0:
            return True
        buf = ctypes.create_unicode_buffer(length + 1)
        GetWindowTextW(hwnd, buf, length + 1)
        title = buf.value.strip()
        lowered = title.lower()
        pid = wintypes.DWORD()
        GetWindowThreadProcessId(hwnd, ctypes.byref(pid))
        window_pid = int(pid.value or 0)
        owner = int(ctypes.windll.user32.GetWindowLongPtrW(hwnd, GWLP_HWNDPARENT) or 0)
        if window_pid == overlay_pid and title.startswith("Memlink Shrine"):
            found["overlay"] = int(hwnd)
        elif owner and window_pid != overlay_pid and "Edge" in title:
            found["candidates"].append((int(hwnd), owner))
        if lowered == hint or (hint and hint in lowered):
            if not found["host"]:
                found["host"] = int(hwnd)
        return True
    EnumWindows(cb, 0)
    foreign_owned = [hwnd for hwnd, owner in found["candidates"] if owner == found["host"]]
    return found["host"], found["overlay"], foreign_owned

for _ in range(200):
    host_hwnd, overlay_hwnd, foreign_owned = find_windows()
    if host_hwnd and overlay_hwnd:
        for hwnd in foreign_owned:
            SetWindowLongPtrW(hwnd, GWLP_HWNDPARENT, 0)
            SetWindowPos(
                hwnd,
                HWND_TOP,
                0,
                0,
                0,
                0,
                SWP_NOMOVE | SWP_NOSIZE | SWP_NOACTIVATE | SWP_FRAMECHANGED,
            )
        SetWindowLongPtrW(overlay_hwnd, GWLP_HWNDPARENT, host_hwnd)
        SetWindowPos(
            overlay_hwnd,
            HWND_TOP,
            0,
            0,
            0,
            0,
            SWP_NOMOVE | SWP_NOSIZE | SWP_NOACTIVATE | SWP_FRAMECHANGED,
        )
        break
    time.sleep(0.25)
"@ | & $program -
}

# Full memory-layer activation rule:
# OpenMemory + Memlink Shrine Web UI + session watcher + Memlink Shrine overlay.
if (-not $NoOpenMemory) {
    Start-OpenMemoryLayer
}
if (-not $NoUi) {
    Start-WebUi
    Set-DefaultSessionMemoryGate
}
if (-not $NoWatcher) {
    Start-SessionWatcher
}
if (-not $NoOverlay) {
    Start-MemlinkShrineOverlay
    Repair-MemlinkShrineOverlayOwnership
}




