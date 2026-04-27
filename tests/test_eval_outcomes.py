from datetime import datetime, timedelta, timezone
from unittest.mock import MagicMock
import pytest
from db.schema import init_db, get_conn, log_signal, get_pending_outcomes, update_outcome
from eval.outcomes import resolve_outcome


def _make_signal_row(direction="long", entry=50000.0, stop=49000.0,
                     fired_at: datetime | None = None):
    if fired_at is None:
        fired_at = datetime.now(timezone.utc) - timedelta(hours=5)
    return {
        "id": 1,
        "pair": "BTC/USDT:USDT",
        "direction": direction,
        "strategy": "ema_crossover",
        "regime": "trending-up",
        "regime_confidence": 0.8,
        "regime_age_candles": 5,
        "entry_price": entry,
        "suggested_stop_loss": stop,
        "timeframe": "1h",
        "fired_at": fired_at.isoformat(),
        "shadow_mode": 1,
        "llm_commentary": None,
        "commentary_status": "pending",
        "outcome": None,
        "outcome_price": None,
        "outcome_resolved_at": None,
    }


def _mock_exchange(candles):
    ex = MagicMock()
    ex.fetch_ohlcv.return_value = candles
    return ex


def _candle(ts_offset_h: int, low: float, high: float, close: float,
            base_ts: datetime | None = None):
    base = base_ts or datetime(2025, 1, 1, tzinfo=timezone.utc)
    ts = base + timedelta(hours=ts_offset_h)
    return [int(ts.timestamp() * 1000), close * 0.999, high, low, close, 1000.0]


class TestResolveOutcome:
    def test_win_long(self):
        signal = _mock_signal_row("long", 50000.0, 49000.0)
        candles = [_candle(i, 50100 + i * 20, 50200 + i * 20, 50150 + i * 20)
                   for i in range(5)]
        ex = _mock_exchange(candles)
        result = resolve_outcome(signal, ex)
        assert result is not None
        outcome, price = result
        assert outcome == "win"

    def test_loss_long(self):
        signal = _mock_signal_row("long", 50000.0, 49000.0)
        candles = [_candle(i, 49500 - i * 20, 49600 - i * 20, 49550 - i * 20)
                   for i in range(5)]
        ex = _mock_exchange(candles)
        result = resolve_outcome(signal, ex)
        assert result is not None
        outcome, price = result
        assert outcome == "loss"

    def test_stopped_out_long(self):
        # Stop is 49000; a candle goes below that
        signal = _mock_signal_row("long", 50000.0, 49000.0)
        candles = [
            _candle(0, 50100.0, 50200.0, 50150.0),
            _candle(1, 48500.0, 50000.0, 49200.0),  # low < stop
        ]
        ex = _mock_exchange(candles)
        result = resolve_outcome(signal, ex)
        assert result is not None
        outcome, price = result
        assert outcome == "stopped_out"
        assert price == 49000.0

    def test_win_short(self):
        signal = _mock_signal_row("short", 50000.0, 51000.0)
        candles = [_candle(i, 49000 - i * 20, 49500 - i * 20, 49200 - i * 20)
                   for i in range(5)]
        ex = _mock_exchange(candles)
        result = resolve_outcome(signal, ex)
        assert result is not None
        outcome, _ = result
        assert outcome == "win"

    def test_loss_short(self):
        signal = _mock_signal_row("short", 50000.0, 51000.0)
        candles = [_candle(i, 49000 + i * 20, 50500 + i * 20, 50200 + i * 20)
                   for i in range(5)]
        ex = _mock_exchange(candles)
        result = resolve_outcome(signal, ex)
        assert result is not None
        outcome, _ = result
        assert outcome == "loss"

    def test_stopped_out_short(self):
        signal = _mock_signal_row("short", 50000.0, 51000.0)
        candles = [
            _candle(0, 49800.0, 51200.0, 50500.0),  # high > stop
        ]
        ex = _mock_exchange(candles)
        result = resolve_outcome(signal, ex)
        assert result is not None
        outcome, _ = result
        assert outcome == "stopped_out"

    def test_no_candle_data_returns_none(self):
        signal = _mock_signal_row()
        ex = _mock_exchange([])
        result = resolve_outcome(signal, ex)
        assert result is None


def _mock_signal_row(direction="long", entry=50000.0, stop=49000.0):
    """Return a dict-like object with subscript access."""
    d = _make_signal_row(direction, entry, stop)

    class RowLike(dict):
        def __getitem__(self, key):
            return super().__getitem__(key)

    return RowLike(d)


class TestAccuracyCalculation:
    def test_accuracy_from_db(self, tmp_db):
        from db.schema import get_accuracy_stats
        from datetime import timezone

        now = datetime.now(timezone.utc)
        with get_conn(tmp_db) as conn:
            for i in range(7):
                s = _make_signal_row(fired_at=now - timedelta(hours=10 + i))
                s["id"] = None
                log_signal(conn, {**s, "shadow_mode": True,
                                  "regime": "trending-up"})
            rows = get_pending_outcomes(conn, 4)
            assert len(rows) == 7
            # Mark 5 as wins, 2 as losses
            for row in rows[:5]:
                update_outcome(conn, row["id"], "win", 51000.0)
            for row in rows[5:]:
                update_outcome(conn, row["id"], "loss", 49000.0)

            stats = get_accuracy_stats(conn)
            assert "trending-up" in stats
            assert abs(stats["trending-up"]["accuracy"] - 5 / 7) < 0.001
