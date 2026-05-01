# Changelog

All notable changes to this project will be documented in this file.

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
