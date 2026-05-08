## Deploy Configuration
- Platform: Hetzner CX22 — root@46.62.219.155
- Install dir: /opt/mexc-signal-engine
- Production URL: http://localhost:5000 (via SSH tunnel)
- Deploy workflow: `bash scripts/deploy.sh` — git pull + pip install + systemctl restart
- Project type: Python process (signal engine + dashboard + paper trader)
- Post-deploy health check: http://localhost:5000/api/health

### Processes (systemd, auto-restart)
- `mexc-signal-engine` — signal_engine.py (APScheduler, runs indefinitely)
- `mexc-dashboard`     — dashboard.py (Flask on 127.0.0.1:5000)
- `mexc-paper-trader`  — paper_trader.py (APScheduler, runs indefinitely)

### SSH access
- Connect:   `ssh -i ~/.ssh/id_ed25519 root@46.62.219.155`
- Dashboard: `ssh -i ~/.ssh/id_ed25519 -L 5000:localhost:5000 root@46.62.219.155`
- Logs:      `journalctl -fu mexc-signal-engine`

### Custom deploy hooks
- Pre-merge: none
- Deploy trigger: `bash scripts/deploy.sh`
- Health check: `curl http://localhost:5000/api/health`

## Design System
Always read DESIGN.md before making any visual or UI decisions.
All font choices, colors, spacing, border radius, and aesthetic direction are defined there.
Do not deviate without explicit user approval.
Key rules:
- Fonts: Instrument Sans (headers), Outfit (UI labels), JetBrains Mono (all prices/numbers)
- Accent: #F0A500 amber — not blue, not purple
- Radius: 4px max on interactive elements, 2px on inputs/badges
- Win/Long: #22C55E · Short/Loss: #EF4444
- Signature patterns: actuarial dot matrix for win rate, regime timeline bar over candlestick charts
