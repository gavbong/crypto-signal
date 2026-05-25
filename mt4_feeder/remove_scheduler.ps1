# remove_scheduler.ps1
# Removes the MT4CandleFeeder scheduled task.

$taskName = "MT4CandleFeeder"
Unregister-ScheduledTask -TaskName $taskName -Confirm:$false -ErrorAction SilentlyContinue
Write-Host "Task '$taskName' removed." -ForegroundColor Yellow
