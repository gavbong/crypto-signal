# mexc-signal-engine

Multi-exchange perpetual futures signal engine. Classifies market regime on 1h candles, fires long/short entry signals on 15m candles across MEXC, Binance, and OKX, and manages a simulated paper-trading account with realistic fees, slippage, and funding costs. A Flask dashboard ties it all together.

---

## Architecture

```
signal_engine.py      — APScheduler loop, runs every 15 min
├── regime/classifier.py   — trending-up / trending-down / choppy / high-volatility
├── signals/selector.py    — regime → active strategies + direction blocks
├── signals/generator.py   — per-strategy signal logic, ATR stops, take-profit calc
├── signals/quality.py     — composite quality score, strategy health auto-disable
└── alerts/telegram.py     — Telegram signal cards

paper_trader.py       — APScheduler loop, simulates fills with fees + slippage
copy_trader.py        — APScheduler loop, mirrors Hyperliquid leaderboard traders
polymarket_trader.py  — APScheduler loop, tracks Polymarket wallet positions
dashboard.py          — Flask API + single-page dashboard
backtest.py           — Offline backtest runner
strategy_advisor.py   — LLM-driven weekly strategy health review
eval/outcomes.py      — Outcome evaluator (TP / SL / timeout labelling)
```

**Processes (systemd, all auto-restart):**

| Service | File | Description |
|---|---|---|
| `mexc-signal-engine` | `signal_engine.py` | Signal generation loop |
| `mexc-paper-trader` | `paper_trader.py` | Paper trading loop |
| `mexc-dashboard` | `dashboard.py` | Flask dashboard |

---

## Quick start

```bash
pip install -r requirements.txt
cp .env.example .env        # fill in MEXC_API_KEY, TELEGRAM_BOT_TOKEN, etc.
python signal_engine.py     # starts signal loop (blocking)
python paper_trader.py      # starts paper trader (blocking)
python dashboard.py         # dashboard at http://127.0.0.1:5000
```

---

## Exchanges

| Exchange | Pairs | Status |
|---|---|---|
| MEXC | BTC/USDT:USDT · ETH/USDT:USDT · SOL/USDT:USDT · XAUT/USDT:USDT | Active |
| Binance | BTC/USDT:USDT · ETH/USDT:USDT · SOL/USDT:USDT | Active |
| OKX | BTC/USDT:USDT · ETH/USDT:USDT · SOL/USDT:USDT | Active |
| Hyperliquid | — | Disabled (high slippage + USDC funding costs) |

Toggle exchanges in `config.yaml` under `exchanges.<name>.enabled`.

---

## Regime classifier

Runs on 1h candles before each signal cycle. Output: one of four labels + a confidence score.

| Label | Description |
|---|---|
| `trending-up` | ADX > 25, EMA slope positive, price above fast EMA |
| `trending-down` | ADX > 25, EMA slope negative, price below fast EMA |
| `choppy` | ADX ≤ 25, price oscillating within Bollinger Bands |
| `high-volatility` | BB width > 1.5× rolling average |

**Stability gate:** the label must appear in ≥ 3 of the last 5 candles before it is used. Regime must also be at least N candles old (`regime_gates.min_regime_age_candles`) before signals fire.

---

## Signal strategies

Each strategy is enabled or disabled per regime in `signals/selector.py`. Direction blocks suppress specific long/short trades calibrated from live results.

| Strategy | Active in regimes | Notes |
|---|---|---|
| `ema_9_21_crossover` | trending-up (long only), trending-down (short only) | EMA 9/21 crossover with volume confirmation |
| `volume_spike` | trending-up | Volume > 2× avg; institutional participation |
| `vol_breakout` | trending-down, high-volatility | Momentum breakout with volume gate |
| `rsi_divergence` | choppy (long only) | Price/RSI divergence; short direction blocked by live data |
| `supply_demand` | choppy | 1h supply/demand zone approach detection |
| `liquidity_grab` | choppy, high-volatility | Stop sweep + reversal; confidence gates block losers |
| `rsi_extreme` | high-volatility (short only) | RSI exits extreme zone; long direction blocked by live data |

**Liquidity grab confidence gates** (added 2026-05-18 after live loss analysis):
- choppy + confidence < 0.30 → blocked (WR 40.8%, avg_r −0.078)
- high-volatility + confidence ≥ 0.50 → blocked (trending move, not reversal)

---

## Risk parameters

Take-profit and stop-loss use ATR-based sizing. RR ratios stack: regime-level defaults are overridden by per-strategy values when present.

