from __future__ import annotations

from datetime import datetime, timedelta

import numpy as np
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

    def _always_buy(
        _bars: list[dict],
        market_trend: int = 0,
        earnings_soon: bool = False,
        threshold: int | None = None,
        timeframe: str | None = None,
    ) -> dict:
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
        timeframe="1Day",
        initial_cash=100_000,
        threshold=3,
        stop_loss_pct=0.05,
        take_profit_pct=0.05,
        slippage_bps=0.0,
        fee_per_trade=0.0,
    )

    assert trades
    assert any(t["exit_reason"] == "take_profit" for t in trades)


def test_simulate_respects_strategy_signal_over_raw_score(monkeypatch):
    start = datetime(2026, 1, 1)
    rows = []
    for i in range(32):
        rows.append({"t": start + timedelta(days=i), "o": 100.0, "h": 100.0, "l": 100.0, "c": 100.0, "v": 1_000_000})
    df = pd.DataFrame(rows)

    def _gated_hold(
        _bars: list[dict],
        market_trend: int = 0,
        earnings_soon: bool = False,
        threshold: int | None = None,
        timeframe: str | None = None,
    ) -> dict:
        return {
            "signal": "hold",
            "score": 10,
            "reason": "gated",
            "rsi": 50,
            "price": 100,
            "atr": 1,
            "event_score": 0,
            "event_reasons": [],
            "regime": "bull_trend",
            "regime_confidence": 1.0,
        }

    monkeypatch.setattr(backtest.strategy, "compute_signals", _gated_hold)

    trades, _, final_equity = backtest._simulate(
        df=df,
        symbol="AAPL",
        timeframe="1Day",
        initial_cash=100_000,
        threshold=3,
        stop_loss_pct=0.0,
        take_profit_pct=0.0,
        slippage_bps=0.0,
        fee_per_trade=0.0,
        warmup_override=30,
    )

    assert trades == []
    assert final_equity == 100_000


def test_build_spy_trend_uses_previous_completed_day(monkeypatch):
    def _spy_bars(_symbol: str, timeframe: str = "1Day", lookback_days: int = 0) -> list[dict]:
        assert timeframe == "1Day"
        return [
            {"t": "2026-01-01T00:00:00", "o": 100.0, "h": 100.0, "l": 100.0, "c": 100.0, "v": 1_000_000},
            {"t": "2026-01-02T00:00:00", "o": 80.0, "h": 80.0, "l": 80.0, "c": 80.0, "v": 1_000_000},
            {"t": "2026-01-03T00:00:00", "o": 80.0, "h": 80.0, "l": 80.0, "c": 80.0, "v": 1_000_000},
        ]

    monkeypatch.setattr(backtest.broker, "get_bars", _spy_bars)

    trend = backtest._build_spy_trend("5Min", 20)

    assert "2026-01-01" not in trend
    assert trend["2026-01-02"] == 1
    assert trend["2026-01-03"] == -1


def test_simulate_trailing_stop_uses_prior_peak(monkeypatch):
    start = datetime(2026, 1, 1)
    rows = []
    for i in range(30):
        rows.append({"t": start + timedelta(days=i), "o": 100.0, "h": 100.0, "l": 100.0, "c": 100.0, "v": 1_000_000})
    rows.append({"t": start + timedelta(days=30), "o": 100.0, "h": 100.0, "l": 100.0, "c": 100.0, "v": 1_000_000})
    rows.append({"t": start + timedelta(days=31), "o": 100.0, "h": 110.0, "l": 104.0, "c": 110.0, "v": 1_000_000})
    df = pd.DataFrame(rows)

    def _always_buy(
        _bars: list[dict],
        market_trend: int = 0,
        earnings_soon: bool = False,
        threshold: int | None = None,
        timeframe: str | None = None,
    ) -> dict:
        return {
            "signal": "buy",
            "score": 10,
            "reason": "forced",
            "rsi": 50,
            "price": 100,
            "atr": 20,
            "event_score": 0,
            "event_reasons": [],
            "regime": "bull_trend",
            "regime_confidence": 1.0,
        }

    monkeypatch.setattr(backtest.strategy, "compute_signals", _always_buy)

    trades, _, _ = backtest._simulate(
        df=df,
        symbol="AAPL",
        timeframe="1Day",
        initial_cash=100_000,
        threshold=3,
        stop_loss_pct=0.05,
        take_profit_pct=0.0,
        slippage_bps=0.0,
        fee_per_trade=0.0,
        warmup_override=30,
    )

    assert trades
    assert trades[-1]["exit_reason"] == "end_of_test"
    assert all(t["exit_reason"] != "trailing_stop" for t in trades)


