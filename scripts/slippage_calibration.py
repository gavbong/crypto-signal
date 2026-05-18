"""
Slippage calibration — compares static paper-trader estimates against observed market data.

Entry slippage: signal fires at candle close → real execution = next candle open.
               Adverse = next open > close (long) or next open < close (short).

SL exit slippage: when SL triggered, actual market fill can be worse than SL price
                  if the candle gaps through it. Measured as SL price vs candle low/high.

Run on production server where CCXT + signals.db are available.
"""
import sqlite3, ccxt, time, statistics, sys

DB_PATH = "/opt/mexc-signal-engine/signals.db"
CURRENT_ENTRY_SLIP = 0.0002   # 0.02%
CURRENT_EXIT_SLIP  = 0.0005   # 0.05%

conn = sqlite3.connect(DB_PATH)
conn.row_factory = sqlite3.Row

exchange = ccxt.mexc({"defaultType": "swap"})
exchange.load_markets()

positions = conn.execute("""
    SELECT p.id, p.pair, p.direction, p.strategy, p.regime,
           p.entry_price as fill_entry, p.exit_price as fill_exit,
           p.stop_loss, p.exit_reason, p.margin_usdt, p.contracts,
           p.opened_at, p.closed_at, p.slippage_usdt,
           s.entry_price as sig_entry, s.fired_at, s.timeframe
    FROM paper_positions p
    JOIN signals s ON s.id = p.signal_id
    WHERE p.closed_at IS NOT NULL AND p.exit_price IS NOT NULL
    ORDER BY p.opened_at
""").fetchall()

print(f"Positions to analyse: {len(positions)}\n")

TF_MS = {"15m": 15*60*1000, "1h": 60*60*1000, "4h": 4*60*60*1000}

entry_slippages = []
exit_slippages  = []

for pos in positions:
    pair   = pos["pair"]
    tf     = pos["timeframe"] or "15m"
    tf_ms  = TF_MS.get(tf, 15*60*1000)

    try:
        from datetime import datetime
        fired_ts  = int(datetime.fromisoformat(pos["fired_at"].replace("Z", "+00:00")).timestamp() * 1000)
        closed_ts = int(datetime.fromisoformat(pos["closed_at"].replace("Z", "+00:00")).timestamp() * 1000)

        # --- Entry slippage: next candle open after signal fires ---
        ohlcv = exchange.fetch_ohlcv(pair, tf, since=fired_ts - tf_ms, limit=4)
        next_open = None
        for c in ohlcv:
            if c[0] > fired_ts:
                next_open = c[1]
                break

        sig_entry = pos["sig_entry"]
        if next_open and sig_entry:
            if pos["direction"] == "long":
                slip_pct = (next_open - sig_entry) / sig_entry
            else:
                slip_pct = (sig_entry - next_open) / sig_entry
            entry_slippages.append({
                "pair": pair, "strategy": pos["strategy"],
                "direction": pos["direction"],
                "sig": sig_entry, "next_open": next_open, "slip_pct": slip_pct,
            })

        # --- Exit slippage: for SL exits, how far did the candle gap past SL? ---
        if pos["exit_reason"] == "stop_loss":
            ex_ohlcv = exchange.fetch_ohlcv(pair, tf, since=closed_ts - tf_ms * 2, limit=4)
            sl_price = pos["stop_loss"]
            sl_candle = None
            for c in ex_ohlcv:
                if c[0] <= closed_ts < c[0] + tf_ms:
                    sl_candle = c
                    break
            if not sl_candle and ex_ohlcv:
                sl_candle = ex_ohlcv[-1]

            if sl_candle and sl_price:
                candle_low  = sl_candle[3]
                candle_high = sl_candle[2]
                if pos["direction"] == "long":
                    actual_fill = min(sl_price, candle_low)
                    slip_pct_exit = (sl_price - actual_fill) / sl_price
                else:
                    actual_fill = max(sl_price, candle_high)
                    slip_pct_exit = (actual_fill - sl_price) / sl_price
                exit_slippages.append({
                    "pair": pair, "strategy": pos["strategy"],
                    "direction": pos["direction"], "sl": sl_price,
                    "candle_extreme": candle_low if pos["direction"] == "long" else candle_high,
                    "actual_fill": actual_fill, "slip_pct": slip_pct_exit,
                })

        time.sleep(0.15)

    except Exception as exc:
        print(f"  SKIP {pair}: {exc}")

