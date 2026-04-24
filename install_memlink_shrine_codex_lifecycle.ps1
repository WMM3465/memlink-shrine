$root = Split-Path -Parent $MyInvocation.MyCommand.Path
$watcher = Join-Path $root "memlink_shrine_codex_lifecycle.ps1"
$starter = Join-Path $root "start_memlink_shrine_codex_lifecycle.ps1"
$taskName = "MemlinkShrineCodexLifecycle"

$action = New-ScheduledTaskAction -Execute "powershell.exe" -Argument "-NoProfile -ExecutionPolicy Bypass -WindowStyle Hidden -File `"$watcher`""
$trigger = New-ScheduledTaskTrigger -AtLogOn
$principal = New-ScheduledTaskPrincipal -UserId $env:USERNAME -LogonType Interactive -RunLevel Limited
$settings = New-ScheduledTaskSettingsSet -AllowStartIfOnBatteries -DontStopIfGoingOnBatteries -MultipleInstances IgnoreNew

Register-ScheduledTask -TaskName $taskName -Action $action -Trigger $trigger -Principal $principal -Settings $settings -Description "Start or stop Memlink Shrine with Codex desktop process." -Force | Out-Null
Write-Host "Installed scheduled task: $taskName"

& $starter





