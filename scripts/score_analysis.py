import sys, sqlite3
sys.path.insert(0, '/opt/mexc-signal-engine')

DB = '/opt/mexc-signal-engine/signals.db'
conn = sqlite3.connect(DB)
conn.row_factory = sqlite3.Row

print('=== DATA AVAILABILITY ===')
r = conn.execute("""
    SELECT
        COUNT(*) as total,
        SUM(CASE WHEN backtest_run_id IS NULL THEN 1 ELSE 0 END) as live,
        SUM(CASE WHEN backtest_run_id IS NOT NULL THEN 1 ELSE 0 END) as backtest,
        SUM(CASE WHEN quality_score IS NOT NULL THEN 1 ELSE 0 END) as has_score,
        SUM(CASE WHEN outcome IS NOT NULL THEN 1 ELSE 0 END) as has_outcome,
        SUM(CASE WHEN quality_score IS NOT NULL AND outcome IS NOT NULL THEN 1 ELSE 0 END) as both
    FROM signals
""").fetchone()
print(f"  total={r['total']}  live={r['live']}  backtest={r['backtest']}")
print(f"  has_score={r['has_score']}  has_outcome={r['has_outcome']}  score+outcome={r['both']}")

print('\n=== BACKTEST: WIN RATE BY QUALITY SCORE BUCKET ===')
rows = conn.execute("""
    SELECT
        CASE
            WHEN quality_score < 30 THEN 'a<30'
            WHEN quality_score < 35 THEN 'b30-35'
            WHEN quality_score < 40 THEN 'c35-40'
            WHEN quality_score < 45 THEN 'd40-45'
            WHEN quality_score < 50 THEN 'e45-50'
            WHEN quality_score < 55 THEN 'f50-55'
            WHEN quality_score < 60 THEN 'g55-60'
            WHEN quality_score < 65 THEN 'h60-65'
            ELSE 'i65+'
        END as bucket,
        COUNT(*) as n,
        SUM(CASE WHEN outcome IN ('win','tp_hit') THEN 1 ELSE 0 END) as wins,
        ROUND(AVG(CASE WHEN outcome IS NOT NULL THEN pnl_r ELSE NULL END), 3) as avg_r,
        ROUND(SUM(CASE WHEN outcome IS NOT NULL THEN pnl_r ELSE NULL END), 2) as net_r
    FROM signals
    WHERE backtest_run_id IS NOT NULL
      AND quality_score IS NOT NULL
      AND outcome IS NOT NULL
    GROUP BY bucket
    ORDER BY bucket
""").fetchall()
if rows:
    print(f"  {'bucket':8s}  {'n':5s}  {'WR':6s}  {'avg_r':7s}  {'net_r':8s}")
    for r in rows:
        label = r['bucket'][1:]
        wr = r['wins']/r['n'] if r['n'] > 0 else 0
        print(f"  {label:8s}  {r['n']:5d}  {wr:.1%}  {r['avg_r'] or 0:+.3f}R  {r['net_r'] or 0:+.2f}R")
else:
    print('  No backtest data with quality_score')

print('\n=== BACKTEST: CHOPPY — SCORE BUCKET vs OUTCOME ===')
rows = conn.execute("""
    SELECT
        strategy, direction,
        CASE
            WHEN quality_score < 40 THEN 'a<40'
            WHEN quality_score < 45 THEN 'b40-45'
            WHEN quality_score < 50 THEN 'c45-50'
            ELSE 'd50+'
        END as bucket,
        COUNT(*) as n,
        SUM(CASE WHEN outcome IN ('win','tp_hit') THEN 1 ELSE 0 END) as wins,
        ROUND(SUM(COALESCE(pnl_r, 0)), 2) as net_r
    FROM signals
    WHERE backtest_run_id IS NOT NULL
      AND regime = 'choppy'
      AND quality_score IS NOT NULL
      AND outcome IS NOT NULL
    GROUP BY strategy, direction, bucket
    ORDER BY strategy, direction, bucket
""").fetchall()
if rows:
    prev = ''
    for r in rows:
        key = f"{r['strategy']} {r['direction']}"
        wr = r['wins']/r['n'] if r['n'] > 0 else 0
        if key != prev:
            print(f"\n  {key}")
            prev = key
        print(f"    {r['bucket'][1:]:6s}  n={r['n']:4d}  WR={wr:.1%}  net_r={r['net_r']:+.2f}R")
else:
    print('  No backtest choppy data with quality_score')

print('\n=== LIVE SIGNALS: OUTCOME SUMMARY (pre-overhaul, no quality_score) ===')
rows = conn.execute("""
    SELECT strategy, regime, direction,
        COUNT(*) as n,
        SUM(CASE WHEN outcome IN ('win','tp_hit') THEN 1 ELSE 0 END) as wins,
        SUM(CASE WHEN outcome IN ('loss','sl_hit') THEN 1 ELSE 0 END) as losses,
        SUM(CASE WHEN outcome IS NULL THEN 1 ELSE 0 END) as pending,
        ROUND(SUM(COALESCE(pnl_r, 0)), 2) as net_r
    FROM signals
    WHERE backtest_run_id IS NULL
    GROUP BY strategy, regime, direction
    ORDER BY strategy, regime, direction
""").fetchall()
print(f"  {'strategy':22s}  {'regime':16s}  {'dir':5s}  n   WR      net_r  pend")
for r in rows:
    resolved = r['wins'] + r['losses']
    wr = r['wins']/resolved if resolved > 0 else None
    wr_s = f"{wr:.1%}" if wr is not None else 'N/A'
    print(f"  {r['strategy']:22s}  {r['regime']:16s}  {r['direction']:5s}  {r['n']:3d}  {wr_s:6s}  {r['net_r']:+.2f}R  {r['pending']}")

print('\n=== BACKTEST RUNS ===')
rows = conn.execute("""
    SELECT id, started_at, pair_count, signal_count, win_rate, net_r
    FROM backtest_runs ORDER BY started_at DESC LIMIT 5
""").fetchall()
for r in rows:
    print(f"  run#{r['id']}  {r['started_at'][:19]}  pairs={r['pair_count']}  signals={r['signal_count']}  WR={r['win_rate']:.1%}  net_r={r['net_r']:+.2f}R")

print('\n=== SCORE THRESHOLD SWEEP — backtest signals passing each threshold ===')
for thresh in [35, 40, 42, 45, 50, 55]:
    r = conn.execute("""
        SELECT COUNT(*) as n,
               SUM(CASE WHEN outcome IN ('win','tp_hit') THEN 1 ELSE 0 END) as wins,
               ROUND(SUM(COALESCE(pnl_r,0)),2) as net_r
        FROM signals
        WHERE backtest_run_id IS NOT NULL
          AND quality_score IS NOT NULL AND quality_score >= ?
          AND outcome IS NOT NULL
    """, (thresh,)).fetchone()
    wr = r['wins']/r['n'] if r['n'] else 0
    print(f"  score>={thresh:2d}:  n={r['n']:5d}  WR={wr:.1%}  net_r={r['net_r']:+.2f}R")

conn.close()
print('\nDone.')
