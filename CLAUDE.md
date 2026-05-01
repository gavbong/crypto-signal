## Deploy Configuration (configured by /setup-deploy)
- Platform: local (runs on this machine)
- Production URL: http://127.0.0.1:5000
- Deploy workflow: manual — pull latest code, restart processes
- Project type: Python process (signal engine + dashboard + paper trader)
- Post-deploy health check: http://127.0.0.1:5000/api/health

### Processes
- `python main.py` — signal engine (APScheduler, runs indefinitely)
- `python dashboard.py` — Flask dashboard on port 5000
- `python paper_trader.py` — paper trading simulator (APScheduler, runs indefinitely)

### Custom deploy hooks
- Pre-merge: none
- Deploy trigger: manual restart of processes after pull
- Deploy status: poll http://127.0.0.1:5000/api/health until 200
- Health check: http://127.0.0.1:5000/api/health

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
