param(
    [int]$PollSeconds = 5,
    [int]$StartupDelaySeconds = 10,
    [switch]$KeepOpenMemoryOnCodexExit,
    [switch]$OpenBrowserOnStart,
    [string]$CodexHealthUrl = "https://api.openai.com/v1/models"
)

$root = Split-Path -Parent $MyInvocation.MyCommand.Path
$startScript = Join-Path $root "start_memlink_shrine_full.ps1"
$stopScript = Join-Path $root "停止Memlink Shrine完整系统.ps1"
$statePath = Join-Path $root "data\memlink_shrine_codex_lifecycle_state.json"

function Test-CodexRunning {
    $processes = Get-Process -ErrorAction SilentlyContinue | Where-Object {
        $_.ProcessName -ieq "Codex" -or $_.ProcessName -ieq "codex"
    }
    return [bool]$processes
}

function Write-State {
    param(
        [string]$Status,
        [bool]$CodexRunning = $false,
        [bool]$CodexNetworkOk = $false,
        [string]$Detail = ""
    )
    $payload = @{
        status = $Status
        updated_at = (Get-Date).ToString("o")
        poll_seconds = $PollSeconds
        startup_delay_seconds = $StartupDelaySeconds
        codex_running = $CodexRunning
        codex_network_ok = $CodexNetworkOk
        codex_health_url = $CodexHealthUrl
        detail = $Detail
    }
    $dir = Split-Path -Parent $statePath
    if (-not (Test-Path -LiteralPath $dir)) {
        New-Item -ItemType Directory -Path $dir | Out-Null
    }
    $payload | ConvertTo-Json | Set-Content -LiteralPath $statePath -Encoding UTF8
}

function Test-CodexInternet {
    try {
        $response = Invoke-WebRequest -UseBasicParsing -Uri $CodexHealthUrl -TimeoutSec 5
        return ($response.StatusCode -ge 200 -and $response.StatusCode -lt 500)
    }
    catch {
        if ($_.Exception.Response) {
            try {
                $status = [int]$_.Exception.Response.StatusCode
                return ($status -ge 200 -and $status -lt 500)
            }
            catch {
                return $false
            }
        }
        return $false
    }
}

function Get-CodexSignal {
    try {
        $python = Get-Command python -ErrorAction SilentlyContinue
        if (-not $python) {
            return @{
                status = "neutral"
                signal_source = "codex_session_event"
                issue_type = ""
                issue_message = ""
                last_issue_at = ""
                last_success_at = ""
            }
        }
        $env:PYTHONPATH = $root
        $raw = & $python.Source -m memlink_shrine.codex_status_probe 2>$null
        if (-not $raw) {
            return @{
                status = "neutral"
                signal_source = "codex_session_event"
                issue_type = ""
                issue_message = ""
                last_issue_at = ""
                last_success_at = ""
            }
        }
        return ($raw | ConvertFrom-Json -ErrorAction Stop)
    }
    catch {
        return @{
            status = "neutral"
            signal_source = "codex_session_event"
            issue_type = ""
            issue_message = ""
            last_issue_at = ""
            last_success_at = ""
        }
    }
}

function Start-MemoryRuntime {
    if (-not (Test-Path -LiteralPath $startScript)) {
        throw "Missing start script: $startScript"
    }
    $args = @("-NoProfile", "-ExecutionPolicy", "Bypass", "-File", $startScript)
    if (-not $OpenBrowserOnStart) {
        $args += "-NoBrowser"
    }
    Start-Process -FilePath "powershell.exe" -ArgumentList $args -WindowStyle Hidden
    Write-State "started"
}

function Stop-MemoryRuntime {
    if (-not (Test-Path -LiteralPath $stopScript)) {
        return
    }
    $args = @("-NoProfile", "-ExecutionPolicy", "Bypass", "-File", $stopScript)
    if ($KeepOpenMemoryOnCodexExit) {
        $args += "-KeepOpenMemory"
    }
    Start-Process -FilePath "powershell.exe" -ArgumentList $args -WindowStyle Hidden
    Write-State "stopped"
}

