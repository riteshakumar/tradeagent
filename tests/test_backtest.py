from __future__ import annotations

from datetime import datetime, timedelta

import pandas as pd

import backtest
import config


def test_check_bar_exit_prefers_stop_when_both_hit():
    # peak_price == entry_price (no run-up), both stop and TP touched intrabar
    bar = pd.Series({"l": 94.0, "h": 107.0})
    hit = backtest._check_bar_exit(100.0, 100.0, bar, stop_loss_pct=0.05, take_profit_pct=0.05)
    assert hit is not None
    px, reason = hit
    assert round(px, 2) == 95.00
    assert reason == "trailing_stop"   # stop takes priority; stop trails from peak


def test_check_bar_exit_only_take_profit():
    bar = pd.Series({"l": 99.0, "h": 106.0})
    hit = backtest._check_bar_exit(100.0, 100.0, bar, stop_loss_pct=0.05, take_profit_pct=0.05)
    assert hit is not None
    _, reason = hit
    assert reason == "take_profit"


def test_check_bar_exit_none_when_no_trigger():
    bar = pd.Series({"l": 99.0, "h": 101.0})
    assert backtest._check_bar_exit(100.0, 100.0, bar, stop_loss_pct=0.05, take_profit_pct=0.05) is None


def test_check_bar_exit_trailing_stop_from_peak():
    # Peak moved up to 110 — stop trails from 110, not 100
    bar = pd.Series({"l": 103.0, "h": 105.0})
    hit = backtest._check_bar_exit(100.0, 110.0, bar, stop_loss_pct=0.05, take_profit_pct=0.20)
    # stop_px = 110 * 0.95 = 104.5, bar low = 103 → stop hit
    assert hit is not None
    px, reason = hit
    assert round(px, 2) == 104.50
    assert reason == "trailing_stop"


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

    def _always_buy(_bars: list[dict], market_trend: int = 0, earnings_soon: bool = False) -> dict:
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
