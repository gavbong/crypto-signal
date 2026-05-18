"""
Deep diagnostic: why haven't rsi_divergence, supply_demand, or liquidity_grab
fired in choppy regime today? Checks RSI, candle structure, and S/D zone proximity.
Run on server: /opt/mexc-signal-engine/.venv/bin/python /tmp/diag_why_no_signals.py
"""
import sys
sys.path.insert(0, "/opt/mexc-signal-engine")

import sqlite3
import math
import ccxt
from utils.config import get as cfg

DB_PATH = "/opt/mexc-signal-engine/signals.db"
conn = sqlite3.connect(DB_PATH)
conn.row_factory = sqlite3.Row

# ── latest regime per pair ────────────────────────────────────────────────────
rows = conn.execute("""
    SELECT pair, regime, confidence, age_candles, stable, logged_at
    FROM regime_log
    WHERE (pair, logged_at) IN (
        SELECT pair, MAX(logged_at) FROM regime_log GROUP BY pair
    )
    ORDER BY pair
""").fetchall()

print("\n=== CURRENT REGIMES ===")
choppy_pairs = []
for r in rows:
    print(f"  {r['pair']:25s}  regime={r['regime']:16s}  conf={r['confidence']:.2f}  "
          f"age={r['age_candles']}  stable={r['stable']}  at={r['logged_at'][:19]}")
    if r["regime"] == "choppy" and r["stable"]:
        choppy_pairs.append(r["pair"])

print(f"\nChoppy stable pairs: {choppy_pairs}")

cfg_data = cfg()
tf = cfg_data.get("timeframe", "15m")
rsi_period = cfg_data.get("signals", {}).get("rsi_period", 14)
rsi_overbought = cfg_data.get("signals", {}).get("rsi_overbought", 62)
rsi_oversold = cfg_data.get("signals", {}).get("rsi_oversold", 45)
rsi_div_lookback = cfg_data.get("signals", {}).get("rsi_divergence_lookback", 10)
rsi_div_min_diff = cfg_data.get("signals", {}).get("rsi_divergence_min_diff", 5)
sd_impulse_atr_mult = cfg_data.get("signals", {}).get("sd_impulse_atr_mult", 2.0)

print(f"\nConfig: RSI overbought={rsi_overbought}, oversold={rsi_oversold}, "
      f"rsi_div_lookback={rsi_div_lookback}, rsi_div_min_diff={rsi_div_min_diff}")
print(f"        sd_impulse_atr_mult={sd_impulse_atr_mult}")


def compute_rsi(closes, period=14):
    """Wilder EMA RSI, returns list aligned to closes."""
    if len(closes) < period + 1:
        return [float("nan")] * len(closes)
    gains, losses = [], []
    for i in range(1, len(closes)):
        d = closes[i] - closes[i - 1]
        gains.append(max(d, 0))
        losses.append(max(-d, 0))
    # Initial SMA seed
    avg_g = sum(gains[:period]) / period
    avg_l = sum(losses[:period]) / period
    rsi = [float("nan")] * (period + 1)
    for i in range(period, len(gains)):
        avg_g = (avg_g * (period - 1) + gains[i]) / period
        avg_l = (avg_l * (period - 1) + losses[i]) / period
        rs = avg_g / avg_l if avg_l != 0 else float("inf")
        rsi.append(100 - 100 / (1 + rs))
    return rsi


def compute_atr(ohlcv, period=14):
    """Returns list of ATR values aligned to ohlcv rows."""
    trs = [float("nan")]
    for i in range(1, len(ohlcv)):
        high = ohlcv[i][2]
        low  = ohlcv[i][3]
        prev = ohlcv[i - 1][4]
        tr = max(high - low, abs(high - prev), abs(low - prev))
        trs.append(tr)
    # Simple rolling mean
    atrs = [float("nan")] * period
    for i in range(period, len(trs)):
        atrs.append(sum(trs[i - period + 1:i + 1]) / period)
    return atrs


exchange_map = {
    "BTC/USDT:USDT": ("binance", "BTC/USDT:USDT"),
    "ETH/USDT:USDT": ("binance", "ETH/USDT:USDT"),
    "SOL/USDT:USDT": ("binance", "SOL/USDT:USDT"),
    "UKOIL/USDT:USDT": ("mexc", "UKOIL/USDT:USDT"),
    "XAUT/USDT:USDT": ("mexc", "XAUT/USDT:USDT"),
}

exchange_insts = {}
def get_exchange(name):
    if name not in exchange_insts:
        if name == "binance":
            exchange_insts[name] = ccxt.binance({"options": {"defaultType": "future"}})
        elif name == "mexc":
            exchange_insts[name] = ccxt.mexc({"options": {"defaultType": "swap"}})
        else:
            exchange_insts[name] = getattr(ccxt, name)()
    return exchange_insts[name]


