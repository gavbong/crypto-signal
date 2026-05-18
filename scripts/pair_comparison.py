import sys, sqlite3
sys.path.insert(0, '/opt/mexc-signal-engine')

DB = '/opt/mexc-signal-engine/signals.db'
conn = sqlite3.connect(DB)
conn.row_factory = sqlite3.Row

for run_id in [11, 12]:
    r = conn.execute('SELECT id, since_date, signal_count, win_rate, net_r, status FROM backtest_runs WHERE id=?', (run_id,)).fetchone()
    if r is None:
        print(f'Run #{run_id}: not found')
        continue
    print(f'Run #{run_id}: since={r["since_date"]}  signals={r["signal_count"]}  WR={r["win_rate"]:.1%}  net_r={r["net_r"]:+.2f}R  [{r["status"]}]')

for run_id in [11, 12]:
    rows = conn.execute('SELECT id FROM backtest_runs WHERE id=?', (run_id,)).fetchone()
    if rows is None:
        continue
    print(f'\n--- Run #{run_id} per-pair breakdown ---')
    rows = conn.execute("""
        SELECT pair,
            COUNT(*) as n,
            SUM(CASE WHEN outcome IN ('win','tp_hit') THEN 1 ELSE 0 END) as wins,
            SUM(CASE WHEN outcome IN ('loss','sl_hit','stopped_out') THEN 1 ELSE 0 END) as losses,
            ROUND(AVG(pnl_r),3) as avg_r,
            ROUND(SUM(pnl_r),2) as net_r
        FROM signals WHERE backtest_run_id=? AND outcome IS NOT NULL
        GROUP BY pair ORDER BY net_r ASC
    """, (run_id,)).fetchall()
    print(f"  {'pair':25s}  {'n':4s}  {'WR':6s}  {'avg_r':8s}  {'net_r':8s}")
    total_net = 0
    for r in rows:
        wr = r['wins']/(r['wins']+r['losses']) if (r['wins']+r['losses']) > 0 else 0
        total_net += r['net_r'] or 0
        print(f"  {r['pair']:25s}  {r['n']:4d}  {wr:.1%}  {r['avg_r'] or 0:+.3f}R  {r['net_r'] or 0:+.2f}R")
    print(f"  {'TOTAL':25s}        {'':6s}  {'':8s}  {total_net:+.2f}R")

# UKOIL deep dive across both runs
print('\n--- UKOIL strategy breakdown (both runs combined) ---')
rows = conn.execute("""
    SELECT strategy, direction, regime,
        COUNT(*) as n,
        SUM(CASE WHEN outcome IN ('win','tp_hit') THEN 1 ELSE 0 END) as wins,
        SUM(CASE WHEN outcome IN ('loss','sl_hit','stopped_out') THEN 1 ELSE 0 END) as losses,
        ROUND(SUM(pnl_r),2) as net_r
    FROM signals
    WHERE backtest_run_id IN (11,12) AND pair='UKOIL/USDT:USDT' AND outcome IS NOT NULL
    GROUP BY strategy, direction, regime ORDER BY net_r ASC
""").fetchall()
for r in rows:
    wr = r['wins']/(r['wins']+r['losses']) if (r['wins']+r['losses']) > 0 else 0
    print(f"  {r['strategy']:22s} {r['direction']:5s} {r['regime']:16s}  n={r['n']:3d}  WR={wr:.1%}  net_r={r['net_r']:+.2f}R")

conn.close()
