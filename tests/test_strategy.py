from __future__ import annotations

from datetime import datetime, timedelta

import config
import pandas as pd
import strategy


def _bars_from_prices(prices: list[float]) -> list[dict]:
    start = datetime(2026, 1, 1)
    rows = []
    for i, p in enumerate(prices):
        rows.append(
            {
                "t": (start + timedelta(days=i)).isoformat(),
                "o": p * 0.995,
                "h": p * 1.01,
                "l": p * 0.99,
                "c": p,
                "v": 1_000_000 + i * 1000,
            }
        )
    return rows


def test_compute_signals_includes_regime_fields(monkeypatch):
    monkeypatch.setattr(config, "ENABLE_REGIME_SWITCHING", True)
    prices = [100 + (i * 0.8) for i in range(120)]
    sig = strategy.compute_signals(_bars_from_prices(prices))

    assert "regime" in sig
    assert "regime_confidence" in sig
    assert sig["regime"] in {"bull_trend", "bear_trend", "range", "high_volatility"}


def test_detects_high_volatility_regime(monkeypatch):
    monkeypatch.setattr(config, "ENABLE_REGIME_SWITCHING", True)
    monkeypatch.setattr(config, "TREND_STRENGTH_THRESHOLD", 0.5)
    monkeypatch.setattr(config, "HIGH_VOL_THRESHOLD", 0.002)

    prices = [100 + ((-1) ** i) * (i * 0.6) for i in range(120)]
    sig = strategy.compute_signals(_bars_from_prices(prices))

    assert sig["regime"] == "high_volatility"


def test_apply_event_score_preserves_regime_keys(monkeypatch):
    monkeypatch.setattr(config, "SIGNAL_THRESHOLD", 3)
    quant = {
        "signal": "hold",
        "score": 1,
        "reason": "base",
        "regime": "range",
        "regime_confidence": 0.5,
        "event_score": 0,
        "event_reasons": [],
    }
    event = {"event_score": 2, "event_reasons": ["earnings beat"]}
    out = strategy.apply_event_score(quant, event)

    assert out["signal"] == "buy"   # 1 + 2 = 3 >= threshold of 3
    assert out["regime"] == "range"


def test_compute_signals_honors_threshold_override(monkeypatch):
    monkeypatch.setattr(config, "SIGNAL_THRESHOLD", 3)
    monkeypatch.setattr(config, "ENABLE_REGIME_SWITCHING", False)

    def _stub_components(_close, _volume, _df, timeframe="1Day", is_intraday=False):
        return (
            {"ema": 1},
            {"ema": "stub"},
            {"regime": "bull_trend", "confidence": 1.0, "trend_strength": 1.0, "realized_vol": 0.0},
            30.0,
        )

    monkeypatch.setattr(strategy, "_score_components", _stub_components)

    bars = _bars_from_prices([100.0] * 35)
    default_sig = strategy.compute_signals(bars)
    override_sig = strategy.compute_signals(bars, threshold=1)

    assert default_sig["signal"] == "hold"
    assert override_sig["signal"] == "buy"


def test_compute_signals_uses_explicit_timeframe_for_intraday(monkeypatch):
    captured = {}

    def _stub_components(_close, _volume, _df, timeframe="1Day", is_intraday=False):
        captured["timeframe"] = timeframe
        captured["is_intraday"] = is_intraday
        return (
            {},
            {},
            {"regime": "range", "confidence": 0.6, "trend_strength": 0.0, "realized_vol": 0.0},
            10.0,
        )

    monkeypatch.setattr(strategy, "_score_components", _stub_components)

    bars = _bars_from_prices([100.0] * 35)
    sig = strategy.compute_signals(bars, timeframe="5Min")

    assert sig["timeframe"] == "5Min"
    assert captured["timeframe"] == "5Min"
    assert captured["is_intraday"] is True


def test_disable_regime_switching_disables_adx_mode_switch(monkeypatch):
    bars = _bars_from_prices([100.0] * 40)
    df = pd.DataFrame(bars)
    close = df["c"].astype(float)
    volume = df["v"].astype(float)

    monkeypatch.setattr(strategy, "_adx", lambda _df, period=14: pd.Series([30.0] * len(_df), index=_df.index))
    monkeypatch.setattr(strategy, "_rsi_score", lambda rsi, prev_rsi=None: (2, "rsi"))
    monkeypatch.setattr(strategy, "_bb_score", lambda price, upper, lower, bb_width_pct=None: (2, "bb"))
    monkeypatch.setattr(strategy, "_macd_score", lambda *args: (0, ""))
    monkeypatch.setattr(strategy, "_ema_score", lambda *args: (0, ""))
    monkeypatch.setattr(strategy, "_supertrend_score", lambda *args: (0, ""))
    monkeypatch.setattr(strategy, "_breakout_score", lambda *args: (0, ""))
    monkeypatch.setattr(strategy, "_momentum_score", lambda *args: (0, ""))
    monkeypatch.setattr(strategy, "_volume_score", lambda volume, current_score: (0, ""))

    monkeypatch.setattr(config, "ENABLE_REGIME_SWITCHING", True)
    scores_enabled, _, _, _ = strategy._score_components(close, volume, df, timeframe="1Day", is_intraday=False)

    monkeypatch.setattr(config, "ENABLE_REGIME_SWITCHING", False)
    scores_disabled, _, _, _ = strategy._score_components(close, volume, df, timeframe="1Day", is_intraday=False)

    assert scores_enabled == {}
    assert scores_disabled["rsi"] == 2
    assert scores_disabled["bb"] == 2
