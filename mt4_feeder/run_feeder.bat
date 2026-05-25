@echo off
REM MT4 Candle Feeder — single-run mode, launched by Windows Task Scheduler every 15 min
REM Do NOT double-click to run in a loop. Use setup_scheduler.ps1 to register the task.
REM
REM INDEX_FEED_URL and INDEX_FEED_API_KEY must be set as User environment variables.
REM Run setup_scheduler.ps1 once to persist them, then this script picks them up automatically.

python "%~dp0mt4_feeder.py"