def test_simulate_partial_exit_fee_allocation_matches_portfolio_pnl(monkeypatch):
    monkeypatch.setattr(config, "MAX_POSITION_PCT", 0.5)

    start = datetime(2026, 1, 1)
    rows = []
    for i in range(30):
        rows.append({"t": start + timedelta(days=i), "o": 100.0, "h": 100.0, "l": 100.0, "c": 100.0, "v": 1_000_000})
    rows.append({"t": start + timedelta(days=30), "o": 100.0, "h": 100.0, "l": 100.0, "c": 100.0, "v": 1_000_000})
    rows.append({"t": start + timedelta(days=31), "o": 116.0, "h": 116.0, "l": 116.0, "c": 116.0, "v": 1_000_000})
    df = pd.DataFrame(rows)

    def _always_buy(
        _bars: list[dict],
        market_trend: int = 0,
        earnings_soon: bool = False,
        threshold: int | None = None,
        timeframe: str | None = None,
    ) -> dict:
        return {
            "signal": "buy",
            "score": 10,
            "reason": "forced",
            "rsi": 50,
            "price": 100,
            "atr": 10,
            "event_score": 0,
            "event_reasons": [],
            "regime": "bull_trend",
            "regime_confidence": 1.0,
        }

    monkeypatch.setattr(backtest.strategy, "compute_signals", _always_buy)

    initial_cash = 100_000
    trades, _, final_equity = backtest._simulate(
        df=df,
        symbol="AAPL",
        timeframe="1Day",
        initial_cash=initial_cash,
        threshold=3,
        stop_loss_pct=0.0,
        take_profit_pct=0.0,
        slippage_bps=0.0,
        fee_per_trade=10.0,
        warmup_override=30,
    )

    assert [t["exit_reason"] for t in trades] == ["partial_profit", "end_of_test"]
    assert round(sum(t["pnl"] for t in trades), 2) == round(final_equity - initial_cash, 2)


def test_compute_stats_uses_timeframe_specific_sharpe_annualization():
    equity_curve = [
        {"date": "2026-01-01 00:00", "equity": 100_000.0},
        {"date": "2026-01-02 00:00", "equity": 101_000.0},
        {"date": "2026-01-03 00:00", "equity": 100_500.0},
        {"date": "2026-01-04 00:00", "equity": 102_000.0},
    ]

    daily_stats = backtest._compute_stats([], 100_000.0, 102_000.0, equity_curve, timeframe="1Day")
    minute_stats = backtest._compute_stats([], 100_000.0, 102_000.0, equity_curve, timeframe="1Min")
    eq_vals = np.array([e["equity"] for e in equity_curve], dtype=float)
    rets = np.diff(eq_vals) / eq_vals[:-1]
    base_sharpe = float(np.mean(rets) / np.std(rets))
    expected_daily = round(base_sharpe * (252 ** 0.5), 3)
    expected_minute = round(base_sharpe * ((252 * 390) ** 0.5), 3)

    assert daily_stats["sharpe"] == expected_daily
    assert minute_stats["sharpe"] > daily_stats["sharpe"]
    assert minute_stats["sharpe"] == expected_minute


def test_simulate_does_not_reenter_on_same_bar_after_intrabar_exit(monkeypatch):
    monkeypatch.setattr(config, "MAX_POSITION_PCT", 0.5)

    start = datetime(2026, 1, 1)
    rows = []
    for i in range(41):
        close = 100.0
        high = 101.0
        low = 99.0
        if i == 40:
            close = 104.0
            high = 110.0
            low = 99.0
        rows.append({"t": start + timedelta(days=i), "o": close, "h": high, "l": low, "c": close, "v": 1_000_000})
    df = pd.DataFrame(rows)

    def _always_buy(
        _bars: list[dict],
        market_trend: int = 0,
        earnings_soon: bool = False,
        threshold: int | None = None,
        timeframe: str | None = None,
    ) -> dict:
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

    trades, _, final_equity = backtest._simulate(
        df=df,
        symbol="AAPL",
        timeframe="1Day",
        initial_cash=100_000,
        threshold=3,
        stop_loss_pct=0.05,
        take_profit_pct=0.05,
        slippage_bps=0.0,
        fee_per_trade=0.0,
    )

    assert len(trades) == 1
    assert trades[0]["exit_reason"] == "take_profit"
    assert final_equity == 102_500.0


