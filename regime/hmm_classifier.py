"""
regime/hmm_classifier.py — Hidden Markov Model macro regime detector.

Trains a Gaussian HMM on daily BTC-USD price data (proxy for overall crypto
market cycle) and classifies the current macro environment as one of:
    crash | bear | neutral | bull | euphoria

This is a macro-level overlay on top of the intraday regime classifier. It
operates on daily candles and uses the forward algorithm only — no lookahead.

The macro regime is stored in paper_state (key: macro_regime / macro_regime_conf)
so the paper trader can scale position sizes accordingly:
    crash    → 0% of normal size  (halt)
    bear     → 30%
    neutral  → 70%
    bull     → 100%
    euphoria → 80%  (overextended — reduce slightly)
"""
from __future__ import annotations

import json
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path

import numpy as np
from loguru import logger

# ── State labels ordered by market sentiment (crash → euphoria) ────────────────
_LABELS_BY_N: dict[int, list[str]] = {
    3: ["bear", "neutral", "bull"],
    4: ["crash", "bear", "bull", "euphoria"],
    5: ["crash", "bear", "neutral", "bull", "euphoria"],
}

# Risk multipliers per macro label (applied to per-trade risk_pct)
MACRO_RISK_MULT: dict[str, float] = {
    "crash":    0.0,   # halt all entries
    "bear":     0.3,   # 30% of normal size
    "neutral":  0.7,   # 70%
    "bull":     1.0,   # full size
    "euphoria": 0.8,   # slightly reduced — overextended market
}

_CACHE_PATH = Path("data/macro/hmm_model_cache.json")
_TRAIN_DAYS = 504          # ~2 years of daily data
_RETRAIN_INTERVAL_H = 24   # retrain once per day
_MIN_STATES = 3
_MAX_STATES = 5
_STABILITY_BARS = 3        # macro regime must persist N bars before acting


