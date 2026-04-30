# Changelog

All notable changes to this project will be documented in this file.

## [1.0.1.0] - 2026-04-30

### Added
- Market timezone session tagging on every signal: Asia, London, Overlap (London/NY), New York, Off-hours
- Session label included in Telegram alert messages between Regime and Entry lines

### Changed
- Scan interval reduced from 60 minutes to 15 minutes for faster response to crypto market moves
- Candle timeframe changed from 1h to 15m to match scan cadence
