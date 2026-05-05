# Changelog

All notable changes to this project will be documented in this file.

## [1.1.0.1] - 2026-05-05

### Fixed
- `supply_demand`: proximity window now uses ATR from `zone_df` (1H when available) instead of 15m ATR — 15m ATR is 3-5x smaller than 1H zone scale, causing the strategy to near-never fire in production
- `supply_demand`: cross-check 1H zones against the last 20 15m closes to catch intra-hour breaches that 1H data misses before evaluating approach conditions
- `supply_demand`: per-regime RR ratios applied correctly (choppy 1.5×, trending 2.5×, high-vol 2.0×) — previously `rr_map` was duplicated in `signal_engine.py` with no guarantee of staying in sync; now `_calc_take_profit` from `signals.generator` is the single source
- Dashboard: `_migrate_paper_db()` moved into `create_app()` so it runs under gunicorn/pytest app-factory, not only `__main__` — previously caused 500 on first API call after gunicorn restart
- Dashboard: paper-DB migration catches `sqlite3.OperationalError` (column already exists) instead of bare `Exception`, preventing silent swallow of real errors
- Dashboard: `seg.regime` and `seg.signal_count` escaped before `innerHTML` interpolation in regime timeline tooltip (XSS hardening)

### Changed
- Regime timeline bar uses stacked lanes — one lane per regime type — instead of a single overlapping bar; high-volatility regime segments now carry the `.high-volatility` CSS class and appear in the stats grid (QA fixes ISSUE-001/002/004)
- Strategy selector: `supply_demand` fires in `choppy` regime only; removed from `trending-up`, `trending-down`, and `high-volatility` (17% win rate in volatile regimes)
- Strategy selector: `macd_crossover` removed from `choppy` (whipsaws in sideways markets)
- 14 new tests: `TestSupplyDemandApproach` (5 tests for approach-based entry logic, 1H zone preference, fallback), `TestCalcTakeProfit` (5 per-regime RR ratio assertions), fixed vacuous `if result is not None: assert` assertions in old supply/demand tests

## [1.1.0.0] - 2026-05-01

### Added
- Multi-timeframe (MTF) architecture: 1h candles for regime classification, 15m candles for signal indicator calculation
- Three new signal strategies: `macd_crossover`, `supply_demand`, `liquidity_grab`
- Supply/demand zone detection with impulse-candle identification (body > 1.5× ATR), mitigation tracking, and zone cap (3 per side)
- Liquidity grab strategy: 0.3 ATR sweep confirmation + 0.2 ATR return confirmation + minimum 8-candle prior swing
- `ema_signal_fast`/`ema_signal_slow` config keys (9/21) separating signal EMA from regime EMA (20/50)
- 7 new test files covering all new strategies and MTF passthrough (193 tests total, 87% coverage)

### Changed
- `ema_crossover` renamed to `ema_9_21_crossover`; now uses `signals.ema_signal_fast/slow` config keys; volume gate removed; close-above-EMA confirmation added
- `vol_breakout` logic flipped from mean-reversion to momentum breakout with consolidation precondition (≥5 of 8 prior candles inside Bollinger Bands)
- `rsi_extreme` thresholds recalibrated from 30/70 to 35/65; volume gate removed
- Strategy selector updated to 7-strategy map; `GATE` and `SHADOW` action types replaced with `SKIP`
- `rsi_divergence` volume gate removed
- `promotion_gate_per_regime` reduced from 30 to 15 for faster shadow-to-live promotion
- `run_once()` parameter `regime_context` renamed to `regimes_1h` to reflect MTF design
- `RegimeResult` NamedTuple explicitly serialized to plain dict before LLM commentary call (JSON safety)

## [1.0.2.0] - 2026-04-30

### Added
- Paper trading simulator (`paper_trader.py`) for ZEC/USDT:USDT futures
  - 100,000 USDT starting balance, 20x leverage, 2% risk per trade
  - DB-poll architecture: reads from signals table, no signal engine dependency at import time
  - SQLite state persistence — crash-safe and restartable
  - Positions: one open per direction max, risk-sized to lot boundary (0.1 ZEC)
  - Stop-loss and take-profit checked every 15 minutes via live ticker
  - Daily PnL snapshots at midnight UTC written to `logs/paper_trade/YYYY-MM-DD.json`
  - Runs indefinitely

## [1.0.1.0] - 2026-04-30

### Added
- Market timezone session tagging on every signal: Asia, London, Overlap (London/NY), New York, Off-hours
- Session label included in Telegram alert messages between Regime and Entry lines

### Changed
- Scan interval reduced from 60 minutes to 15 minutes for faster response to crypto market moves
- Candle timeframe changed from 1h to 15m to match scan cadence