$memoryActive = $false
$codexDetectedAt = $null
$networkIssueObservedAt = $null
Write-State "watching" -CodexRunning:$false -CodexNetworkOk:$false -Detail "Waiting for Codex process"

while ($true) {
    $codexRunning = Test-CodexRunning
    $codexNetworkOk = $false
    $codexSignal = @{
        status = "neutral"
        signal_source = "codex_session_event"
        issue_type = ""
        issue_message = ""
        last_issue_at = ""
        last_success_at = ""
    }
    if ($codexRunning) {
        if (-not $codexDetectedAt) {
            $codexDetectedAt = Get-Date
        }
        $codexSignal = Get-CodexSignal
        if ($codexSignal.status -eq "healthy") {
            $codexNetworkOk = $true
        }
        elseif ($codexSignal.status -eq "network_error") {
            $codexNetworkOk = $false
        }
        else {
            $codexNetworkOk = Test-CodexInternet
        }
    } else {
        $codexDetectedAt = $null
        $networkIssueObservedAt = $null
    }
    $delayReady = $false
    if ($codexRunning -and $codexDetectedAt) {
        $elapsed = ((Get-Date) - $codexDetectedAt).TotalSeconds
        $delayReady = ($elapsed -ge $StartupDelaySeconds)
    }
    if ($codexRunning -and -not $memoryActive -and $delayReady) {
        Start-MemoryRuntime
        $memoryActive = $true
    }
    elseif (-not $codexRunning -and $memoryActive) {
        Stop-MemoryRuntime
        $memoryActive = $false
    }
    if (-not $codexRunning) {
        Write-State "watching" -CodexRunning:$false -CodexNetworkOk:$false -Detail "Waiting for Codex process"
    }
    elseif (-not $delayReady) {
        $remaining = [Math]::Max(0, $StartupDelaySeconds - [int][Math]::Floor(((Get-Date) - $codexDetectedAt).TotalSeconds))
        Write-State "warming_up" -CodexRunning:$true -CodexNetworkOk:$codexNetworkOk -Detail "Codex detected; Memlink will start in ${remaining}s"
    }
    else {
        if ($codexSignal.status -eq "network_error") {
            if (-not $networkIssueObservedAt) {
                $networkIssueObservedAt = Get-Date
            }
            $issueElapsed = ((Get-Date) - $networkIssueObservedAt).TotalSeconds
            if ($issueElapsed -ge 10) {
                Write-State "started_degraded" -CodexRunning:$true -CodexNetworkOk:$false -Detail "Codex connection lost; memory temporarily unavailable"
            } else {
                $remaining = [Math]::Max(0, 10 - [int][Math]::Floor($issueElapsed))
                Write-State "observing_disconnect" -CodexRunning:$true -CodexNetworkOk:$false -Detail "Codex reported network failure; observing for ${remaining}s"
            }
        }
        elseif ($codexNetworkOk) {
            $networkIssueObservedAt = $null
            Write-State "started" -CodexRunning:$true -CodexNetworkOk:$true -Detail "Codex network is reachable"
        }
        else {
            if (-not $networkIssueObservedAt) {
                Write-State "started_degraded" -CodexRunning:$true -CodexNetworkOk:$false -Detail "Codex is offline; Memlink is up but unavailable"
            } else {
                $issueElapsed = ((Get-Date) - $networkIssueObservedAt).TotalSeconds
                if ($issueElapsed -ge 10) {
                    Write-State "started_degraded" -CodexRunning:$true -CodexNetworkOk:$false -Detail "Codex connection lost; memory temporarily unavailable"
                } else {
                    $remaining = [Math]::Max(0, 10 - [int][Math]::Floor($issueElapsed))
                    Write-State "observing_disconnect" -CodexRunning:$true -CodexNetworkOk:$false -Detail "Codex reported network failure; observing for ${remaining}s"
                }
            }
        }
    }
    Start-Sleep -Seconds $PollSeconds
}




