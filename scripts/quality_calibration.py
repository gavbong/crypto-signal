"""
Quality score calibration analysis — run #11 (first backtest with quality_score stored).
Answers: what min_quality_score threshold maximises risk-adjusted returns?
"""
import sys, sqlite3, math
sys.path.insert(0, '/opt/mexc-signal-engine')

DB = '/opt/mexc-signal-engine/signals.db'
RUN_ID = 11

conn = sqlite3.connect(DB)
conn.row_factory = sqlite3.Row

# ── 0. data availability ──────────────────────────────────────────────────────
r = conn.execute("""
    SELECT COUNT(*) as n,
           SUM(CASE WHEN quality_score IS NOT NULL THEN 1 ELSE 0 END) as scored,
           SUM(CASE WHEN outcome IS NOT NULL THEN 1 ELSE 0 END) as resolved
    FROM signals WHERE backtest_run_id=?
""", (RUN_ID,)).fetchone()
print(f"Run #{RUN_ID}: total={r['n']}  scored={r['scored']}  resolved={r['resolved']}")

# ── 1. score distribution ─────────────────────────────────────────────────────
print('\n=== SCORE DISTRIBUTION (all signals) ===')
rows = conn.execute("""
    SELECT
        CAST(quality_score/5 AS INT)*5 as bucket_floor,
        COUNT(*) as n,
        SUM(CASE WHEN outcome IN ('win','tp_hit') THEN 1 ELSE 0 END) as wins,
        SUM(CASE WHEN outcome IN ('loss','sl_hit','stopped_out') THEN 1 ELSE 0 END) as losses,
        ROUND(AVG(pnl_r), 3) as avg_r,
        ROUND(SUM(pnl_r), 2) as net_r
    FROM signals
    WHERE backtest_run_id=? AND quality_score IS NOT NULL AND outcome IS NOT NULL
    GROUP BY bucket_floor ORDER BY bucket_floor
""", (RUN_ID,)).fetchall()
print(f"  {'score':8s}  {'n':5s}  {'WR':6s}  {'avg_r':7s}  {'net_r':8s}  bar")
for r in rows:
    resolved = r['wins'] + r['losses']
    wr = r['wins'] / resolved if resolved > 0 else 0
    be = 0.40  # breakeven at 1.5 R:R
    bar = '#' * int(r['n'] / 5)
    flag = ' ← BE' if abs(wr - be) < 0.02 else (' ✓' if wr > be else ' ✗')
    print(f"  {r['bucket_floor']:3d}-{r['bucket_floor']+4}    {r['n']:5d}  {wr:.1%}  {r['avg_r'] or 0:+.3f}R  {r['net_r'] or 0:+.2f}R  {bar}{flag}")

# ── 2. threshold sweep ────────────────────────────────────────────────────────
print('\n=== THRESHOLD SWEEP — signals passing each cutoff ===')
print(f"  {'thresh':6s}  {'n':5s}  {'WR':6s}  {'avg_r':7s}  {'net_r':9s}  {'excluded':8s}")
total_n = conn.execute("SELECT COUNT(*) FROM signals WHERE backtest_run_id=? AND quality_score IS NOT NULL AND outcome IS NOT NULL", (RUN_ID,)).fetchone()[0]
for thresh in [0, 30, 35, 38, 40, 42, 45, 48, 50, 55, 60]:
    r = conn.execute("""
        SELECT COUNT(*) as n,
               SUM(CASE WHEN outcome IN ('win','tp_hit') THEN 1 ELSE 0 END) as wins,
               SUM(CASE WHEN outcome IN ('loss','sl_hit','stopped_out') THEN 1 ELSE 0 END) as losses,
               ROUND(AVG(pnl_r), 3) as avg_r,
               ROUND(SUM(pnl_r), 2) as net_r
        FROM signals
        WHERE backtest_run_id=? AND quality_score >= ? AND outcome IS NOT NULL
    """, (RUN_ID, thresh)).fetchone()
    resolved = r['wins'] + r['losses']
    wr = r['wins'] / resolved if resolved > 0 else 0
    excluded = total_n - r['n']
    marker = ' ◄ current' if thresh == 45 else ''
    print(f"  >={thresh:3d}     {r['n']:5d}  {wr:.1%}  {r['avg_r'] or 0:+.3f}R  {r['net_r'] or 0:+9.2f}R  -{excluded:4d}{marker}")

