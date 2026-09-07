@echo off
setlocal

REM ── Guard: TradingView must be running ────────────────────────────────────
tasklist /FI "IMAGENAME eq TradingView.exe" 2>NUL | find /I "TradingView.exe" >NUL
if errorlevel 1 (
    echo [%date% %time%] TradingView not running -- skip >> logs\tjl_scanner.log
    exit /b 0
)

REM ── Guard: ET time gate 10:00-14:00 (handles DST automatically) ──────────
for /f "delims=" %%i in ('powershell -NoProfile -Command ^
    "[System.TimeZoneInfo]::ConvertTimeBySystemTimeZoneId([DateTime]::UtcNow, 'Eastern Standard Time').ToString('HHmm')"') do set ETHHMM=%%i
if %ETHHMM% LSS 1000 (
    echo [%date% %time%] Outside ET window (%ETHHMM% ET) -- skip >> logs\tjl_scanner.log
    exit /b 0
)
if %ETHHMM% GEQ 1400 (
    echo [%date% %time%] Outside ET window (%ETHHMM% ET) -- skip >> logs\tjl_scanner.log
    exit /b 0
)

REM ── Run scanner ───────────────────────────────────────────────────────────
cd /d C:\Users\tongl\mexc-signal-engine
if not exist logs mkdir logs
echo [%date% %time%] Starting TJL scan (%ETHHMM% ET) >> logs\tjl_scanner.log
"C:\Program Files\nodejs\node.exe" scripts\tjl_scanner.mjs >> logs\tjl_scanner.log 2>&1