# --- Report ---
print("=" * 70)
print("ENTRY SLIPPAGE  (signal close → next candle open)")
print(f"Config estimate: {CURRENT_ENTRY_SLIP*100:.3f}%")
print("=" * 70)
for x in entry_slippages:
    sign = "+" if x["slip_pct"] >= 0 else ""
    print(
        f"  {x['pair']:22s} {x['strategy']:20s} {x['direction']:5s}"
        f"  sig={x['sig']:.4f}  next_open={x['next_open']:.4f}"
        f"  slip={sign}{x['slip_pct']*100:.4f}%"
    )

if entry_slippages:
    vals = [x["slip_pct"] for x in entry_slippages]
    adverse = [v for v in vals if v > 0]
    neutral = [v for v in vals if v <= 0]
    print(f"\n  total n={len(vals)}, adverse={len(adverse)}, favourable={len(neutral)}")
    if adverse:
        print(f"  Adverse only:  mean={statistics.mean(adverse)*100:.4f}%  "
              f"median={statistics.median(adverse)*100:.4f}%  max={max(adverse)*100:.4f}%")
    print(f"  All combined:  mean={statistics.mean(vals)*100:.4f}%")
    print(f"\n  VERDICT: config {CURRENT_ENTRY_SLIP*100:.3f}% vs observed "
          f"adverse mean {statistics.mean(adverse)*100:.4f}%" if adverse else "")

print()
print("=" * 70)
print("EXIT SLIPPAGE  (SL price vs candle extreme that triggered it)")
print(f"Config estimate: {CURRENT_EXIT_SLIP*100:.3f}%")
print("=" * 70)
for x in exit_slippages:
    key = "low" if x["direction"] == "long" else "high"
    print(
        f"  {x['pair']:22s} {x['strategy']:20s} {x['direction']:5s}"
        f"  sl={x['sl']:.4f}  candle_{key}={x['candle_extreme']:.4f}"
        f"  gap_slip={x['slip_pct']*100:.4f}%"
    )

if exit_slippages:
    vals = [x["slip_pct"] for x in exit_slippages]
    print(f"\n  total n={len(vals)}")
    print(f"  mean={statistics.mean(vals)*100:.4f}%  "
          f"median={statistics.median(vals)*100:.4f}%  max={max(vals)*100:.4f}%")
    print(f"\n  VERDICT: config {CURRENT_EXIT_SLIP*100:.3f}% vs observed "
          f"mean {statistics.mean(vals)*100:.4f}%")

print()
print("=" * 70)
print("RECOMMENDATIONS")
print("=" * 70)
if entry_slippages:
    adverse = [x["slip_pct"] for x in entry_slippages if x["slip_pct"] > 0]
    if adverse:
        rec_entry = max(statistics.median(adverse), CURRENT_ENTRY_SLIP) * 1.25
        print(f"  entry_slippage_pct: {CURRENT_ENTRY_SLIP:.4f} → {rec_entry:.4f}  "
              f"({rec_entry*100:.3f}%) [median adverse + 25% safety margin]")
if exit_slippages:
    vals = [x["slip_pct"] for x in exit_slippages]
    rec_exit = max(statistics.median(vals), CURRENT_EXIT_SLIP) * 1.25
    print(f"  slippage_pct:       {CURRENT_EXIT_SLIP:.4f} → {rec_exit:.4f}  "
          f"({rec_exit*100:.3f}%) [median + 25% safety margin]")

conn.close()
