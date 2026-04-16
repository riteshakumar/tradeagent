from __future__ import annotations

from datetime import datetime, timedelta

import config
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


def test_apply_event_score_preserves_regime_keys():
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

    assert out["signal"] == "buy"
    assert out["regime"] == "range"
