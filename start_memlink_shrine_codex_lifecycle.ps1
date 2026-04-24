$root = Split-Path -Parent $MyInvocation.MyCommand.Path
$watcher = Join-Path $root "memlink_shrine_codex_lifecycle.ps1"
$existing = Get-CimInstance Win32_Process -Filter "name = 'powershell.exe'" -ErrorAction SilentlyContinue |
    Where-Object { $_.CommandLine -like "*memlink_shrine_codex_lifecycle.ps1*" }

if ($existing) {
    Write-Host "Codex memory lifecycle watcher is already running."
    exit 0
}

Start-Process -FilePath "powershell.exe" -ArgumentList @(
    "-NoProfile",
    "-ExecutionPolicy",
    "Bypass",
    "-WindowStyle",
    "Hidden",
    "-File",
    $watcher
) -WindowStyle Hidden

Write-Host "Codex memory lifecycle watcher started."



