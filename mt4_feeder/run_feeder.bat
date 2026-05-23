@echo off
REM MT4 Candle Feeder — runs continuously, posts to Hetzner every 15 minutes
REM Double-click to start, or add to Windows Task Scheduler.

set INDEX_FEED_URL=https://gavintong.com
set INDEX_FEED_API_KEY=REDACTED_ROTATED_KEY

python "%~dp0mt4_feeder.py" --loop
pause
