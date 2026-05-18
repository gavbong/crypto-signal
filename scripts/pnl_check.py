import sys, sqlite3
sys.path.insert(0, '/opt/mexc-signal-engine')
conn = sqlite3.connect('/opt/mexc-signal-engine/signals.db')
conn.row_factory = sqlite3.Row

print('=== pnl_r reliability (live signals) ===')
rows = conn.execute("""
    SELECT strategy, regime, direction,
        COUNT(*) as n,
        SUM(CASE WHEN outcome IN ('win','tp_hit') THEN 1 ELSE 0 END) as wins,
        SUM(CASE WHEN pnl_r IS NULL THEN 1 ELSE 0 END) as null_r,
        SUM(CASE WHEN pnl_r IS NOT NULL AND pnl_r > 0 THEN 1 ELSE 0 END) as pos_r,
        SUM(CASE WHEN pnl_r IS NOT NULL AND pnl_r <= 0 THEN 1 ELSE 0 END) as nonpos_r,
        ROUND(SUM(COALESCE(pnl_r,0)),2) as net_r
    FROM signals WHERE backtest_run_id IS NULL AND outcome IS NOT NULL
    GROUP BY strategy, regime, direction ORDER BY strategy, regime, direction
""").fetchall()
for r in rows:
    wr = r['wins']/r['n'] if r['n'] else 0
    print(f"  {r['strategy']:22s} {r['regime']:16s} {r['direction']:5s}  n={r['n']:3d} WR={wr:.0%}  pnl_r: null={r['null_r']} pos={r['pos_r']} nonpos={r['nonpos_r']}  net={r['net_r']:+.2f}R")

print('\n=== liquidity_grab choppy long — individual trades ===')
rows = conn.execute("""
    SELECT outcome, pnl_r, entry_price, suggested_stop_loss, suggested_take_profit, fired_at
    FROM signals WHERE backtest_run_id IS NULL AND strategy='liquidity_grab'
    AND regime='choppy' AND direction='long' ORDER BY fired_at DESC LIMIT 12
""").fetchall()
for r in rows:
    entry = r['entry_price'] or 0
    sl = r['suggested_stop_loss'] or 0
    tp = r['suggested_take_profit'] or 0
    risk_pct = abs(entry - sl) / entry * 100 if entry else 0
    print(f"  {r['fired_at'][:16]}  {r['outcome']:8s}  pnl_r={str(r['pnl_r']):8s}  entry={entry:.2f}  sl={sl:.2f}({risk_pct:.2f}%)  tp={tp:.2f}")

print('\n=== rsi_divergence choppy short — individual trades (last 15) ===')
rows = conn.execute("""
    SELECT outcome, pnl_r, entry_price, suggested_stop_loss, fired_at
    FROM signals WHERE backtest_run_id IS NULL AND strategy='rsi_divergence'
    AND regime='choppy' AND direction='short' ORDER BY fired_at DESC LIMIT 15
""").fetchall()
for r in rows:
    entry = r['entry_price'] or 0
    sl = r['suggested_stop_loss'] or 0
    risk_pct = abs(entry - sl) / entry * 100 if entry else 0
    print(f"  {r['fired_at'][:16]}  {r['outcome']:8s}  pnl_r={str(r['pnl_r']):8s}  entry={entry:.2f}  sl={sl:.2f}({risk_pct:.2f}%)")

print('\n=== rsi_divergence choppy long — individual trades (last 15) ===')
rows = conn.execute("""
    SELECT outcome, pnl_r, entry_price, suggested_stop_loss, fired_at
    FROM signals WHERE backtest_run_id IS NULL AND strategy='rsi_divergence'
    AND regime='choppy' AND direction='long' ORDER BY fired_at DESC LIMIT 15
""").fetchall()
for r in rows:
    entry = r['entry_price'] or 0
    sl = r['suggested_stop_loss'] or 0
    risk_pct = abs(entry - sl) / entry * 100 if entry else 0
    print(f"  {r['fired_at'][:16]}  {r['outcome']:8s}  pnl_r={str(r['pnl_r']):8s}  entry={entry:.2f}  sl={sl:.2f}({risk_pct:.2f}%)")

conn.close()
