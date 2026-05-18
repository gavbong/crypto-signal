import sqlite3

DB = '/opt/mexc-signal-engine/signals.db'
conn = sqlite3.connect(DB)
conn.row_factory = sqlite3.Row

print('=== LIVE SIGNALS PER DAY (last 14d) ===')
rows = conn.execute("""
    SELECT DATE(fired_at) as d, COUNT(*) as n,
           SUM(CASE WHEN outcome IN ('win','tp_hit') THEN 1 ELSE 0 END) as wins,
           SUM(CASE WHEN outcome IN ('loss','sl_hit','stopped_out') THEN 1 ELSE 0 END) as losses,
           SUM(CASE WHEN outcome IS NULL THEN 1 ELSE 0 END) as pending
    FROM signals WHERE backtest_run_id IS NULL
    GROUP BY d ORDER BY d DESC LIMIT 14
""").fetchall()
for r in rows:
    print(f"  {r['d']}  n={r['n']:3d}  wins={r['wins']:2d}  losses={r['losses']:2d}  pending={r['pending']:2d}")

print('\n=== LIVE SIGNAL QUALITY SCORES (all time) ===')
r = conn.execute("""
    SELECT
        COUNT(*) as total,
        SUM(CASE WHEN quality_score IS NULL THEN 1 ELSE 0 END) as no_score,
        SUM(CASE WHEN quality_score < 40 THEN 1 ELSE 0 END) as below_40,
        SUM(CASE WHEN quality_score >= 40 AND quality_score < 45 THEN 1 ELSE 0 END) as q40_45,
        SUM(CASE WHEN quality_score >= 45 AND quality_score < 50 THEN 1 ELSE 0 END) as q45_50,
        SUM(CASE WHEN quality_score >= 50 THEN 1 ELSE 0 END) as q50_plus,
        ROUND(MIN(quality_score),1) as mn,
        ROUND(MAX(quality_score),1) as mx,
        ROUND(AVG(quality_score),1) as avg
    FROM signals WHERE backtest_run_id IS NULL
""").fetchone()
print(f"  total={r['total']}  no_score={r['no_score']}  below_40={r['below_40']}  q40-45={r['q40_45']}  q45-50={r['q45_50']}  q50+={r['q50_plus']}")
print(f"  score range: {r['mn']} - {r['mx']}  avg={r['avg']}")

print('\n=== LIVE SIGNALS: strategy x regime x direction (closed only) ===')
rows = conn.execute("""
    SELECT strategy, regime, direction,
        COUNT(*) as n,
        SUM(CASE WHEN outcome IN ('win','tp_hit') THEN 1 ELSE 0 END) as wins,
        SUM(CASE WHEN outcome IN ('loss','sl_hit','stopped_out') THEN 1 ELSE 0 END) as losses,
        ROUND(AVG(quality_score),1) as avg_qs,
        ROUND(SUM(pnl_r),2) as net_r
    FROM signals WHERE backtest_run_id IS NULL AND outcome IS NOT NULL
    GROUP BY strategy, regime, direction ORDER BY n DESC
""").fetchall()
print(f"  {'strategy':22s}  {'regime':16s}  {'dir':5s}  {'n':4s}  {'WR':5s}  {'avg_qs':6s}  {'net_r':7s}")
for r in rows:
    wr = r['wins']/(r['wins']+r['losses']) if (r['wins']+r['losses']) > 0 else 0
    print(f"  {r['strategy']:22s}  {r['regime']:16s}  {r['direction']:5s}  {r['n']:4d}  {wr:.0%}    {r['avg_qs'] or 0:5.1f}   {r['net_r'] or 0:+.2f}R")

print('\n=== REGIME DISTRIBUTION (live regime_log last 7d) ===')
rows = conn.execute("""
    SELECT pair, regime, COUNT(*) as n
    FROM regime_log
    WHERE logged_at >= datetime('now', '-7 days')
    GROUP BY pair, regime ORDER BY pair, n DESC
""").fetchall()
for r in rows:
    print(f"  {r['pair']:20s}  {r['regime']:16s}  n={r['n']}")

print('\n=== STRATEGY HEALTH STATUS ===')
rows = conn.execute("""
    SELECT strategy, regime, direction, status, win_rate, signal_count
    FROM strategy_health ORDER BY status, strategy
""").fetchall()
for r in rows:
    wr = f"{r['win_rate']:.0%}" if r['win_rate'] else 'N/A'
    print(f"  {r['strategy']:22s}  {r['regime']:16s}  {r['direction']:5s}  {r['status']:10s}  WR={wr}  n={r['signal_count']}")

conn.close()
print('\nDone.')