```yaml
# Regime-level RR
rr_ratio: 2.0          # choppy / high-vol
rr_ratio_choppy: 1.5
rr_ratio_trending: 2.5
rr_ratio_high_vol: 2.0

# Per-strategy overrides (calibrated from 15 live trades, 2026-05-18)
rr_ratio_strategy:
  liquidity_grab: 2.5  # failed sweeps gap hard through SL
  vol_breakout: 2.0
  rsi_divergence: 2.0
  supply_demand: 2.0
  rsi_extreme: 2.0
  ema_9_21_crossover: 2.0

# Stop width by regime
atr_stop_multiplier: 1.5
atr_stop_multiplier_choppy: 2.0
atr_stop_multiplier_high_vol: 2.5
```

Asset class profiles in `asset_class_profiles` apply separate stop floor/ceiling for crypto vs gold (XAUT).

---

## Signal quality

Every signal gets a composite quality score (0–100) before it fires:

| Component | Weight | Source |
|---|---|---|
| Regime confidence | 20% | Classifier output |
| Rolling 30d win rate | 80% | Live closed signals for this pair+strategy+regime |

Signals below `signal_quality.min_quality_score: 40` are suppressed. A bootstrap win rate of 45% is assumed when fewer than 20 live signals exist for a combo.

**Strategy health auto-disable:**

| Status | Win rate threshold |
|---|---|
| WATCH | < 38% |
| CAUTION | < 33% |
| DISABLED | < 30% (approx breakeven at RR 2.33) |
| Re-enabled | > 40% for 14+ days |

---

## Paper trader

Simulates fills on every signal using realistic cost assumptions.

**Cost model (calibrated 2026-05-18, n=15 live trades):**

| Cost | Value | Notes |
|---|---|---|
| Entry slippage | 0.05% | Adverse median 0.037% + margin |
| SL exit slippage | 0.52% | Gap median 0.414% + 25% safety margin |
| Taker fee (entry/SL) | 0.06% | MEXC default |
| Maker fee (TP) | 0% (MEXC), 0.02% (Binance/OKX) | TP exits rest as limit orders |
| Funding | Per-pair 8h rate | Fetched live from MEXC via ccxt, cached 8h |

**Guards:**
- Correlated-pairs guard: blocks stacking same-direction `liquidity_grab` across BTC/ETH/SOL/BNB
- Circuit breaker: pauses new entries after 5 consecutive losses for 4h
- Position timeout: force-closes positions open > 48h
- Stop loss: 20% drawdown on margin triggers close

Config key: `paper_trader` block in `config.yaml`.

---

## Copy trader

Tracks Hyperliquid leaderboard traders. Candidates are scored daily; high-scorers are promoted to active copy status.

```yaml
copy_trader:
  top_n: 5
  min_pnl_30d: 100000       # $100K 30d PnL floor
  poll_interval_minutes: 2  # top traders open/close in minutes
  max_concurrent_positions: 15
  candidate_score_threshold: 2.0
  candidate_promote_cycles: 3
```

---

## Polymarket trader

Tracks Polymarket prediction market positions by wallet address.

```yaml
polymarket_trader:
  top_n: 10
  min_pnl_30d: 50000
  watched_wallets: []       # add wallet addresses from polymarket.com/leaderboard
  poly_discovery_markets: 20
```

---

## Dashboard

Single-page app at `http://localhost:5000`. Six tabs:

| Tab | Description |
|---|---|
| Dashboard | Live paper P&L, equity curve, strategy health cards, regime timeline |
| Signals | Full signals feed — pair, direction, regime, entry/stop/target, outcome, P&L R |
| Copy Trader | HL trader account, tracked wallets, open/closed positions, comparison chart |
| Polymarket | PM wallet positions, consensus view, convergence tracker |
| Backtest | Run chips, equity curve, breakdown by strategy × regime, A/B compare mode |
| Settings | Active exchange pairs |

**API endpoints:**

