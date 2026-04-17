from __future__ import annotations

import config
import risk


def _account(equity: float = 100000.0) -> dict:
    return {
        "equity": equity,
        "cash": equity,
        "buying_power": equity * 2,
        "portfolio_value": equity,
    }


def test_drawdown_halt_latches(monkeypatch):
    risk.reset_halts(reset_peak=True)
    monkeypatch.setattr(config, "MAX_DRAWDOWN_PCT", 0.05)

    first = risk.evaluate_drawdown(_account(100000))
    second = risk.evaluate_drawdown(_account(94000))
    recovered = risk.evaluate_drawdown(_account(99000))

    assert not first["halted"]
    assert second["halted"]
    assert second["just_triggered"]
    assert recovered["halted"]


def test_daily_loss_stop_blocks_pre_trade(monkeypatch):
    risk.reset_halts(reset_peak=True)
    risk._last_order_time.clear()   # ensure no cooldown bleeds from prior tests
    monkeypatch.setattr(config, "DAILY_LOSS_STOP_PCT", 0.02)
    monkeypatch.setattr(config, "ENABLE_CORRELATION_CAP", False)
    monkeypatch.setattr(config, "MAX_SECTOR_EXPOSURE_PCT", 1.0)
    monkeypatch.setattr(config, "ORDER_COOLDOWN_SEC", 0)

    now = risk._now_utc()
    risk.update_daily_loss_guard(_account(100000), now=now)
    state = risk.update_daily_loss_guard(_account(97000), now=now)
    assert state["halted"]

    ok, reason = risk.pre_trade_checks(
        symbol="AAPL",
        price=100.0,
        account=_account(97000),
        positions=[],
        watchlist=["AAPL"],
        atr=1.0,
    )
    assert not ok
    assert "daily loss stop" in reason


def test_sector_exposure_cap(monkeypatch):
    monkeypatch.setattr(config, "MAX_SECTOR_EXPOSURE_PCT", 0.20)

    positions = [
        {
            "symbol": "AAPL",
            "qty": 100,
            "current_price": 190,
            "side": "long",
        }
    ]
    ok, reason = risk.check_sector_exposure(
        symbol="MSFT",
        price=300,
        qty=20,
        positions=positions,
        account=_account(100000),
    )
    assert not ok
    assert "sector cap exceeded" in reason


def test_correlation_cap(monkeypatch):
    monkeypatch.setattr(config, "ENABLE_CORRELATION_CAP", True)
    monkeypatch.setattr(config, "MAX_CORRELATION", 0.8)
    monkeypatch.setattr(config, "MAX_CORRELATED_POSITIONS", 2)

    positions = [
        {"symbol": "AAPL", "qty": 10, "current_price": 200},
        {"symbol": "MSFT", "qty": 10, "current_price": 300},
    ]

    def _fake_fetch(_symbol: str, _days: int) -> list[float]:
        return [float(i) for i in range(1, 200)]

    ok, reason = risk.check_correlation_cap("NVDA", positions, close_fetcher=_fake_fetch)
    assert not ok
    assert "correlation cap exceeded" in reason
