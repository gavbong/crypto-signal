# setup_scheduler.ps1
# One-time setup: persists env vars in your user profile, then registers a
# Windows Task Scheduler task that runs mt4_feeder.py every 15 minutes —
# silently, with no CMD window.
#
# Run once from PowerShell (no admin needed):
#   cd C:\...\mexc-signal-engine\mt4_feeder
#   .\setup_scheduler.ps1

$taskName  = "MT4CandleFeeder"
$scriptDir = Split-Path -Parent $MyInvocation.MyCommand.Definition
$pyScript  = Join-Path $scriptDir "mt4_feeder.py"

# Use pythonw.exe (windowless) so no CMD flashes on screen
$pythonw = (Get-Command pythonw -ErrorAction SilentlyContinue).Source
if (-not $pythonw) {
    # Fall back: find pythonw.exe next to python.exe
    $py = (Get-Command python -ErrorAction SilentlyContinue).Source
    if ($py) {
        $pythonw = Join-Path (Split-Path $py) "pythonw.exe"
    }
}
if (-not $pythonw -or -not (Test-Path $pythonw)) {
    Write-Error "pythonw.exe not found. Make sure Python is installed."
    exit 1
}

# Persist env vars at user scope so the scheduled task inherits them
[System.Environment]::SetEnvironmentVariable(
    "INDEX_FEED_URL",
    "https://gavintong.com",
    "User"
)
[System.Environment]::SetEnvironmentVariable(
    "INDEX_FEED_API_KEY",
    "REDACTED_ROTATED_KEY",
    "User"
)
Write-Host "Environment variables saved to user profile." -ForegroundColor Cyan

# Remove existing task before re-registering
Unregister-ScheduledTask -TaskName $taskName -Confirm:$false -ErrorAction SilentlyContinue

$action = New-ScheduledTaskAction `
    -Execute $pythonw `
    -Argument "`"$pyScript`"" `
    -WorkingDirectory $scriptDir

# Every 15 minutes starting 1 minute from now, indefinitely
$trigger = New-ScheduledTaskTrigger `
    -RepetitionInterval (New-TimeSpan -Minutes 15) `
    -Once `
    -At (Get-Date).AddMinutes(1) `
    -RepetitionDuration ([TimeSpan]::MaxValue)

$settings = New-ScheduledTaskSettingsSet `
    -ExecutionTimeLimit (New-TimeSpan -Minutes 5) `
    -MultipleInstances IgnoreNew `
    -StartWhenAvailable `
    -Hidden

$principal = New-ScheduledTaskPrincipal `
    -UserId ([System.Security.Principal.WindowsIdentity]::GetCurrent().Name) `
    -LogonType Interactive `
    -RunLevel Limited

Register-ScheduledTask `
    -TaskName  $taskName `
    -Action    $action `
    -Trigger   $trigger `
    -Settings  $settings `
    -Principal $principal `
    -Force | Out-Null

Write-Host ""
Write-Host "Task '$taskName' registered." -ForegroundColor Green
Write-Host "  Script  : $pyScript"
Write-Host "  Launcher: $pythonw (no window)"
Write-Host "  Fires   : every 15 minutes"
Write-Host ""
Write-Host "Check status : Get-ScheduledTask -TaskName '$taskName'"
Write-Host "Run now      : Start-ScheduledTask -TaskName '$taskName'"
Write-Host "Remove       : .\remove_scheduler.ps1"
