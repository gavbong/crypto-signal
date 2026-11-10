# mexc-signal-engine

Multi-exchange perpetual futures and index CFD signal engine. Classifies market regime on 1h candles, fires long/short entry signals on 15m candles across MEXC, Binance, OKX (crypto) and Trade Nation (DJ30/FTSE100/DAX indices), and manages a simulated paper-trading account with realistic fees, slippage, and funding costs. A Flask dashboard ties it all together.

---

## Architecture

```
signal_engine.py      â€” APScheduler loop, runs every 15 min
â”œâ”€â”€ regime/classifier.py   â€” trending-up / trending-down / choppy / high-volatility
â”œâ”€â”€ signals/selector.py    â€” regime â†’ active strategies + direction blocks
â”œâ”€â”€ signals/generator.py   â€” per-strategy signal logic, ATR stops, take-profit calc
â”œâ”€â”€ signals/quality.py     â€” composite quality score, strategy health auto-disable
â””â”€â”€ alerts/telegram.py     â€” Telegram signal cards with LLM commentary

paper_trader.py       â€” APScheduler loop, simulates fills with fees + slippage
copy_trader.py        â€” APScheduler loop, mirrors Hyperliquid leaderboard traders
polymarket_trader.py  â€” APScheduler loop, tracks Polymarket wallet positions
dashboard.py          â€” Flask API + single-page dashboard
backtest.py           â€” Offline backtest runner
strategy_advisor.py   â€” Daily strategy health review (net_r + win-rate gates)
eval/outcomes.py      â€” Outcome evaluator (TP / SL / timeout labelling)
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
| MEXC | BTC/USDT:USDT Â· ETH/USDT:USDT Â· SOL/USDT:USDT Â· XAUT/USDT:USDT | Active |
| Binance | BTC/USDT:USDT Â· ETH/USDT:USDT Â· SOL/USDT:USDT | Active |
| OKX | BTC/USDT:USDT Â· ETH/USDT:USDT Â· SOL/USDT:USDT | Active |
| Trade Nation | DJ30/USD Â· FTSE100/USD Â· DAX/USD | Active (index CFDs) |
| Hyperliquid | â€” | Disabled (high slippage + USDC funding costs) |

Toggle exchanges in `config.yaml` under `exchanges.<name>.enabled`.

---

## Regime classifier

Runs on 1h candles before each signal cycle. Output: one of four labels + a confidence score.

| Label | Description |
|---|---|
| `trending-up` | ADX > 25, EMA slope positive, price above fast EMA |
| `trending-down` | ADX > 25, EMA slope negative, price below fast EMA |
| `choppy` | ADX â‰¤ 25, price oscillating within Bollinger Bands |
| `high-volatility` | BB width > 1.5Ã— rolling average |

**Stability gate:** the label must appear in â‰¥ 3 of the last 5 candles before it is used. Regime must also be at least N candles old (`regime_gates.min_regime_age_candles`) before signals fire.

---

## Signal strategies

Each strategy is enabled or disabled per regime in `signals/selector.py`. Direction blocks suppress specific long/short trades calibrated from live results.

| Strategy | Active regimes | Notes |
|---|---|---|
| `ema_9_21_crossover` | trending-up (long), trending-down (short) | EMA 9/21 crossover with volume confirmation |
| `rsi_divergence` | trending-down (short only) | Bearish divergence confirming downtrend; long direction blocked |
| `rsi_extreme` | choppy (ETH only), high-volatility (short only) | RSI exits extreme zone; long blocked in high-vol; BTC/SOL blocked in choppy |
| `vol_breakout` | high-volatility (long only) | Momentum breakout; short direction blocked by live data |
| `supply_demand` | trending-up, trending-down | Zone rejection with trend direction; no edge in choppy (SKIP) |
| `liquidity_grab` | choppy, high-volatility | Stop sweep + reversal; both directions active |
| `session_open_breakout` | trending-up, trending-down, high-volatility | ORB: indices only (DJ30/FTSE100/DAX); first 30 min defines range, fires 30-90 min after open with volume confirmation |

Per-pair skips (configured in `config.yaml â†’ skip_strategies_for_pairs`):
- DAX: `supply_demand`, `liquidity_grab` â€” 0-20% WR in backtest
- DJ30: `supply_demand` â€” 38% WR, âˆ’7.36R in choppy
- BTC/SOL: `rsi_extreme` in choppy only â€” ETH A-grade (WR 59.5%, p=0.005); BTC/SOL D-grade

---

## Risk parameters

Take-profit and stop-loss use ATR-based sizing. RR ratios stack: regime-level defaults are overridden by per-strategy values when present, and by per-regime-per-strategy overrides at the highest precision.

```yaml
# Regime-level RR
rr_ratio_choppy: 1.5
rr_ratio_trending: 2.5
rr_ratio_high_vol: 2.0