| Route | Description |
|---|---|
| `GET /api/signals` | Signals feed (`?filter=live\|shadow\|all&limit=N`) |
| `GET /api/stats` | Win rate, net R, regime breakdown (`?since=YYYY-MM-DD`) |
| `GET /api/active` | Open paper positions |
| `GET /api/paper/stats` | Paper account equity, P&L, fees, trades |
| `GET /api/paper/positions` | Open paper positions detail |
| `GET /api/paper/history` | Closed paper trades |
| `GET /api/paper/daily` | Daily P&L series |
| `GET /api/strategy-health` | Strategy health status per combo |
| `POST /api/strategy-health/toggle` | Manual override enable/disable |
| `POST /api/engine/pause` | Pause/resume signal engine |
| `GET /api/regime` | Regime timeline segments |
| `GET /api/health` | Engine heartbeat |
| `GET /api/config/pairs` | Active exchange/pair list |
| `GET /api/analysis/latest` | Latest LLM strategy analysis |
| `GET /api/copy/account` | Copy trader account summary |
| `GET /api/copy/traders` | Active HL traders |
| `GET /api/copy/positions` | Open copy positions |
| `GET /api/copy/candidates` | HL candidate watchlist |
| `GET /api/copy/history` | Closed copy trades |
| `GET /api/copy/comparison` | Copy vs signal engine P&L |
| `GET /api/poly/account` | Polymarket account |
| `GET /api/poly/traders` | Tracked PM wallets |
| `GET /api/poly/positions` | Open PM positions |
| `GET /api/poly/consensus` | Consensus view across wallets |
| `GET /api/poly/convergence` | Convergence tracker |
| `GET /api/backtest/runs` | Backtest run list |
| `GET /api/backtest/equity` | Equity curve for a run |
| `GET /api/backtest/breakdown` | Strategy × regime breakdown |

**Auth:** Set `DASHBOARD_TOKEN` in `.env`. Token is enforced only when `dashboard.host` is not `127.0.0.1`.

---

## Backtest

```bash
python backtest.py --start 2025-01-01 --end 2025-12-31
```

Results are stored in the DB and visible in the Backtest tab. Use A/B compare mode to overlay two runs. Best run to date: Run #12 (+64.20R, 48% WR, 1960 signals).

---

## LLM integration

Two models are used:

| Model | Role |
|---|---|
| `claude-haiku-4-5-20251001` | Per-signal commentary appended to Telegram alerts |
| `claude-sonnet-4-6` | Weekly strategy health analysis (`strategy_advisor.py`) |

Commentary is cached for `llm.cache_ttl_seconds: 300`. Set `ANTHROPIC_API_KEY` in `.env`.

---

## Shadow mode

```yaml
shadow_mode: true   # log signals to DB without firing Telegram alerts
```

Walk-forward promotion gates: ≥ 38 total shadow signals, ≥ 15 per regime, ≥ 55% directional accuracy over the evaluation window.

---

## Calibration scripts

| Script | Purpose |
|---|---|
| `scripts/slippage_calibration.py` | Measure real vs estimated entry/SL slippage from live closed trades |
| `scripts/quality_calibration.py` | Analyse signal quality score distribution |
| `scripts/score_analysis.py` | Score breakdown by strategy and regime |
| `scripts/pnl_check.py` | P&L reconciliation |
| `scripts/pair_comparison.py` | Cross-pair performance comparison |
| `scripts/signal_audit.py` | Signal firing audit |
| `scripts/diag_why_no_signals.py` | Diagnose why a cycle produced no signals |

Run these on the production server where `signals.db` is available.

---

## Production

**Server:** Hetzner CX22 — `root@<YOUR_SERVER_IP>`

```bash
# SSH access
ssh -i ~/.ssh/id_ed25519 root@<YOUR_SERVER_IP>

# Dashboard via tunnel
ssh -i ~/.ssh/id_ed25519 -L 5000:localhost:5000 root@<YOUR_SERVER_IP>

# Deploy
bash scripts/deploy.sh   # git pull + pip install + systemctl restart all

# Logs
journalctl -fu mexc-signal-engine
journalctl -fu mexc-paper-trader
journalctl -fu mexc-dashboard

# Health
curl http://localhost:5000/api/health
curl http://localhost:5000/api/paper/stats
```

---

## Tests

```bash
pytest                               # all tests
pytest tests/test_liquidity_grab.py  # single test file
pytest -x                            # stop on first failure
```

Key test files cover regime classifier, all signal strategies, dedup logic, paper trader fills, copy trader, dashboard API, and Telegram formatting.

---

## Environment variables

| Variable | Required | Description |
|---|---|---|
| `MEXC_API_KEY` | Yes | MEXC API key |
| `MEXC_SECRET` | Yes | MEXC API secret |
| `TELEGRAM_BOT_TOKEN` | Yes | Telegram bot token |
| `TELEGRAM_CHAT_ID` | Yes | Telegram chat/channel ID |
| `ANTHROPIC_API_KEY` | Yes | Claude API key (LLM commentary) |
| `DASHBOARD_TOKEN` | No | Bearer token for remote dashboard access |
| `ARBISCAN_API_KEY` | No | Arbiscan key for on-chain copy trader data |