for pair in choppy_pairs:
    ex_name, sym = exchange_map.get(pair, ("binance", pair))
    ex = get_exchange(ex_name)

    print(f"\n{'='*65}")
    print(f"PAIR: {pair}  (exchange: {ex_name})")

    try:
        ohlcv = ex.fetch_ohlcv(sym, tf, limit=60)
    except Exception as e:
        print(f"  ERROR fetching {tf} candles: {e}")
        continue

    closes  = [c[4] for c in ohlcv]
    highs   = [c[2] for c in ohlcv]
    lows    = [c[3] for c in ohlcv]
    opens   = [c[1] for c in ohlcv]
    volumes = [c[5] for c in ohlcv]

    rsi_vals = compute_rsi(closes, rsi_period)
    atr_vals = compute_atr(ohlcv, 14)

    rsi_now  = rsi_vals[-1]
    atr_now  = atr_vals[-1]
    close_now = closes[-1]

    print(f"  close={close_now:.4f}  ATR={atr_now:.4f} ({atr_now/close_now*100:.3f}%)")
    print(f"  RSI={rsi_now:.2f}  (overbought>{rsi_overbought}, oversold<{rsi_oversold})")

    # ── rsi_divergence SHORT ──────────────────────────────────────────────────
    print(f"\n  [rsi_divergence SHORT]")
    if math.isnan(rsi_now):
        print(f"    RSI=NaN — not enough data")
    elif rsi_now <= rsi_overbought:
        last10 = [round(v, 1) for v in rsi_vals[-10:] if not math.isnan(v)]
        print(f"    RSI={rsi_now:.2f} ≤ {rsi_overbought} — SHORT BLOCKED (not overbought)")
        print(f"    RSI last 10: {last10}")
        print(f"    Need RSI to push above {rsi_overbought} to trigger")
    else:
        # RSI is overbought — check bearish divergence
        lb = rsi_div_lookback
        prior_rsi = [v for v in rsi_vals[-lb-1:-1] if not math.isnan(v)]
        prior_highs = highs[-lb-1:-1]
        if not prior_rsi:
            print(f"    Not enough RSI history for divergence check")
        else:
            rsi_prev_max = max(prior_rsi)
            price_prev_max = max(prior_highs)
            rsi_diff = rsi_now - rsi_prev_max
            price_up = close_now > price_prev_max
            rsi_down = rsi_diff < -rsi_div_min_diff
            print(f"    RSI={rsi_now:.2f} > {rsi_overbought} ✓")
            print(f"    RSI prev peak (last {lb} candles): {rsi_prev_max:.2f}")
            print(f"    RSI diff: {rsi_diff:+.2f}  (need < -{rsi_div_min_diff} for lower high)")
            print(f"    Price prev high: {price_prev_max:.4f}, now: {close_now:.4f}")
            print(f"    Price higher high: {'YES ✓' if price_up else 'NO ✗'}")
            print(f"    RSI lower high:    {'YES ✓' if rsi_down else 'NO ✗'}")
            if price_up and rsi_down:
                print(f"    → DIVERGENCE DETECTED — rsi_divergence should have fired!")

    # ── liquidity_grab SHORT ──────────────────────────────────────────────────
    print(f"\n  [liquidity_grab SHORT] (sweep above prev high, close below)")
    triggered = False
    for i in range(-5, 0):
        ci_high  = highs[i]
        ci_close = closes[i]
        pi_high  = highs[i - 1]
        swept    = ci_high > pi_high
        closed_below = ci_close < pi_high
        ts = ohlcv[i][0]
        marker = ""
        if swept and closed_below:
            marker = "  ← GRAB PATTERN"
            triggered = True
        print(f"    [{i}] high={ci_high:.4f} vs prev={pi_high:.4f}  "
              f"close={ci_close:.4f}  swept={swept} closed_below={closed_below}{marker}")
    if not triggered:
        print(f"    → No grab pattern in last 5 candles")

    # ── supply_demand ─────────────────────────────────────────────────────────
    print(f"\n  [supply_demand] (price within 1.5×ATR of 1H S/D zone)")
    prox_window = 1.5 * atr_now
    try:
        ohlcv_1h = ex.fetch_ohlcv(sym, "1h", limit=100)
        atr_1h = compute_atr(ohlcv_1h, 14)

        zones = []
        for i in range(1, len(ohlcv_1h) - 3):
            row = ohlcv_1h[i]
            o, h, l, c = row[1], row[2], row[3], row[4]
            body = abs(c - o)
            atr_i = atr_1h[i]
            if math.isnan(atr_i) or atr_i == 0:
                continue
            if body >= sd_impulse_atr_mult * atr_i:
                if c > o:  # bullish impulse → demand zone below
                    zones.append({"type": "demand", "top": min(o, c), "bot": l})
                else:  # bearish → supply zone above
                    zones.append({"type": "supply", "top": h, "bot": max(o, c)})

        print(f"    Found {len(zones)} zones in 1H. Proximity window: {prox_window:.4f}")
        near = []
        for z in zones:
            dist = min(abs(close_now - z["top"]), abs(close_now - z["bot"]))
            near.append((dist, z))
        near.sort(key=lambda x: x[0])
        print(f"    Nearest 5 zones:")
        any_in_range = False
        for dist, z in near[:5]:
            in_range = dist <= prox_window
            if in_range:
                any_in_range = True
            flag = "IN RANGE" if in_range else "too far"
            print(f"      {z['type']:8s}  top={z['top']:.4f}  bot={z['bot']:.4f}  "
                  f"dist={dist:.4f}  [{flag}]")
        if any_in_range:
            print(f"    → Zone(s) in proximity; check directional candle confirmation")
        else:
            print(f"    → No zones within proximity → supply_demand BLOCKED")
    except Exception as e:
        print(f"    ERROR fetching 1H data: {e}")

# ── recent signals ────────────────────────────────────────────────────────────
print(f"\n{'='*65}")
print("RECENT SIGNALS (last 10, live only):")
recent = conn.execute("""
    SELECT pair, strategy, direction, regime, quality_score, fired_at
    FROM signals
    WHERE backtest_run_id IS NULL
    ORDER BY fired_at DESC
    LIMIT 10
""").fetchall()
if recent:
    for r in recent:
        print(f"  {r['fired_at'][:19]}  {r['pair']:25s}  {r['strategy']:20s}  "
              f"{r['direction']:6s}  score={r['quality_score']}")
else:
    print("  (none)")

conn.close()
print("\nDone.")