# Per-strategy overrides
rr_ratio_strategy:
  liquidity_grab: 2.5       # failed sweeps gap hard through SL
  vol_breakout: 2.0
  rsi_divergence: 2.0
  rsi_extreme: 2.0
  ema_9_21_crossover: 2.0
  session_open_breakout: 1.5  # ORB: range-based SL wider; lower RR keeps TP reachable

# Per-regime-per-strategy (highest priority)
rr_ratio_regime_overrides:
  choppy:
    liquidity_grab: 1.5     # mean-reversion in chop: 2.5R TP never hit; 1.5R is
```

Asset class profiles (`asset_class_profiles`) apply separate stop floor/ceiling for crypto, gold (XAUT), and indices.

---

## Signal quality

Every signal gets a composite quality score (0â€“100) before it fires:

| Component | Weight | Source |
|---|---|---|
| Regime confidence | 20% | Classifier output |
| Rolling 30d win rate | 80% | Live closed signals for this strategy+regime+direction |

Signals below `signal_quality.min_quality_score: 40` are suppressed. A bootstrap win rate of **0.40** is assumed when fewer than 20 live signals exist for a combo.

> **Quality ceiling math:** `score = (0.20 Ã— conf + 0.80 Ã— wr) Ã— 100`. At bootstrap WR 0.40, max score = 52. Do not raise `min_quality_score` above 52 without also raising `bootstrap_wr`, or all new strategy/regime combos will be silently blocked.

**Strategy health auto-disable** (`signals/quality.py`, updated per resolved outcome):

| Status | Condition |
|---|---|
| HEALTHY | WR â‰¥ 38% and net_r/trade â‰¥ âˆ’0.10 |
| CAUTION | WR < 38%, or WR â‰¥ 38% but net_r/trade < âˆ’0.10 |
| DISABLED | WR < 30%, or net_r/trade < âˆ’0.20 (regardless of WR) |
| Re-enabled | WR > 40% sustained for 14+ days |

The net_r/trade gate catches combos that pass the WR breakeven check but still lose money due to bad R:R (e.g. wins too small relative to losses). Thresholds: `net_r_per_trade_caution: -0.10`, `net_r_per_trade_disable: -0.20` in `config.yaml`.

The daily `strategy_advisor.py` review mirrors these thresholds and writes `analysis/review-YYYY-MM-DD.{json,md}`, alerting via Telegram if any DISABLE rows exist.

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
| Signals | Full signals feed â€” pair, direction, regime, entry/stop/target, outcome, P&L R |
| Copy Trader | HL trader account, tracked wallets, open/closed positions, comparison chart |
| Polymarket | PM wallet positions, consensus view, convergence tracker |
| Backtest | Run chips, equity curve, breakdown by strategy Ã— regime, A/B compare mode |
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
| `GET /api/analysis/latest` | Latest strategy health analysis |
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
| `GET /api/backtest/breakdown` | Strategy Ã— regime breakdown |

**Auth:** Set `DASHBOARD_TOKEN` in `.env`. Token is enforced only when `dashboard.host` is not `127.0.0.1`.

---

## Backtest

```bash
python backtest.py --start 2025-01-01 --end 2025-12-31
```

Results are stored in the DB and visible in the Backtest tab. Use A/B compare mode to overlay two runs.

Best full-year run to date (run #22, since 2026-01-01): **+7.14R net, 46.2% WR, Sharpe 0.30, 956 signals.** May-only window (run #19): +13.8R, 49.2% WR, Sharpe 3.67.

---

## LLM integration

Two models are used:

| Model | Role |
|---|---|
| `claude-haiku-4-5-20251001` | Per-signal commentary appended to Telegram alerts |
| `claude-sonnet-4-6` | Daily strategy health analysis (`strategy_advisor.py`) |

Commentary pulls recent CoinTelegraph/CoinDesk RSS headlines for news context. Cached for `llm.cache_ttl_seconds: 300`. Set `ANTHROPIC_API_KEY` in `.env`.

All LLM output fields are HTML-escaped before injection into Telegram `parse_mode=HTML` messages.

---

## Shadow mode

```yaml
shadow_mode: true   # log signals to DB without firing Telegram alerts
```

Walk-forward promotion gates: â‰¥ 38 total shadow signals, â‰¥ 15 per regime, â‰¥ 55% directional accuracy over the evaluation window.

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

**Server:** Hetzner CX22 â€” `root@<YOUR_SERVER_IP>`

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
