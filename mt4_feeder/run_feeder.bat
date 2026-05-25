@echo off
REM MT4 Candle Feeder — single-run mode, launched by Windows Task Scheduler every 15 min
REM Do NOT double-click to run in a loop. Use setup_scheduler.ps1 to register the task.

set INDEX_FEED_URL=https://gavintong.com
set INDEX_FEED_API_KEY=REDACTED_ROTATED_KEY

python "%~dp0mt4_feeder.py"
