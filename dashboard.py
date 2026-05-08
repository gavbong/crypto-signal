import json
import os
import sqlite3
from datetime import datetime, timezone
from pathlib import Path

from flask import Flask, abort, jsonify, request, send_from_directory

from db.schema import get_conn, init_db
from utils.config import get as cfg

_STATIC = Path(__file__).parent / "static"


def _normalize_ts(ts: str | None) -> str | None:
    if ts is None:
        return None
    try:
        dt = datetime.fromisoformat(ts)
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        return dt.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S") + "Z"
    except Exception:
        return ts


def _shadow_param(filter_arg: str) -> int | None:
    return {"live": 0, "shadow": 1, "all": None}.get(filter_arg, 0)


def create_app() -> Flask:
    dash_cfg = cfg().get("dashboard", {})
    host = dash_cfg.get("host", "127.0.0.1")

    token = os.environ.get("DASHBOARD_TOKEN")
    require_token = bool(token) and host != "127.0.0.1"

    app = Flask(__name__, static_folder=str(_STATIC), static_url_path="/static")

    def _auth():
        if not require_token:
            return
        if request.headers.get("Authorization") != f"Bearer {token}":
            abort(401)

    @app.route("/")
    def index():
        return send_from_directory(str(_STATIC), "dashboard.html")

    @app.route("/favicon.ico")
    def favicon():
        from flask import Response
        return Response(status=204)

    @app.route("/api/signals")
    def api_signals():
        _auth()
        shadow = _shadow_param(request.args.get("filter", "live"))
        exchange_filter = request.args.get("exchange")
        with get_conn() as conn:
            where_parts, params = [], []
            if shadow is not None:
                where_parts.append("shadow_mode=?")
                params.append(shadow)
            if exchange_filter:
                where_parts.append("exchange=?")
                params.append(exchange_filter)
            where = ("WHERE " + " AND ".join(where_parts)) if where_parts else ""
            rows = conn.execute(
                f"""SELECT id, pair, direction, strategy, regime, entry_price,
                          suggested_stop_loss, suggested_take_profit,
                          fired_at, outcome, outcome_price, pnl_r,
                          llm_commentary, shadow_mode, exchange
                   FROM signals {where} ORDER BY fired_at DESC LIMIT 100""",
                params,
            ).fetchall()
            total = conn.execute(
                f"SELECT COUNT(*) FROM signals {where}", params
            ).fetchone()[0]

        return jsonify({
            "signals": [
                {
                    "id": r["id"],
                    "pair": r["pair"],
                    "direction": r["direction"],
                    "strategy": r["strategy"],
                    "regime": r["regime"],
                    "entry_price": r["entry_price"],
                    "suggested_stop_loss": r["suggested_stop_loss"],
                    "suggested_take_profit": r["suggested_take_profit"],
                    "fired_at": _normalize_ts(r["fired_at"]),
                    "outcome": r["outcome"],
                    "outcome_price": r["outcome_price"],
                    "pnl_r": r["pnl_r"],
                    "llm_commentary": r["llm_commentary"],
                    "shadow_mode": bool(r["shadow_mode"]),
                    "exchange": r["exchange"] or "mexc",
                }
                for r in rows
            ],
            "total": total,
        })

    @app.route("/api/stats")
    def api_stats():
        _auth()
        shadow = _shadow_param(request.args.get("filter", "live"))
        since = request.args.get("since")

        where_parts, params = [], []
        if shadow is not None:
            where_parts.append("shadow_mode=?")
            params.append(shadow)
        if since:
            where_parts.append("DATE(fired_at)>=?")
            params.append(since)
        where = ("WHERE " + " AND ".join(where_parts)) if where_parts else ""

        with get_conn() as conn:
            agg = conn.execute(
                f"""SELECT
                        COUNT(*) as total_fired,
                        SUM(CASE WHEN outcome IS NOT NULL THEN 1 ELSE 0 END) as resolved,
                        SUM(CASE WHEN outcome IN ('win','tp_hit') THEN 1 ELSE 0 END) as wins,
                        SUM(CASE WHEN outcome='loss' THEN 1 ELSE 0 END) as losses,
                        SUM(CASE WHEN outcome='stopped_out' THEN 1 ELSE 0 END) as stopped,
                        SUM(CASE WHEN outcome='tp_hit' THEN 1 ELSE 0 END) as tp_hits,
                        SUM(COALESCE(pnl_r,0)) as net_r,
                        MIN(DATE(fired_at)) as period_start,
                        MAX(DATE(fired_at)) as period_end
                    FROM signals {where}""",
                params,
            ).fetchone()

            by_regime_rows = conn.execute(
                f"""SELECT regime,
                        COUNT(*) as fired,
                        SUM(CASE WHEN outcome IN ('win','tp_hit') THEN 1 ELSE 0 END) as wins,
                        SUM(CASE WHEN outcome='loss' THEN 1 ELSE 0 END) as losses,
                        SUM(CASE WHEN outcome='stopped_out' THEN 1 ELSE 0 END) as stopped,
                        SUM(CASE WHEN outcome='tp_hit' THEN 1 ELSE 0 END) as tp_hits,
                        SUM(COALESCE(pnl_r,0)) as net_r,
                        SUM(CASE WHEN outcome IS NOT NULL THEN 1 ELSE 0 END) as resolved
                    FROM signals {where} GROUP BY regime""",
                params,
            ).fetchall()

        resolved = agg["resolved"] or 0
        wins = agg["wins"] or 0
        net_r = agg["net_r"] or 0.0
        rr = cfg().get("signals", {}).get("rr_ratio", 2.0)

        by_regime = {}
        for r in by_regime_rows:
            res = r["resolved"] or 0
            w = r["wins"] or 0
            by_regime[r["regime"]] = {
                "fired": r["fired"],
                "wins": w,
                "losses": r["losses"] or 0,
                "stopped": r["stopped"] or 0,
                "tp_hits": r["tp_hits"] or 0,
                "net_r": round(r["net_r"] or 0.0, 3),
                "resolved": res,
                "accuracy": round(w / res, 3) if res > 0 else 0.0,
            }

        return jsonify({
            "accuracy": round(wins / resolved, 3) if resolved > 0 else 0.0,
            "net_r": round(net_r, 3),
            "avg_r": round(net_r / resolved, 3) if resolved > 0 else 0.0,
            "rr_ratio": rr,
            "total_fired": agg["total_fired"] or 0,
            "resolved": resolved,
            "wins": wins,
            "losses": agg["losses"] or 0,
            "stopped": agg["stopped"] or 0,
            "tp_hits": agg["tp_hits"] or 0,
            "by_regime": by_regime,
            "period_start": agg["period_start"],
            "period_end": agg["period_end"],
        })

    @app.route("/api/active")
    def api_active():
        _auth()
        with get_conn() as conn:
            rows = conn.execute(
                """SELECT pair, direction, entry_price,
                          suggested_stop_loss, suggested_take_profit,
                          fired_at, llm_commentary, regime
                   FROM signals
                   WHERE outcome IS NULL AND shadow_mode=0
                   ORDER BY fired_at DESC LIMIT 5"""
            ).fetchall()

        return jsonify({
            "signals": [
                {
                    "pair": r["pair"],
                    "direction": r["direction"],
                    "entry_price": r["entry_price"],
                    "suggested_stop_loss": r["suggested_stop_loss"],
                    "suggested_take_profit": r["suggested_take_profit"],
                    "fired_at": _normalize_ts(r["fired_at"]),
                    "llm_commentary": r["llm_commentary"],
                    "regime": r["regime"],
                }
                for r in rows
            ]
        })

    # ── Paper Trading API ─────────────────────────────────────────────────────
    _PAPER_INITIAL = 1_000.0

    @app.route("/api/paper/stats")
    def api_paper_stats():
        _auth()
        with get_conn() as conn:
            realized = conn.execute(
                "SELECT COALESCE(SUM(pnl_usdt),0) FROM paper_positions WHERE exit_price IS NOT NULL"
            ).fetchone()[0]
            open_margin = conn.execute(
                "SELECT COALESCE(SUM(margin_usdt),0) FROM paper_positions WHERE exit_price IS NULL"
            ).fetchone()[0]
            wins = conn.execute(
                "SELECT COUNT(*) FROM paper_positions WHERE exit_price IS NOT NULL AND pnl_usdt > 0"
            ).fetchone()[0]
            losses = conn.execute(
                "SELECT COUNT(*) FROM paper_positions WHERE exit_price IS NOT NULL AND pnl_usdt <= 0"
            ).fetchone()[0]
            open_count = conn.execute(
                "SELECT COUNT(*) FROM paper_positions WHERE exit_price IS NULL"
            ).fetchone()[0]
            open_positions = conn.execute(
                "SELECT direction, entry_price, contracts, last_price FROM paper_positions WHERE exit_price IS NULL"
            ).fetchall()

        unrealized = 0.0
        for p in open_positions:
            if p["last_price"] is not None:
                if p["direction"] == "long":
                    unrealized += (p["last_price"] - p["entry_price"]) * p["contracts"]
                else:
                    unrealized += (p["entry_price"] - p["last_price"]) * p["contracts"]

        total_closed = wins + losses
        balance = _PAPER_INITIAL + realized - open_margin
        equity = balance + unrealized
        return jsonify({
            "balance_usdt": round(balance, 2),
            "equity_usdt": round(equity, 2),
            "initial_balance": _PAPER_INITIAL,
            "realized_pnl": round(realized, 2),
            "unrealized_pnl": round(unrealized, 2),
            "open_margin": round(open_margin, 2),
            "wins": wins,
            "losses": losses,
            "total_closed": total_closed,
            "open_count": open_count,
            "win_rate": round(wins / total_closed, 4) if total_closed > 0 else 0.0,
        })

    @app.route("/api/paper/positions")
    def api_paper_positions():
        _auth()
        with get_conn() as conn:
            rows = conn.execute(
                """SELECT id, pair, direction, strategy, regime,
                          entry_price, contracts, margin_usdt, stop_loss, take_profit,
                          opened_at, last_price, exchange
                   FROM paper_positions WHERE exit_price IS NULL ORDER BY opened_at DESC"""
            ).fetchall()

        def _unrealized(r):
            if r["last_price"] is None:
                return None
            if r["direction"] == "long":
                return round((r["last_price"] - r["entry_price"]) * r["contracts"], 4)
            return round((r["entry_price"] - r["last_price"]) * r["contracts"], 4)

        return jsonify({
            "positions": [
                {
                    "id": r["id"], "pair": r["pair"], "direction": r["direction"],
                    "strategy": r["strategy"], "regime": r["regime"],
                    "entry_price": r["entry_price"], "contracts": r["contracts"],
                    "margin_usdt": r["margin_usdt"], "stop_loss": r["stop_loss"],
                    "take_profit": r["take_profit"],
                    "opened_at": _normalize_ts(r["opened_at"]),
                    "last_price": r["last_price"],
                    "unrealized_pnl": _unrealized(r),
                    "notional_usdt": round(r["contracts"] * r["last_price"], 2) if r["last_price"] else None,
                    "exchange": r["exchange"] or "mexc",
                }
                for r in rows
            ]
        })

    @app.route("/api/paper/history")
    def api_paper_history():
        _auth()
        with get_conn() as conn:
            rows = conn.execute(
                """SELECT id, pair, direction, strategy, regime, entry_price,
                          contracts, margin_usdt, exit_price, exit_reason, pnl_usdt,
                          opened_at, closed_at, exchange
                   FROM paper_positions WHERE exit_price IS NOT NULL
                   ORDER BY closed_at DESC"""
            ).fetchall()
        return jsonify({
            "trades": [
                {
                    "id": r["id"], "pair": r["pair"], "direction": r["direction"],
                    "strategy": r["strategy"], "regime": r["regime"],
                    "entry_price": r["entry_price"], "contracts": r["contracts"],
                    "margin_usdt": r["margin_usdt"], "exit_price": r["exit_price"],
                    "exit_reason": r["exit_reason"], "pnl_usdt": r["pnl_usdt"],
                    "opened_at": _normalize_ts(r["opened_at"]),
                    "closed_at": _normalize_ts(r["closed_at"]),
                    "exchange": r["exchange"] or "mexc",
                }
                for r in rows
            ]
        })

    @app.route("/api/paper/daily")
    def api_paper_daily():
        _auth()
        with get_conn() as conn:
            rows = conn.execute(
                """SELECT day_number, snapshot_date, balance_usdt, equity_usdt,
                          realized_pnl, unrealized_pnl, open_positions,
                          total_trades, wins, losses, win_rate
                   FROM paper_daily_pnl ORDER BY day_number DESC LIMIT 30"""
            ).fetchall()
        return jsonify({
            "snapshots": [
                {
                    "day_number": r["day_number"], "snapshot_date": r["snapshot_date"],
                    "balance_usdt": r["balance_usdt"], "equity_usdt": r["equity_usdt"],
                    "realized_pnl": r["realized_pnl"], "unrealized_pnl": r["unrealized_pnl"],
                    "open_positions": r["open_positions"], "total_trades": r["total_trades"],
                    "wins": r["wins"], "losses": r["losses"], "win_rate": r["win_rate"],
                }
                for r in rows
            ]
        })

    @app.route("/api/config/pairs")
    def api_config_pairs():
        _auth()
        exchanges = cfg().get("exchanges", {})
        seen, result = set(), []
        for exc_id, exc_cfg in exchanges.items():
            if not exc_cfg.get("enabled", False):
                continue
            for p in exc_cfg.get("pairs", []):
                base = p.split(":")[0]
                if base not in seen:
                    seen.add(base)
                    result.append({"pair": base, "exchange": exc_id})
        return jsonify({"pairs": result})

    @app.route("/api/health")
    def api_health():
        _auth()
        with get_conn() as conn:
            row = conn.execute(
                "SELECT MAX(logged_at) as last_write FROM regime_log"
            ).fetchone()

        last_write = _normalize_ts(row["last_write"]) if row else None
        engine_running = False
        if last_write:
            try:
                dt = datetime.fromisoformat(last_write.replace("Z", "+00:00"))
                engine_running = (datetime.now(timezone.utc) - dt).total_seconds() < 600
            except Exception:
                pass

        return jsonify({
            "engine_running": engine_running,
            "last_write": last_write,
            "threshold_minutes": 10,
        })

    @app.route("/api/regime")
    def api_regime():
        _auth()
        shadow = _shadow_param(request.args.get("filter", "live"))
        with get_conn() as conn:
            if shadow is None:
                rows = conn.execute(
                    """SELECT regime, MIN(DATE(fired_at)) as start,
                              MAX(DATE(fired_at)) as end, COUNT(*) as signal_count
                       FROM signals GROUP BY regime ORDER BY start ASC"""
                ).fetchall()
                period = conn.execute(
                    "SELECT MIN(DATE(fired_at)) as s, MAX(DATE(fired_at)) as e FROM signals"
                ).fetchone()
            else:
                rows = conn.execute(
                    """SELECT regime, MIN(DATE(fired_at)) as start,
                              MAX(DATE(fired_at)) as end, COUNT(*) as signal_count
                       FROM signals WHERE shadow_mode=? GROUP BY regime ORDER BY start ASC""",
                    (shadow,),
                ).fetchall()
                period = conn.execute(
                    "SELECT MIN(DATE(fired_at)) as s, MAX(DATE(fired_at)) as e FROM signals WHERE shadow_mode=?",
                    (shadow,),
                ).fetchone()

        return jsonify({
            "segments": [
                {"regime": r["regime"], "start": r["start"],
                 "end": r["end"], "signal_count": r["signal_count"]}
                for r in rows
            ],
            "period_start": period["s"] if period else None,
            "period_end": period["e"] if period else None,
        })

    @app.route("/api/analysis/latest")
    def api_analysis_latest():
        _auth()
        analysis_dir = Path(__file__).parent / "analysis"
        if not analysis_dir.exists():
            return jsonify({"date": None, "rows": []})
        files = sorted(analysis_dir.glob("review-*.json"), reverse=True)
        if not files:
            return jsonify({"date": None, "rows": []})
        data = json.loads(files[0].read_text())
        return jsonify(data)

    # ── Copy Trader API ───────────────────────────────────────────────────────

    @app.route("/api/copy/account")
    def api_copy_account():
        _auth()
        ct_cfg = cfg().get("copy_trader", {})
        initial = float(ct_cfg.get("initial_balance", 10_000))
        with get_conn() as conn:
            acc = conn.execute("SELECT balance FROM copy_account WHERE id=1").fetchone()
            realized = conn.execute(
                "SELECT COALESCE(SUM(pnl_usdt),0) FROM copy_positions WHERE closed_at IS NOT NULL"
            ).fetchone()[0]
            open_count = conn.execute(
                "SELECT COUNT(*) FROM copy_positions WHERE closed_at IS NULL"
            ).fetchone()[0]
            wins = conn.execute(
                "SELECT COUNT(*) FROM copy_positions WHERE closed_at IS NOT NULL AND pnl_usdt > 0"
            ).fetchone()[0]
            losses = conn.execute(
                "SELECT COUNT(*) FROM copy_positions WHERE closed_at IS NOT NULL AND pnl_usdt <= 0"
            ).fetchone()[0]
            open_pos = conn.execute(
                "SELECT direction, entry_price, contracts, last_price FROM copy_positions WHERE closed_at IS NULL"
            ).fetchall()

        balance = acc["balance"] if acc else initial
        unrealized = 0.0
        for p in open_pos:
            if p["last_price"]:
                sign = 1 if p["direction"] == "long" else -1
                unrealized += (p["last_price"] - p["entry_price"]) * (p["contracts"] or 0.0) * sign

        total_closed = wins + losses
        return jsonify({
            "balance": round(balance, 2),
            "initial_balance": initial,
            "realized_pnl": round(realized, 2),
            "unrealized_pnl": round(unrealized, 2),
            "equity": round(balance + unrealized, 2),
            "total_return_pct": round((balance + unrealized - initial) / initial * 100, 2) if initial > 0 else 0.0,
            "wins": wins,
            "losses": losses,
            "open_count": open_count,
            "win_rate": round(wins / total_closed, 4) if total_closed > 0 else 0.0,
        })

    @app.route("/api/copy/traders")
    def api_copy_traders():
        _auth()
        with get_conn() as conn:
            rows = conn.execute(
                """SELECT t.wallet, t.alias, t.pnl_30d, t.tracked_since, t.last_refreshed, t.active,
                          COUNT(p.id) as trade_count,
                          COALESCE(SUM(CASE WHEN p.pnl_usdt > 0 THEN 1 ELSE 0 END), 0) as wins,
                          COALESCE(SUM(CASE WHEN p.pnl_usdt <= 0 AND p.closed_at IS NOT NULL THEN 1 ELSE 0 END), 0) as losses,
                          COALESCE(SUM(p.pnl_usdt), 0) as total_copy_pnl
                   FROM copy_traders t
                   LEFT JOIN copy_positions p ON p.trader_wallet=t.wallet AND p.closed_at IS NOT NULL
                   GROUP BY t.wallet
                   ORDER BY t.pnl_30d DESC"""
            ).fetchall()
        return jsonify({
            "traders": [
                {
                    "wallet": r["wallet"],
                    "alias": r["alias"],
                    "pnl_30d": r["pnl_30d"],
                    "tracked_since": _normalize_ts(r["tracked_since"]),
                    "last_refreshed": _normalize_ts(r["last_refreshed"]),
                    "active": bool(r["active"]),
                    "trade_count": r["trade_count"] or 0,
                    "wins": r["wins"] or 0,
                    "losses": r["losses"] or 0,
                    "total_copy_pnl": round(r["total_copy_pnl"] or 0.0, 2),
                    "win_rate": round((r["wins"] or 0) / max(r["trade_count"] or 0, 1), 4),
                }
                for r in rows
            ]
        })

    @app.route("/api/copy/positions")
    def api_copy_positions():
        _auth()
        with get_conn() as conn:
            rows = conn.execute(
                """SELECT id, trader_wallet, pair, direction, entry_price, last_price,
                          contracts, margin_usdt, opened_at
                   FROM copy_positions WHERE closed_at IS NULL ORDER BY opened_at DESC"""
            ).fetchall()

        def _unrealized(r):
            if r["last_price"] is None:
                return None
            sign = 1 if r["direction"] == "long" else -1
            return round((r["last_price"] - r["entry_price"]) * (r["contracts"] or 0.0) * sign, 4)

        return jsonify({
            "positions": [
                {
                    "id": r["id"],
                    "trader_wallet": r["trader_wallet"],
                    "pair": r["pair"],
                    "direction": r["direction"],
                    "entry_price": r["entry_price"],
                    "last_price": r["last_price"],
                    "contracts": r["contracts"],
                    "margin_usdt": r["margin_usdt"],
                    "unrealized_pnl": _unrealized(r),
                    "opened_at": _normalize_ts(r["opened_at"]),
                }
                for r in rows
            ]
        })

    @app.route("/api/copy/history")
    def api_copy_history():
        _auth()
        with get_conn() as conn:
            rows = conn.execute(
                """SELECT id, trader_wallet, pair, direction, entry_price, exit_price,
                          contracts, margin_usdt, pnl_usdt, opened_at, closed_at, exit_reason
                   FROM copy_positions WHERE closed_at IS NOT NULL
                   ORDER BY closed_at DESC LIMIT 200"""
            ).fetchall()
        return jsonify({
            "trades": [
                {
                    "id": r["id"],
                    "trader_wallet": r["trader_wallet"],
                    "pair": r["pair"],
                    "direction": r["direction"],
                    "entry_price": r["entry_price"],
                    "exit_price": r["exit_price"],
                    "contracts": r["contracts"],
                    "margin_usdt": r["margin_usdt"],
                    "pnl_usdt": r["pnl_usdt"],
                    "opened_at": _normalize_ts(r["opened_at"]),
                    "closed_at": _normalize_ts(r["closed_at"]),
                    "exit_reason": r["exit_reason"],
                }
                for r in rows
            ]
        })

    @app.route("/api/copy/comparison")
    def api_copy_comparison():
        """Cumulative daily PnL for both copy trader and paper trader — feeds comparison chart."""
        _auth()
        with get_conn() as conn:
            copy_rows = conn.execute(
                "SELECT date, pnl_usdt FROM copy_daily_pnl ORDER BY date"
            ).fetchall()
            paper_rows = conn.execute(
                """SELECT DATE(closed_at) as date, SUM(pnl_usdt) as pnl_usdt
                   FROM paper_positions WHERE closed_at IS NOT NULL
                   GROUP BY DATE(closed_at) ORDER BY date"""
            ).fetchall()

        def _cumulative(rows):
            total, result = 0.0, []
            for r in rows:
                total += r["pnl_usdt"] or 0.0
                result.append({"date": r["date"], "cumulative_pnl": round(total, 2)})
            return result

        return jsonify({
            "copy": _cumulative(copy_rows),
            "paper": _cumulative(paper_rows),
        })

    # ── Polymarket API ────────────────────────────────────────────────────────

    @app.route("/api/poly/account")
    def api_poly_account():
        _auth()
        with get_conn() as conn:
            acc = conn.execute("SELECT * FROM poly_account WHERE id=1").fetchone()
            open_count = conn.execute(
                "SELECT COUNT(*) FROM poly_positions WHERE closed_at IS NULL"
            ).fetchone()[0]
            cat_rows = conn.execute(
                """SELECT category,
                          SUM(CASE WHEN exit_reason='resolved_win' THEN 1 ELSE 0 END) as wins,
                          SUM(CASE WHEN exit_reason='resolved_loss' THEN 1 ELSE 0 END) as losses
                   FROM poly_positions
                   WHERE exit_reason IN ('resolved_win','resolved_loss')
                   GROUP BY category"""
            ).fetchall()
            unrealized = conn.execute(
                """SELECT COALESCE(SUM(shares*(current_price-entry_price)),0)
                   FROM poly_positions
                   WHERE closed_at IS NULL AND current_price IS NOT NULL AND entry_price >= 0.01"""
            ).fetchone()[0]

        if not acc:
            return jsonify({"balance": 10000, "initial_balance": 10000, "realized_pnl": 0,
                            "unrealized_pnl": 0, "wins": 0, "losses": 0, "win_rate": 0,
                            "open_count": 0, "by_category": {}})

        total_closed = (acc["wins"] or 0) + (acc["losses"] or 0)
        by_cat = {}
        for r in cat_rows:
            w, l = r["wins"] or 0, r["losses"] or 0
            by_cat[r["category"]] = {
                "wins": w, "losses": l,
                "win_rate": round(w / (w + l), 4) if (w + l) > 0 else 0.0,
            }
        return jsonify({
            "balance": round(acc["balance"], 2),
            "initial_balance": round(acc["initial_balance"], 2),
            "realized_pnl": round(acc["realized_pnl"] or 0, 2),
            "unrealized_pnl": round(unrealized or 0, 2),
            "wins": acc["wins"] or 0,
            "losses": acc["losses"] or 0,
            "open_count": open_count,
            "win_rate": round((acc["wins"] or 0) / total_closed, 4) if total_closed > 0 else 0.0,
            "by_category": by_cat,
        })

    @app.route("/api/poly/traders")
    def api_poly_traders():
        _auth()
        with get_conn() as conn:
            rows = conn.execute(
                """SELECT t.wallet, t.alias, t.pnl_30d, t.volume_30d, t.tracked_since, t.active,
                          COUNT(p.id) as trade_count,
                          COALESCE(SUM(CASE WHEN p.exit_reason='resolved_win' THEN 1 ELSE 0 END),0) as wins,
                          COALESCE(SUM(CASE WHEN p.exit_reason='resolved_loss' THEN 1 ELSE 0 END),0) as losses,
                          COALESCE(SUM(p.pnl_usdt),0) as copy_pnl
                   FROM poly_traders t
                   LEFT JOIN poly_positions p ON p.trader_wallet=t.wallet AND p.closed_at IS NOT NULL
                   GROUP BY t.wallet
                   ORDER BY t.pnl_30d DESC"""
            ).fetchall()
        return jsonify({
            "traders": [
                {
                    "wallet": r["wallet"],
                    "alias": r["alias"],
                    "pnl_30d": r["pnl_30d"],
                    "volume_30d": r["volume_30d"],
                    "tracked_since": _normalize_ts(r["tracked_since"]),
                    "active": bool(r["active"]),
                    "trade_count": r["trade_count"] or 0,
                    "wins": r["wins"] or 0,
                    "losses": r["losses"] or 0,
                    "copy_pnl": round(r["copy_pnl"] or 0, 2),
                    "win_rate": round((r["wins"] or 0) / max(r["trade_count"] or 1, 1), 4),
                }
                for r in rows
            ]
        })

    @app.route("/api/poly/positions")
    def api_poly_positions():
        _auth()
        with get_conn() as conn:
            rows = conn.execute(
                """SELECT id, trader_wallet, market_id, market_title, category,
                          outcome, shares, entry_price, current_price, cost_basis,
                          pnl_usdt, exit_price, exit_reason, opened_at, closed_at
                   FROM poly_positions ORDER BY opened_at DESC LIMIT 200"""
            ).fetchall()

        def _unrealized(r):
            if r["closed_at"] or r["current_price"] is None:
                return r["pnl_usdt"]
            if r["entry_price"] is None or r["entry_price"] < 0.01:
                return None
            return round(r["shares"] * (r["current_price"] - r["entry_price"]), 4)

        return jsonify({
            "positions": [
                {
                    "id": r["id"],
                    "trader_wallet": r["trader_wallet"],
                    "market_id": r["market_id"],
                    "market_title": r["market_title"],
                    "category": r["category"],
                    "outcome": r["outcome"],
                    "shares": r["shares"],
                    "entry_price": r["entry_price"],
                    "current_price": r["current_price"],
                    "cost_basis": r["cost_basis"],
                    "pnl_usdt": _unrealized(r),
                    "exit_price": r["exit_price"],
                    "exit_reason": r["exit_reason"],
                    "opened_at": _normalize_ts(r["opened_at"]),
                    "closed_at": _normalize_ts(r["closed_at"]),
                    "open": r["closed_at"] is None,
                }
                for r in rows
            ]
        })

    @app.route("/api/poly/consensus")
    def api_poly_consensus():
        """Markets where >= 2 tracked traders hold the same outcome."""
        _auth()
        with get_conn() as conn:
            rows = conn.execute(
                """SELECT market_id, market_title, outcome,
                          COUNT(DISTINCT trader_wallet) as trader_count,
                          AVG(entry_price) as avg_entry,
                          SUM(cost_basis) as total_exposure
                   FROM poly_positions
                   WHERE closed_at IS NULL
                   GROUP BY market_id, outcome
                   HAVING COUNT(DISTINCT trader_wallet) >= 2
                   ORDER BY trader_count DESC, total_exposure DESC"""
            ).fetchall()
        return jsonify({
            "consensus": [
                {
                    "market_id": r["market_id"],
                    "market_title": r["market_title"],
                    "outcome": r["outcome"],
                    "trader_count": r["trader_count"],
                    "avg_entry": round(r["avg_entry"] or 0, 3),
                    "total_exposure": round(r["total_exposure"] or 0, 2),
                }
                for r in rows
            ]
        })

    @app.route("/api/poly/convergence")
    def api_poly_convergence():
        """Open Polymarket positions that overlap with a recent engine signal (same ticker, same direction)."""
        _auth()
        import re
        ticker_re = re.compile(r'\b(BTC|ETH|SOL|XRP|BNB|DOGE|ADA|AVAX|MATIC|DOT|LINK)\b', re.I)
        with get_conn() as conn:
            positions = conn.execute(
                """SELECT id, trader_wallet, market_title, outcome, entry_price,
                          current_price, cost_basis, opened_at
                   FROM poly_positions WHERE closed_at IS NULL"""
            ).fetchall()
            convergent = []
            for pos in positions:
                m = ticker_re.search(pos["market_title"] or "")
                if not m:
                    continue
                ticker    = m.group(1).upper()
                direction = "long" if pos["outcome"] == "YES" else "short"
                sig = conn.execute(
                    """SELECT pair, direction, strategy, entry_price, fired_at
                       FROM signals
                       WHERE pair LIKE ? AND direction = ?
                         AND fired_at > datetime('now', '-24 hours')
                       ORDER BY fired_at DESC LIMIT 1""",
                    (f"%{ticker}%", direction),
                ).fetchone()
                if sig:
                    convergent.append({
                        "poly_id": pos["id"],
                        "trader_wallet": pos["trader_wallet"],
                        "market_title": pos["market_title"],
                        "outcome": pos["outcome"],
                        "entry_price": pos["entry_price"],
                        "current_price": pos["current_price"],
                        "opened_at": _normalize_ts(pos["opened_at"]),
                        "signal_pair": sig["pair"],
                        "signal_direction": sig["direction"],
                        "signal_strategy": sig["strategy"],
                        "signal_fired_at": _normalize_ts(sig["fired_at"]),
                    })
        return jsonify({"convergence": convergent})

    _migrate_paper_db()
    _migrate_copy_db()
    _migrate_poly_db()
    return app


def _migrate_paper_db():
    with get_conn() as conn:
        for migration in [
            "ALTER TABLE paper_positions ADD COLUMN last_price REAL",
            "ALTER TABLE paper_positions ADD COLUMN exchange TEXT NOT NULL DEFAULT 'mexc'",
        ]:
            try:
                conn.execute(migration)
                conn.commit()
            except sqlite3.OperationalError:
                pass  # column already exists


def _migrate_copy_db():
    from copy_trader import init_copy_db
    with get_conn() as conn:
        init_copy_db(conn)


def _migrate_poly_db():
    from polymarket_trader import init_poly_db
    with get_conn() as conn:
        init_poly_db(conn)


if __name__ == "__main__":
    dash_cfg = cfg().get("dashboard", {})
    init_db()
    app = create_app()
    app.run(
        host=dash_cfg.get("host", "127.0.0.1"),
        port=dash_cfg.get("port", 5000),
        debug=dash_cfg.get("debug", False),
    )
