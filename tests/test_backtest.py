from __future__ import annotations

from datetime import datetime, timedelta

import pandas as pd

import backtest
import config


def test_check_bar_exit_prefers_stop_when_both_hit():
    bar = pd.Series({"l": 94.0, "h": 107.0})
    hit = backtest._check_bar_exit(100.0, bar, stop_loss_pct=0.05, take_profit_pct=0.05)
    assert hit is not None
    px, reason = hit
    assert round(px, 2) == 95.00
    assert reason == "stop_loss"


def test_simulate_applies_take_profit(monkeypatch):
    monkeypatch.setattr(config, "MAX_POSITION_PCT", 0.5)

    start = datetime(2026, 1, 1)
    rows = []
    for i in range(70):
        close = 100.0
        high = 101.0
        low = 99.0
        if i == 40:
            close = 104.0
            high = 110.0
            low = 99.0
        rows.append({"t": start + timedelta(days=i), "o": close, "h": high, "l": low, "c": close, "v": 1_000_000})
    df = pd.DataFrame(rows)

    def _always_buy(_bars: list[dict]) -> dict:
        return {
            "signal": "buy",
            "score": 10,
            "reason": "forced",
            "rsi": 50,
            "price": 100,
            "atr": 1,
            "event_score": 0,
            "event_reasons": [],
            "regime": "bull_trend",
            "regime_confidence": 1.0,
        }

    monkeypatch.setattr(backtest.strategy, "compute_signals", _always_buy)

    trades, _, _ = backtest._simulate(
        df=df,
        symbol="AAPL",
        initial_cash=100_000,
        threshold=3,
        stop_loss_pct=0.05,
        take_profit_pct=0.05,
        slippage_bps=0.0,
        fee_per_trade=0.0,
    )

    assert trades
    assert any(t["exit_reason"] == "take_profit" for t in trades)
