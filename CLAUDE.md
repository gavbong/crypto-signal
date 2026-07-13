## Deploy Configuration
- Platform: Hetzner CX22 — root@<YOUR_SERVER_IP>
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
- Connect:   `ssh -i ~/.ssh/id_ed25519 root@<YOUR_SERVER_IP>`
- Dashboard: `ssh -i ~/.ssh/id_ed25519 -L 5000:localhost:5000 root@<YOUR_SERVER_IP>`
- Logs:      `journalctl -fu mexc-signal-engine`

### Custom deploy hooks
- Pre-merge: none
- Deploy trigger: `bash scripts/deploy.sh`
- Health check: `curl http://localhost:5000/api/health`

### Code change workflow (REQUIRED ORDER)
After any code or config edit:
1. `git add <files> && git commit -m "..."` — commit locally
2. `git push origin main` — push to GitHub FIRST
3. SSH to server and `git pull --ff-only` + restart affected services

Never deploy (pull on server) before pushing to GitHub. The remote repo must always be the source of truth.

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

## Skill routing

When the user's request matches an available skill, invoke it via the Skill tool. When in doubt, invoke the skill.

Key routing rules:
- Product ideas/brainstorming → invoke /office-hours
- Strategy/scope → invoke /plan-ceo-review
- Architecture → invoke /plan-eng-review
- Design system/plan review → invoke /design-consultation or /plan-design-review
- Full review pipeline → invoke /autoplan
- Bugs/errors → invoke /investigate
- QA/testing site behavior → invoke /qa or /qa-only
- Code review/diff check → invoke /review
- Visual polish → invoke /design-review
- Ship/deploy/PR → invoke /ship or /land-and-deploy
- Save progress → invoke /context-save
- Resume context → invoke /context-restore
