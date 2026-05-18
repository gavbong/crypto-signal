# Handoff — mexc-signal-engine backtest tab

**Date:** 2026-05-12  
**Branch:** main  
**Production:** root@46.62.219.155 · /opt/mexc-signal-engine

---

## Goal

Get the backtest tab in the dashboard fully working end-to-end:
1. User clicks "Run Backtest ▾", picks a start date, clicks ▶ Run
2. `backtest.py` runs as a subprocess, progress updates in real time
3. On completion, equity curve and strategy×regime breakdown table render
4. A/B compare mode overlays two runs and shows a delta table

The deeper goal is a **parameter tuning loop**: change a config value, re-run backtest, compare equity curves to see if it improved. The A/B compare is the insight engine.

---

## Current State

### What works — as of May 12 2026
- **Run #8 completed successfully** — first ever successful end-to-end run
  - 2,177 signals, 985 wins, 45.2% win rate, -67.7R net
  - Runtime: ~9 minutes for 5 pairs × 72 days (2026-03-01 to present)
- Dashboard tab renders with nav, stats row, equity panel, breakdown panel side-by-side
- Progress bar updates in real time (per-pair: "BTC/USDT:USDT done (1/5)")
- API endpoints all return data: `/api/backtest/runs`, `/api/backtest/equity`, `/api/backtest/breakdown`
- Subprocess stderr captured; errors surface as `progress_msg` on failed rows
- Stale run detection marks orphaned runs failed on restart (2-min threshold)
- A/B compare mode: overlaid equity SVG + diff table + config diff label (UI built, untested end-to-end)
- Run chips show readable dates, failed runs show red ✕ + error message

### What has NOT been tested
- **A/B compare mode** — UI exists but needs a second completed run to actually test
- **Equity curve rendering** — endpoints return data but the SVG rendering in the browser has not been visually verified
- **Breakdown table rendering** — data comes through correctly but visual render unverified

---

## Bugs Fixed This Session (3 root causes)

### 1. `KeyError: 'pairs'` (runs 3–5)
`backtest.py` used `c["pairs"]` but config nests pairs under `exchanges.mexc.pairs`.
**Fix:** `pairs = c.get("pairs") or c.get("exchanges", {}).get("mexc", {}).get("pairs", [])`

### 2. O(n²) regime classification (runs 6–7 killed for performance)
`classify()` was called per candle, recomputing ADX/EMA/BBands ~20× each time.  
For 6,967 BTC candles: ~540k full indicator recalculations → ~10 min/pair → ~50 min total.  
**Fix:** Added `classify_series(full_df)` to `regime/classifier.py` — computes all indicators once on the full DataFrame, returns a `list[RegimeResult | None]`. `run_pair` now calls it once and looks up `regimes[i]` in the loop.  
**Speedup:** ~5x per pair (2 min vs 10+ min). Total: ~9 min for 5 pairs.

### 3. Infinite fetch loop for commodity futures (run 7 killed)
MEXC returns **synthetic future candles** for UKOIL (and likely XAUT). The `fetch_history` loop never terminated because every page had exactly 1000 candles, even past today's date.  
**Fix:** `fetch_history` now checks `batch[0][0] > now_ms` to stop when future territory is entered, and trims any future candles from the last valid batch.

---

## Files Changed This Session

| File | What changed |
|------|-------------|
| `backtest.py` | Fixed `c["pairs"]` KeyError; added `from regime.classifier import classify_series`; `run_pair` uses `classify_series` precompute; `fetch_history` stops at `now_ms` |
| `regime/classifier.py` | Added `classify_series(full_df)` — vectorized O(n) regime classification |

---

## Next Step: Verify the UI

Run #8 completed and data is in the DB. The next session should:

1. **Open the dashboard** (SSH tunnel: `ssh -i ~/.ssh/id_ed25519 -L 5000:localhost:5000 root@46.62.219.155`)
2. **Navigate to the Backtest tab**
3. **Select Run #8** from the run chip list
4. **Verify equity curve renders** (SVG line chart, starts at 0, shows cumulative R)
5. **Verify breakdown table renders** (strategy × regime rows with win rate, net R, signal count)
6. **Run a second backtest** (different date range or same for comparison)
7. **Test A/B compare mode** — check both runs, verify equity curves overlay and delta table appears

### If equity curve is blank / chart doesn't render
Check: `curl -s "http://localhost:5000/api/backtest/equity?run_id=8"` — should return a JSON array of `{date, cumulative_r}` objects. The dashboard JS reads this and draws the SVG via D3 or hand-rolled path logic (check `static/dashboard.html` for the equity rendering code).

---

## Run Timing Benchmarks

| Pair | Fetch | Process | Total |
|------|-------|---------|-------|
| BTC/USDT:USDT | ~9s | ~100s | ~2 min |
| ETH/USDT:USDT | ~5s | ~90s | ~1.5 min |
| SOL/USDT:USDT | ~4s | ~90s | ~1.5 min |
| UKOIL/USDT:USDT | ~30s (7 pages, NOW capped) | ~90s | ~2 min |
| XAUT/USDT:USDT | ~10s | ~90s | ~2 min |
| **Total** | | | **~9 min** |

---

## Production DB State

```
Run #8: done | 2026-03-01 → 2026-05-12 | 2177 signals | 45.2% win rate | -67.7R net
Runs #1-7: all failed (see progress_msg for each)
```
