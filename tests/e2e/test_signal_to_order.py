"""
E2E tests — full signal-to-order pipeline with all external calls mocked.

These tests exercise main._process_symbol() end-to-end without hitting
any real broker, LLM, or news API.
"""
from __future__ import annotations

import pytest
from unittest.mock import MagicMock, patch
from datetime import datetime, timezone

import config
import main
import risk
import trade_journal


# ── Shared fixtures ────────────────────────────────────────────────────────────

def _account(equity: float = 100_000.0) -> dict:
    return {
        "equity": equity,
        "cash": equity * 0.5,
        "buying_power": equity,
        "portfolio_value": equity,
    }


def _signal(action: str = "buy", score: int = 5, price: float = 150.0) -> dict:
    return {
        "signal": action,
        "score": score,
        "price": price,
        "reason": "test signal",
        "rsi": 55.0,
        "atr": 2.0,
        "adx": 30.0,
        "regime": "bull_trend",
        "regime_confidence": 0.9,
        "regime_realized_vol": 0.012,
        "regime_trend_strength": 0.015,
        "market_trend": 1,
        "earnings_soon": False,
        "event_score": 0,
        "event_reasons": [],
        "ema_score": 1, "macd_score": 1, "rsi_score": 1,
        "bb_score": 0, "supertrend_score": 1, "vwap_score": 1,
        "breakout_score": 0, "momentum_score": 1, "adx_score": 0,
    }


def _bars(n: int = 60, price: float = 150.0) -> list[dict]:
    from datetime import timedelta
    start = datetime(2026, 1, 1, tzinfo=timezone.utc)
    return [
        {
            "t": (start + timedelta(days=i)).isoformat(),
            "o": price * 0.998, "h": price * 1.005,
            "l": price * 0.995, "c": price, "v": 1_000_000,
        }
        for i in range(n)
    ]


@pytest.fixture(autouse=True)
def reset_state():
    """Reset all module-level state before each test."""
    main._curated_blacklist.clear()
    main._peak_prices.clear()
    main._partial_done.clear()
    main._position_stops.clear()
    main._exit_holds.clear()
    risk.reset_halts(reset_peak=True)
    risk._manager.last_order_time.clear()   # prevent cooldown bleed between tests
    yield


@pytest.fixture(autouse=True)
def tmp_journal(tmp_path, monkeypatch):
    monkeypatch.setattr(trade_journal, "_JOURNAL_FILE", str(tmp_path / "journal.json"))


# ── Helpers: patch context managers ───────────────────────────────────────────

def _mock_env(monkeypatch, *, signal=None, bars=None, positions=None, account=None):
    """Patch broker + strategy so _process_symbol is fully offline."""
    sig = signal or _signal()
    monkeypatch.setattr(config, "USE_AGENT", False)
    monkeypatch.setattr(config, "MULTI_TIMEFRAME_ENABLED", False)
    monkeypatch.setattr(config, "PEER_CHECK_ENABLED", False)
    monkeypatch.setattr(config, "PREMARKET_CURATION_ENABLED", False)
    monkeypatch.setattr(config, "GAP_FILTER_PCT", 0.0)
    monkeypatch.setattr(config, "MARKET_OPEN_BUFFER_MIN", 0)
    monkeypatch.setattr(config, "MARKET_CLOSE_BUFFER_MIN", 0)
    monkeypatch.setattr(config, "DRY_RUN", True)
    monkeypatch.setattr(config, "SHADOW_MODE", False)
    monkeypatch.setattr(config, "SIGNAL_THRESHOLD", 3)

    import broker, strategy, events
    monkeypatch.setattr(broker, "get_account", lambda: account or _account())
    monkeypatch.setattr(broker, "get_positions", lambda: positions or [])
    monkeypatch.setattr(broker, "get_bars", lambda *a, **kw: bars or _bars())
    monkeypatch.setattr(strategy, "compute_signals", lambda *a, **kw: sig)
    monkeypatch.setattr(events, "is_earnings_period", lambda *a, **kw: False)
    monkeypatch.setattr(events, "fetch_news", lambda **kw: [])
    monkeypatch.setattr(events, "sentiment_trend", lambda *a: 0)
    monkeypatch.setattr(events, "is_high_impact_macro_day", lambda: False)


