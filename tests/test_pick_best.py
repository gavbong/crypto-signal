"""Tests for _pick_best: confirms highest regime_confidence wins per base asset."""
from signal_engine import _pick_best


def _sig(pair, direction, strategy, regime, confidence, exchange="mexc"):
    return {
        "pair": pair,
        "direction": direction,
        "strategy": strategy,
        "regime": regime,
        "regime_confidence": confidence,
        "regime_age_candles": 5,
        "entry_price": 100.0,
        "suggested_stop_loss": 98.0,
        "suggested_take_profit": 104.0,
        "timeframe": "15m",
        "fired_at": "2026-01-01T00:00:00+00:00",
        "shadow_mode": True,
        "exchange": exchange,
        "_regime_context": {},
    }


class TestPickBest:
    def test_single_candidate_passes_through(self):
        candidates = [_sig("BTC/USDT:USDT", "long", "ema_9_21_crossover", "trending-up", 0.70)]
        result = _pick_best(candidates)
        assert len(result) == 1
        assert result[0]["exchange"] == "mexc"

    def test_higher_confidence_wins(self):
        """OKX has 0.85 confidence vs MEXC 0.60 — OKX should win."""
        candidates = [
            _sig("BTC/USDT:USDT", "long", "ema_9_21_crossover", "trending-up", 0.60, "mexc"),
            _sig("BTC/USDT:USDT", "long", "ema_9_21_crossover", "trending-up", 0.85, "okx"),
            _sig("BTC/USDT:USDT", "long", "ema_9_21_crossover", "trending-up", 0.72, "binance"),
        ]
        result = _pick_best(candidates)
        assert len(result) == 1
        assert result[0]["exchange"] == "okx"
        assert result[0]["regime_confidence"] == 0.85

    def test_usdc_pair_deduped_against_usdt(self):
        """BTC/USDC:USDC (Hyperliquid) and BTC/USDT:USDT (MEXC) — only best survives."""
        candidates = [
            _sig("BTC/USDT:USDT", "short", "rsi_divergence", "choppy", 0.65, "mexc"),
            _sig("BTC/USDC:USDC", "short", "rsi_divergence", "choppy", 0.78, "hyperliquid"),
        ]
        result = _pick_best(candidates)
        assert len(result) == 1
        assert result[0]["exchange"] == "hyperliquid"

    def test_different_base_assets_both_pass(self):
        """BTC and ETH are different tokens — both signals should survive."""
        candidates = [
            _sig("BTC/USDT:USDT", "long", "ema_9_21_crossover", "trending-up", 0.80, "mexc"),
            _sig("ETH/USDT:USDT", "long", "ema_9_21_crossover", "trending-up", 0.75, "binance"),
        ]
        result = _pick_best(candidates)
        assert len(result) == 2
        bases = {r["pair"].split("/")[0] for r in result}
        assert bases == {"BTC", "ETH"}

    def test_conflicting_directions_only_one_survives(self):
        """BTC long (0.80) and BTC short (0.75) — only the higher-confidence long survives."""
        candidates = [
            _sig("BTC/USDT:USDT", "long",  "ema_9_21_crossover", "trending-up",   0.80, "mexc"),
            _sig("BTC/USDT:USDT", "short", "ema_9_21_crossover", "trending-down", 0.75, "okx"),
        ]
        result = _pick_best(candidates)
        assert len(result) == 1
        assert result[0]["direction"] == "long"

    def test_competing_strategies_best_wins(self):
        """Two strategies for the same token — highest confidence (rsi 0.90) wins."""
        candidates = [
            _sig("BTC/USDT:USDT", "long", "ema_9_21_crossover", "trending-up", 0.80, "mexc"),
            _sig("BTC/USDT:USDT", "long", "rsi_divergence",     "trending-up", 0.90, "binance"),
        ]
        result = _pick_best(candidates)
        assert len(result) == 1
        assert result[0]["strategy"] == "rsi_divergence"

    def test_tie_keeps_first_seen(self):
        """Equal confidence — config order (first in list) wins."""
        candidates = [
            _sig("BTC/USDT:USDT", "long", "ema_9_21_crossover", "trending-up", 0.80, "mexc"),
            _sig("BTC/USDT:USDT", "long", "ema_9_21_crossover", "trending-up", 0.80, "binance"),
        ]
        result = _pick_best(candidates)
        assert len(result) == 1
        assert result[0]["exchange"] == "mexc"

    def test_empty_candidates_returns_empty(self):
        assert _pick_best([]) == []
