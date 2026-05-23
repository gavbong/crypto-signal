# MT4 Feeder — Setup Guide

Two files. Five steps. The EA runs inside MT4 on your Windows PC; the feeder script POSTs candle data to the Hetzner server.

---

## Step 1 — Install the Expert Advisor

1. Open MT4 → File → Open Data Folder → `MQL4/Experts/`
2. Copy `candle_export.mq4` into that folder
3. In MT4: Navigator → Expert Advisors → right-click → Refresh
4. Open a chart for each instrument (DJ30, FTSE100, DAX, XAUUSD)
5. Drag `candle_export` onto each chart
6. In the EA settings, set `PairName` for each chart:
   - DJ30 chart   → `DJ30/USD`
   - FTSE100 chart → `FTSE100/USD`
   - DAX chart    → `DAX/USD`
   - XAUUSD chart → `XAU/USD`
7. In MT4 → Tools → Options → Expert Advisors: make sure **"Allow automated trading"** is checked

The EA writes files to:
```
%APPDATA%\MetaQuotes\Terminal\Common\Files\candles_<SYMBOL>.json
```

Confirm the files appear and update every 15 minutes before moving to Step 2.

---

## Step 2 — Find your broker's symbol names

Open MT4 → View → Market Watch. The exact symbol names displayed there (e.g. `US30`, `UK100`, `GER40`, `XAUUSD`) must match the keys in `SYMBOL_MAP` in `mt4_feeder.py`.

Edit `mt4_feeder.py` → `SYMBOL_MAP` to match your broker if different from the defaults.

---

## Step 3 — Install Python and dependencies

```powershell
winget install Python.Python.3.12
pip install requests
```

---

## Step 4 — Set environment variables

In PowerShell (or Windows environment variables):

```powershell
$env:INDEX_FEED_URL     = "http://<YOUR_SERVER_IP>:5000"
$env:INDEX_FEED_API_KEY = "your-secret-key-here"
```

The same `INDEX_FEED_API_KEY` must be set on the Hetzner server:
```bash
# On Hetzner, add to /etc/environment or systemd unit:
INDEX_FEED_API_KEY=your-secret-key-here
```

If your server requires SSH tunnel for dashboard access:
```powershell
$env:INDEX_FEED_URL = "http://127.0.0.1:5000"
# Then keep this tunnel open: ssh -i ~/.ssh/id_ed25519 -L 5000:localhost:5000 root@<YOUR_SERVER_IP>
```

---

## Step 5 — Run the feeder

**Single run (test first):**
```powershell
python mt4_feeder\mt4_feeder.py
```

**Continuous loop (leave running):**
```powershell
python mt4_feeder\mt4_feeder.py --loop
```

**Windows Task Scheduler (recommended for production):**
- Action: `python C:\path\to\mexc-signal-engine\mt4_feeder\mt4_feeder.py`
- Trigger: every 15 minutes
- Conditions: only run if network available

---

## Verify it's working

On Hetzner, check the DB:
```bash
ssh root@<YOUR_SERVER_IP>
sqlite3 /opt/mexc-signal-engine/signals.db \
  "SELECT pair, COUNT(*) as n, MAX(datetime(ts,'unixepoch')) as latest FROM index_candles GROUP BY pair;"
```

Expected output after a few hours:
```
DJ30/USD|95|2026-05-27 14:30:00
FTSE100/USD|87|2026-05-27 16:15:00
DAX/USD|92|2026-05-27 17:00:00
XAU/USD|98|2026-05-27 17:15:00
```

---

## Enable signals (after 2 weeks of data)

Once `index_candles` is filling correctly, enable signal generation:

```yaml
# config.yaml on Hetzner
indices:
  enabled: true   # was false
```

Then deploy: `bash scripts/deploy.sh`