class MacroHMMClassifier:
    """
    Trains a Gaussian HMM on daily BTC-USD log returns + realized volatility.
    Auto-selects the number of states (3–5) by BIC.
    Inference uses the forward algorithm only — causal, no lookahead.
    """

    def __init__(self) -> None:
        self._model = None
        self._state_labels: list[str] = []
        self._trained_at: float = 0.0
        self._recent_labels: list[str] = []  # last N macro labels for stability check

    # ── Training ───────────────────────────────────────────────────────────────

    def fit(self, ticker: str = "BTC-USD") -> bool:
        """Download daily data and train. Returns True on success."""
        try:
            features, dates = self._fetch_features(ticker)
            if features is None or len(features) < 60:
                logger.warning("MacroHMM: insufficient training data")
                return False

            best_model, best_n = self._select_model(features)
            if best_model is None:
                logger.warning("MacroHMM: model selection failed")
                return False

            self._model = best_model
            self._state_labels = self._label_states(best_model, best_n)
            self._trained_at = time.time()

            # Warm up recent_labels from the tail of training data
            states = self._forward_states(features[-20:])
            self._recent_labels = [self._state_labels[s] for s in states]

            logger.info(
                f"MacroHMM: trained n_states={best_n} labels={self._state_labels} "
                f"on {len(features)} days, current={self._recent_labels[-1]}"
            )
            self._save_cache()
            return True

        except Exception as exc:
            logger.warning(f"MacroHMM: fit failed — {exc}")
            return False

    def retrain_needed(self) -> bool:
        return (time.time() - self._trained_at) > _RETRAIN_INTERVAL_H * 3600

    # ── Inference ─────────────────────────────────────────────────────────────

    def predict(self, ticker: str = "BTC-USD") -> tuple[str, float]:
        """
        Return (macro_label, confidence) for the current moment.
        confidence = posterior probability of the most likely state.
        Falls back to ('neutral', 0.0) if model not ready.
        """
        if self._model is None:
            return "neutral", 0.0
        try:
            features, _ = self._fetch_features(ticker, limit=30)
            if features is None or len(features) < 5:
                return "neutral", 0.0

            posteriors = self._forward_posteriors(features)
            last = posteriors[-1]
            state = int(np.argmax(last))
            conf = float(last[state])
            label = self._state_labels[state]

            # Update rolling label buffer for stability tracking
            self._recent_labels.append(label)
            if len(self._recent_labels) > 20:
                self._recent_labels = self._recent_labels[-20:]

            return label, round(conf, 3)

        except Exception as exc:
            logger.warning(f"MacroHMM: predict failed — {exc}")
            return "neutral", 0.0

    def is_stable(self) -> bool:
        """True if the last _STABILITY_BARS macro labels all agree."""
        recent = self._recent_labels[-_STABILITY_BARS:]
        return len(recent) >= _STABILITY_BARS and len(set(recent)) == 1

    # ── Feature engineering ────────────────────────────────────────────────────

    def _fetch_features(self, ticker: str, limit: int = _TRAIN_DAYS
                        ) -> tuple[np.ndarray | None, list]:
        """Download daily OHLCV from yfinance and compute HMM features."""
        try:
            import yfinance as yf
            period = f"{limit + 30}d"
            df = yf.download(ticker, period=period, progress=False, auto_adjust=True)
            if df.empty or len(df) < 10:
                return None, []

            # Flatten MultiIndex columns if present (yfinance >= 0.2)
            if hasattr(df.columns, "levels"):
                df.columns = [c[0] if isinstance(c, tuple) else c for c in df.columns]

            df = df.dropna(subset=["Close", "Volume"])
            close = df["Close"].values.astype(float)
            volume = df["Volume"].values.astype(float)
            dates = df.index.tolist()

            log_ret = np.diff(np.log(close))
            # 10-day realized volatility
            rv = np.array([
                log_ret[max(0, i - 9):i + 1].std()
                for i in range(len(log_ret))
            ])
            # Volume z-score (20-day rolling)
            vol_z = np.array([
                (volume[i + 1] - volume[max(0, i - 18):i + 1].mean())
                / (volume[max(0, i - 18):i + 1].std() + 1e-9)
                for i in range(len(log_ret))
            ])

            features = np.column_stack([log_ret, rv, vol_z])
            # Clip extreme values to 5 sigma
            for col in range(features.shape[1]):
                mu, sd = features[:, col].mean(), features[:, col].std()
                features[:, col] = np.clip(features[:, col], mu - 5 * sd, mu + 5 * sd)

            features = features[-limit:]
            dates = dates[-(limit + 1):]
            return features, dates

        except Exception as exc:
            logger.warning(f"MacroHMM: feature fetch failed — {exc}")
            return None, []

    # ── Model selection ────────────────────────────────────────────────────────

    def _select_model(self, features: np.ndarray):
        """Try n_states = 3..5, pick the one with the best (lowest) BIC."""
        from hmmlearn.hmm import GaussianHMM

        best_bic = np.inf
        best_model = None
        best_n = _MIN_STATES

        for n in range(_MIN_STATES, _MAX_STATES + 1):
            for attempt in range(3):  # multiple random inits
                try:
                    model = GaussianHMM(
                        n_components=n,
                        covariance_type="full",
                        n_iter=200,
                        tol=1e-4,
                        random_state=42 + attempt,
                    )
                    model.fit(features)
                    log_lik = model.score(features)
                    n_params = n * n + n * features.shape[1] + n * features.shape[1] ** 2
                    bic = -2 * log_lik * len(features) + n_params * np.log(len(features))
                    if bic < best_bic:
                        best_bic = bic
                        best_model = model
                        best_n = n
                except Exception:
                    continue

        return best_model, best_n

    # ── State labeling ─────────────────────────────────────────────────────────

    def _label_states(self, model, n_states: int) -> list[str]:
        """Sort HMM states by mean log return → assign crash/bear/.../euphoria."""
        means = model.means_[:, 0]  # first feature = log return
        order = np.argsort(means)   # ascending: crash first
        labels_template = _LABELS_BY_N.get(n_states, _LABELS_BY_N[3])
        label_map = [""] * n_states
        for rank, state_idx in enumerate(order):
            label_map[state_idx] = labels_template[rank]
        return label_map

    # ── Forward algorithm ──────────────────────────────────────────────────────

    def _forward_posteriors(self, features: np.ndarray) -> np.ndarray:
        """
        Run the forward algorithm on features — causal, no lookahead.
        Returns posterior (normalized alpha) for each timestep.
        """
        from scipy.stats import multivariate_normal

        model = self._model
        n = model.n_components
        T = len(features)
        alpha = np.zeros((T, n))

        # t=0: use start probabilities
        for j in range(n):
            alpha[0, j] = model.startprob_[j] * multivariate_normal.pdf(
                features[0], model.means_[j], model.covars_[j]
            )
        s = alpha[0].sum()
        alpha[0] /= s + 1e-300

        # t=1..T-1: forward recursion
        for t in range(1, T):
            for j in range(n):
                alpha[t, j] = np.dot(alpha[t - 1], model.transmat_[:, j]) * \
                    multivariate_normal.pdf(features[t], model.means_[j], model.covars_[j])
            s = alpha[t].sum()
            alpha[t] /= s + 1e-300

        return alpha

    def _forward_states(self, features: np.ndarray) -> list[int]:
        """Return the argmax state at each timestep (forward only)."""
        posteriors = self._forward_posteriors(features)
        return [int(np.argmax(posteriors[t])) for t in range(len(posteriors))]

    # ── Persistence ───────────────────────────────────────────────────────────

    def _save_cache(self) -> None:
        """Cache model parameters so we survive restarts without re-downloading."""
        try:
            _CACHE_PATH.parent.mkdir(parents=True, exist_ok=True)
            model = self._model
            cache = {
                "trained_at": self._trained_at,
                "state_labels": self._state_labels,
                "recent_labels": self._recent_labels,
                "n_components": model.n_components,
                "startprob": model.startprob_.tolist(),
                "transmat": model.transmat_.tolist(),
                "means": model.means_.tolist(),
                "covars": model.covars_.tolist(),
            }
            _CACHE_PATH.write_text(json.dumps(cache))
        except Exception as exc:
            logger.debug(f"MacroHMM: cache save failed — {exc}")

    def load_cache(self) -> bool:
        """Restore model from disk cache. Returns True if cache is fresh enough."""
        try:
            if not _CACHE_PATH.exists():
                return False
            cache = json.loads(_CACHE_PATH.read_text())
            age_h = (time.time() - cache["trained_at"]) / 3600
            if age_h > _RETRAIN_INTERVAL_H * 2:
                return False

            from hmmlearn.hmm import GaussianHMM
            import numpy as np

            model = GaussianHMM(n_components=cache["n_components"])
            model.startprob_ = np.array(cache["startprob"])
            model.transmat_ = np.array(cache["transmat"])
            model.means_ = np.array(cache["means"])
            model.covars_ = np.array(cache["covars"])
            # hmmlearn needs these set to avoid predict errors
            model.n_features = model.means_.shape[1]
            model.covariance_type = "full"

            self._model = model
            self._state_labels = cache["state_labels"]
            self._trained_at = cache["trained_at"]
            self._recent_labels = cache.get("recent_labels", [])
            logger.info(
                f"MacroHMM: loaded cache (age {age_h:.1f}h) "
                f"labels={self._state_labels} recent={self._recent_labels[-3:]}"
            )
            return True
        except Exception as exc:
            logger.debug(f"MacroHMM: cache load failed — {exc}")
            return False


# Module-level singleton
_classifier: MacroHMMClassifier | None = None


def get_classifier() -> MacroHMMClassifier:
    global _classifier
    if _classifier is None:
        _classifier = MacroHMMClassifier()
    return _classifier


def current_macro_regime(ticker: str = "BTC-USD") -> tuple[str, float, bool]:
    """
    Convenience function — returns (label, confidence, stable).
    Trains/retrains the singleton classifier as needed.
    """
    clf = get_classifier()
    if clf._model is None:
        if not clf.load_cache():
            logger.info("MacroHMM: training from scratch...")
            clf.fit(ticker)
    elif clf.retrain_needed():
        logger.info("MacroHMM: retraining (24h interval)...")
        clf.fit(ticker)

    label, conf = clf.predict(ticker)
    stable = clf.is_stable()
    return label, conf, stable