# ── 3. choppy regime breakdown by score bucket ────────────────────────────────
print('\n=== CHOPPY: STRATEGY × DIRECTION × SCORE BUCKET ===')
rows = conn.execute("""
    SELECT strategy, direction,
        CASE
            WHEN quality_score < 35 THEN 'a<35'
            WHEN quality_score < 40 THEN 'b35-40'
            WHEN quality_score < 45 THEN 'c40-45'
            WHEN quality_score < 50 THEN 'd45-50'
            ELSE 'e50+'
        END as bucket,
        COUNT(*) as n,
        SUM(CASE WHEN outcome IN ('win','tp_hit') THEN 1 ELSE 0 END) as wins,
        SUM(CASE WHEN outcome IN ('loss','sl_hit','stopped_out') THEN 1 ELSE 0 END) as losses,
        ROUND(AVG(pnl_r), 3) as avg_r
    FROM signals
    WHERE backtest_run_id=? AND regime='choppy'
      AND quality_score IS NOT NULL AND outcome IS NOT NULL
    GROUP BY strategy, direction, bucket
    ORDER BY strategy, direction, bucket
""", (RUN_ID,)).fetchall()
prev = ''
for r in rows:
    key = f"{r['strategy']} {r['direction']}"
    resolved = r['wins'] + r['losses']
    wr = r['wins'] / resolved if resolved > 0 else 0
    if key != prev:
        print(f"\n  {key}")
        prev = key
    flag = '✓' if wr >= 0.40 else '✗'
    print(f"    {r['bucket'][1:]:6s}  n={r['n']:4d}  WR={wr:.1%}  avg_r={r['avg_r'] or 0:+.3f}R  {flag}")

# ── 4. regime breakdown at key thresholds ────────────────────────────────────
print('\n=== PER-REGIME WR AT THRESHOLD 40 vs 45 ===')
for thresh in [40, 45]:
    print(f"\n  score >= {thresh}:")
    rows = conn.execute("""
        SELECT regime,
            COUNT(*) as n,
            SUM(CASE WHEN outcome IN ('win','tp_hit') THEN 1 ELSE 0 END) as wins,
            SUM(CASE WHEN outcome IN ('loss','sl_hit','stopped_out') THEN 1 ELSE 0 END) as losses,
            ROUND(SUM(pnl_r), 2) as net_r
        FROM signals
        WHERE backtest_run_id=? AND quality_score >= ? AND outcome IS NOT NULL
        GROUP BY regime ORDER BY regime
    """, (RUN_ID, thresh)).fetchall()
    for r in rows:
        resolved = r['wins'] + r['losses']
        wr = r['wins'] / resolved if resolved > 0 else 0
        print(f"    {r['regime']:18s}  n={r['n']:4d}  WR={wr:.1%}  net_r={r['net_r']:+.2f}R")

# ── 5. score stats summary ────────────────────────────────────────────────────
print('\n=== SCORE STATISTICS ===')
r = conn.execute("""
    SELECT MIN(quality_score) as mn, MAX(quality_score) as mx,
           AVG(quality_score) as avg,
           SUM(CASE WHEN quality_score < 40 THEN 1 ELSE 0 END) as below_40,
           SUM(CASE WHEN quality_score < 45 THEN 1 ELSE 0 END) as below_45,
           COUNT(*) as total
    FROM signals WHERE backtest_run_id=? AND quality_score IS NOT NULL
""", (RUN_ID,)).fetchone()
print(f"  min={r['mn']:.1f}  max={r['mx']:.1f}  avg={r['avg']:.1f}")
print(f"  below 40: {r['below_40']} ({r['below_40']/r['total']:.0%} of scored)")
print(f"  below 45: {r['below_45']} ({r['below_45']/r['total']:.0%} of scored)")

conn.close()
print('\nDone.')
