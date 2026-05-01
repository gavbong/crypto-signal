# Changelog

All notable changes to this project will be documented in this file.

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