def test_equity_curve_includes_final_liquidation_equity(monkeypatch):
    monkeypatch.setattr(config, "MAX_POSITION_PCT", 0.5)

    start = datetime(2026, 1, 1)
    rows = []
    for i in range(35):
        close = 100.0 if i < 34 else 102.0
        rows.append({"t": start + timedelta(days=i), "o": close, "h": close, "l": close, "c": close, "v": 1_000_000})
    df = pd.DataFrame(rows)

    def _always_buy(
        _bars: list[dict],
        market_trend: int = 0,
        earnings_soon: bool = False,
        threshold: int | None = None,
        timeframe: str | None = None,
    ) -> dict:
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

    _, equity_curve, final_equity = backtest._simulate(
        df=df,
        symbol="AAPL",
        timeframe="1Day",
        initial_cash=100_000,
        threshold=3,
        stop_loss_pct=0.0,
        take_profit_pct=0.0,
        slippage_bps=0.0,
        fee_per_trade=10.0,
    )

    assert equity_curve[-1]["equity"] == round(final_equity, 2)


def test_select_training_parameters_respects_trade_floor(monkeypatch):
    monkeypatch.setattr(backtest, "_parameter_grid", lambda: [(2, 0.02, 0.05), (3, 0.05, 0.10)])

    def _fake_eval(
        df,
        symbol,
        timeframe,
        initial_cash,
        threshold,
        stop_loss_pct,
        take_profit_pct,
        market_trend_by_date=None,
        filter_context=None,
        warmup_override=None,
    ):
        if threshold == 2:
            return {
                "threshold": threshold,
                "stop_loss_pct": stop_loss_pct,
                "take_profit_pct": take_profit_pct,
                "trades": 1,
                "sharpe": 99.0,
                "total_return_pct": 50.0,
                "max_drawdown_pct": 1.0,
            }
        return {
            "threshold": threshold,
            "stop_loss_pct": stop_loss_pct,
            "take_profit_pct": take_profit_pct,
            "trades": 8,
            "sharpe": 1.0,
            "total_return_pct": 5.0,
            "max_drawdown_pct": 2.0,
        }

    monkeypatch.setattr(backtest, "_evaluate_parameters", _fake_eval)

    df = pd.DataFrame(
        [{"t": datetime(2026, 1, 1) + timedelta(days=i), "o": 100.0, "h": 100.0, "l": 100.0, "c": 100.0, "v": 1_000_000} for i in range(80)]
    )
    best = backtest._select_training_parameters(df, "AAPL", "1Day", 100_000)

    assert best is not None
    assert best["threshold"] == 3


def test_optimize_ranks_on_validation_not_training(monkeypatch):
    bars = [
        {"t": (datetime(2026, 1, 1) + timedelta(days=i)).isoformat(), "o": 100.0, "h": 100.0, "l": 100.0, "c": 100.0, "v": 1_000_000}
        for i in range(60)
    ]
    monkeypatch.setattr(backtest.broker, "get_bars", lambda *args, **kwargs: bars)
    monkeypatch.setattr(backtest, "_build_filter_context", lambda *args, **kwargs: {})
    monkeypatch.setattr(backtest, "_parameter_grid", lambda: [(2, 0.02, 0.05), (3, 0.05, 0.10)])

    def _fake_eval(
        df,
        symbol,
        timeframe,
        initial_cash,
        threshold,
        stop_loss_pct,
        take_profit_pct,
        market_trend_by_date=None,
        filter_context=None,
        warmup_override=None,
    ):
        if warmup_override is None:
            train_by_threshold = {
                2: {"trades": 6, "sharpe": 5.0, "total_return_pct": 12.0, "max_drawdown_pct": 1.0},
                3: {"trades": 6, "sharpe": 2.0, "total_return_pct": 8.0, "max_drawdown_pct": 1.0},
            }
            return {
                "threshold": threshold,
                "stop_loss_pct": stop_loss_pct,
                "take_profit_pct": take_profit_pct,
                **train_by_threshold[threshold],
            }

        validation_by_threshold = {
            2: {"trades": 4, "sharpe": 0.5, "total_return_pct": 1.0, "max_drawdown_pct": 3.0, "win_rate_pct": 50.0},
            3: {"trades": 4, "sharpe": 3.0, "total_return_pct": 4.0, "max_drawdown_pct": 2.0, "win_rate_pct": 55.0},
        }
        return {
            "threshold": threshold,
            "stop_loss_pct": stop_loss_pct,
            "take_profit_pct": take_profit_pct,
            **validation_by_threshold[threshold],
        }

    monkeypatch.setattr(backtest, "_evaluate_parameters", _fake_eval)

    result = backtest.optimize("AAPL", timeframe="1Day", lookback_days=60)

    assert result["selection"] == "train_validation"
    assert result["best"]["threshold"] == 3
