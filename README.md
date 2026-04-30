# mexc-signal-engine

Crypto trading signal engine for MEXC perpetual futures. Detects regime (trending/ranging/high-vol), fires long/short signals via Telegram, and evaluates outcomes using R-multiples.

## Quick start

```bash
pip install -r requirements.txt
cp .env.example .env   # fill in your keys
python main.py         # starts signal engine
python dashboard.py    # starts dashboard on http://127.0.0.1:5000
```

## Dashboard

Real-time web UI for monitoring live signals and backtest performance.

**Routes served by `dashboard.py`:**

| Route | Description |
|---|---|
| `GET /` | Dashboard HTML |
| `GET /api/signals` | Last 100 signals (`?filter=live\|shadow\|all`) |
| `GET /api/stats` | Win rate, net R, by-regime breakdown (`?since=YYYY-MM-DD`) |
| `GET /api/active` | Top 5 open positions |
| `GET /api/health` | Engine heartbeat (stale if no write in 10 min) |
| `GET /api/regime` | Regime timeline segments |

**Auth:** Set `DASHBOARD_TOKEN` in `.env` to require `Authorization: Bearer <token>` on all API routes. Token is only enforced when `dashboard.host` is not `127.0.0.1`.

**Config** (`config.yaml`):
```yaml
dashboard:
  host: "127.0.0.1"   # change to 0.0.0.0 for remote access
  port: 5000
  debug: false
```

## Tests

```bash
pytest                        # all tests
pytest tests/test_dashboard.py  # dashboard API tests only
```

## Shadow mode

Set `shadow_mode: true` in `config.yaml` to log signals to DB without firing Telegram alerts. Used for walk-forward validation before going live.