# ── Tests ──────────────────────────────────────────────────────────────────────

@pytest.mark.e2e
def test_buy_signal_logged_dry_run(monkeypatch, capsys):
    """A BUY signal in DRY_RUN mode logs the order instead of executing."""
    _mock_env(monkeypatch, signal=_signal("buy", score=5))
    main._process_symbol("AAPL", ["AAPL"], market_trend=1)
    # DRY_RUN should log but not crash


@pytest.mark.e2e
def test_hold_signal_no_action(monkeypatch):
    """HOLD signal → no order placed, no journal entry."""
    _mock_env(monkeypatch, signal=_signal("hold", score=1))
    main._process_symbol("AAPL", ["AAPL"], market_trend=0)
    stats = trade_journal.get_stats()
    assert stats["total_decisions"] == 0


@pytest.mark.e2e
def test_earnings_suppresses_buy(monkeypatch):
    """If earnings are imminent, buy should be suppressed."""
    _mock_env(monkeypatch, signal=_signal("buy", score=6))
    import events
    monkeypatch.setattr(events, "is_earnings_period", lambda *a, **kw: True)
    # earnings_soon=True is passed to compute_signals; strategy returns hold
    import strategy
    def _hold_on_earnings(bars, market_trend=0, earnings_soon=False, threshold=None, timeframe=None):
        s = _signal("hold" if earnings_soon else "buy", score=6)
        s["earnings_soon"] = earnings_soon
        return s
    monkeypatch.setattr(strategy, "compute_signals", _hold_on_earnings)
    main._process_symbol("AAPL", ["AAPL"], market_trend=1)
    # No approved buy decision should be in journal
    stats = trade_journal.get_stats()
    assert stats["approved"] == 0


@pytest.mark.e2e
def test_blacklisted_symbol_skipped(monkeypatch):
    """Symbol in _curated_blacklist is skipped entirely."""
    _mock_env(monkeypatch, signal=_signal("buy", score=6))
    main._curated_blacklist.add("TSLA")
    order_placed = []
    import broker
    monkeypatch.setattr(broker, "place_market_order", lambda *a, **kw: order_placed.append(1) or {})
    main._process_symbol("TSLA", ["TSLA"], market_trend=1)
    assert len(order_placed) == 0


@pytest.mark.e2e
def test_time_of_day_blocks_buy(monkeypatch):
    """Opening buffer blocks buy when market just opened."""
    _mock_env(monkeypatch, signal=_signal("buy", score=5))
    monkeypatch.setattr(config, "MARKET_OPEN_BUFFER_MIN", 30)
    monkeypatch.setattr(config, "MARKET_CLOSE_BUFFER_MIN", 0)
    monkeypatch.setattr(config, "GAP_FILTER_PCT", 0.0)

    # Patch check_time_of_day to simulate being in the opening buffer
    import risk as risk_mod
    monkeypatch.setattr(risk_mod, "check_time_of_day", lambda: (False, "opening buffer active (15min remaining)"))
    main._process_symbol("AAPL", ["AAPL"], market_trend=1)
    stats = trade_journal.get_stats()
    assert stats["approved"] == 0


@pytest.mark.e2e
def test_gap_filter_blocks_buy(monkeypatch):
    """Gap filter blocks entry when stock gapped up > threshold."""
    _mock_env(monkeypatch, signal=_signal("buy", score=5))
    monkeypatch.setattr(config, "GAP_FILTER_PCT", 0.03)

    gapped_bars = _bars()
    gapped_bars[-1]["o"] = gapped_bars[-2]["c"] * 1.05   # 5% gap-up

    import broker
    monkeypatch.setattr(broker, "get_bars", lambda *a, **kw: gapped_bars)
    main._process_symbol("AAPL", ["AAPL"], market_trend=1)
    stats = trade_journal.get_stats()
    assert stats["approved"] == 0


@pytest.mark.e2e
def test_agent_approve_triggers_buy(monkeypatch):
    """When agent approves, a BUY order is placed and decision logged."""
    _mock_env(monkeypatch, signal=_signal("buy", score=5))
    # Use live order path (not dry run) so log_decision is reached
    monkeypatch.setattr(config, "DRY_RUN", False)
    monkeypatch.setattr(config, "USE_AGENT", True)
    monkeypatch.setattr(config, "AGENT_PROVIDER", "openai")

    import broker, alerts
    monkeypatch.setattr(broker, "place_market_order", lambda *a, **kw: {"id": "order-123"})
    monkeypatch.setattr(alerts, "order_alert", lambda *a, **kw: None)
    monkeypatch.setattr(alerts, "signal_alert", lambda *a, **kw: None)

    import agent
    monkeypatch.setattr(agent, "evaluate_signal", lambda sym, sig, use_cache=True: {
        "approved": True,
        "reason": "strong momentum confirmed by news",
        "size_multiplier": 1.2,
        "suggested_stop_pct": 0.07,
    })
    main._process_symbol("AAPL", ["AAPL"], market_trend=1)
    stats = trade_journal.get_stats()
    assert stats["approved"] == 1


@pytest.mark.e2e
def test_agent_reject_blocks_buy(monkeypatch):
    """When agent rejects, the trade is logged as rejected and no order placed."""
    _mock_env(monkeypatch, signal=_signal("buy", score=5))
    monkeypatch.setattr(config, "USE_AGENT", True)
    monkeypatch.setattr(config, "AGENT_PROVIDER", "openai")

    import agent
    monkeypatch.setattr(agent, "evaluate_signal", lambda sym, sig, use_cache=True: {
        "approved": False,
        "reason": "breaking negative catalyst: CEO resigned",
        "size_multiplier": 1.0,
        "suggested_stop_pct": None,
    })
    main._process_symbol("AAPL", ["AAPL"], market_trend=1)
    stats = trade_journal.get_stats()
    assert stats["rejected"] == 1
    assert stats["approved"] == 0


@pytest.mark.e2e
def test_sl_tp_log_outcome(monkeypatch, tmp_path):
    """Trailing stop hit → log_outcome is written with negative PnL."""
    _mock_env(monkeypatch, signal=_signal("hold", score=1))
    monkeypatch.setattr(config, "STOP_LOSS_PCT", 0.05)
    monkeypatch.setattr(config, "TAKE_PROFIT_PCT", 0.10)
    monkeypatch.setattr(config, "EXIT_REVIEW_ENABLED", False)
    monkeypatch.setattr(config, "DRY_RUN", False)

    import broker
    closed = []
    monkeypatch.setattr(broker, "close_position", lambda sym: closed.append(sym) or {"order_id": "x"})

    import alerts
    monkeypatch.setattr(alerts, "order_alert", lambda *a, **kw: None)

    # Simulate position where trailing stop is hit
    position = {
        "symbol": "AAPL",
        "qty": 10,
        "side": "long",
        "avg_entry": 150.0,
        "current_price": 140.0,   # dropped well below 5% stop from entry
        "unrealized_pnl": -100.0,
        "unrealized_pnl_pct": -0.067,
    }
    main._peak_prices["AAPL"] = 150.0   # peak = entry, so stop = 150 * 0.95 = 142.5 > 140 → hit

    result = main._check_sl_tp(position)
    assert result is True
    assert "AAPL" in closed
    stats = trade_journal.get_stats()
    assert stats["total_outcomes"] == 1
    assert stats["losses"] == 1
