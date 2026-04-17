"""Unit tests for risk.check_time_of_day and risk.check_gap."""
from __future__ import annotations

from datetime import datetime, timezone, timedelta

import config
import risk


def _et(hour: int, minute: int) -> datetime:
    """Return a UTC datetime that maps to HH:MM Eastern (EST = UTC-5)."""
    return datetime(2026, 1, 15, hour + 5, minute, tzinfo=timezone.utc)


# ── check_time_of_day ──────────────────────────────────────────────────────────

def test_mid_session_ok(monkeypatch):
    monkeypatch.setattr(config, "MARKET_OPEN_BUFFER_MIN", 30)
    monkeypatch.setattr(config, "MARKET_CLOSE_BUFFER_MIN", 30)
    ok, reason = risk.check_time_of_day(now=_et(11, 0))   # 11:00 ET — mid-day
    assert ok


def test_opening_buffer_blocks(monkeypatch):
    monkeypatch.setattr(config, "MARKET_OPEN_BUFFER_MIN", 30)
    monkeypatch.setattr(config, "MARKET_CLOSE_BUFFER_MIN", 30)
    ok, reason = risk.check_time_of_day(now=_et(9, 45))   # 9:45 ET — within 30min of open
    assert not ok
    assert "opening buffer" in reason


def test_closing_buffer_blocks(monkeypatch):
    monkeypatch.setattr(config, "MARKET_OPEN_BUFFER_MIN", 30)
    monkeypatch.setattr(config, "MARKET_CLOSE_BUFFER_MIN", 30)
    ok, reason = risk.check_time_of_day(now=_et(15, 45))  # 3:45 PM ET — within 30min of close
    assert not ok
    assert "closing buffer" in reason


def test_exactly_at_open_cutoff_ok(monkeypatch):
    monkeypatch.setattr(config, "MARKET_OPEN_BUFFER_MIN", 30)
    monkeypatch.setattr(config, "MARKET_CLOSE_BUFFER_MIN", 30)
    ok, _ = risk.check_time_of_day(now=_et(10, 1))   # just past 10:00 ET cutoff
    assert ok


def test_disabled_when_both_zero(monkeypatch):
    monkeypatch.setattr(config, "MARKET_OPEN_BUFFER_MIN", 0)
    monkeypatch.setattr(config, "MARKET_CLOSE_BUFFER_MIN", 0)
    ok, reason = risk.check_time_of_day(now=_et(9, 31))
    assert ok
    assert "disabled" in reason


# ── check_gap ─────────────────────────────────────────────────────────────────

def _bars(prev_close: float, curr_open: float) -> list[dict]:
    return [
        {"t": "2026-01-14", "o": prev_close, "h": prev_close, "l": prev_close, "c": prev_close, "v": 1_000_000},
        {"t": "2026-01-15", "o": curr_open,  "h": curr_open,  "l": curr_open,  "c": curr_open,  "v": 1_000_000},
    ]


def test_no_gap_ok(monkeypatch):
    monkeypatch.setattr(config, "GAP_FILTER_PCT", 0.03)
    ok, _ = risk.check_gap(_bars(100.0, 101.0))   # 1% gap — below 3% threshold
    assert ok


def test_gap_up_blocked(monkeypatch):
    monkeypatch.setattr(config, "GAP_FILTER_PCT", 0.03)
    ok, reason = risk.check_gap(_bars(100.0, 104.5))   # 4.5% gap-up
    assert not ok
    assert "gap-up" in reason


def test_gap_down_blocked(monkeypatch):
    monkeypatch.setattr(config, "GAP_FILTER_PCT", 0.03)
    ok, reason = risk.check_gap(_bars(100.0, 96.0))   # 4% gap-down
    assert not ok
    assert "gap-down" in reason


def test_gap_disabled_when_zero(monkeypatch):
    monkeypatch.setattr(config, "GAP_FILTER_PCT", 0.0)
    ok, reason = risk.check_gap(_bars(100.0, 110.0))   # 10% gap — filter disabled
    assert ok


def test_gap_insufficient_bars(monkeypatch):
    monkeypatch.setattr(config, "GAP_FILTER_PCT", 0.03)
    ok, _ = risk.check_gap([{"c": 100.0, "o": 105.0}])   # only 1 bar
    assert ok   # fail-open


def test_gap_custom_threshold():
    ok, reason = risk.check_gap(_bars(100.0, 106.0), max_gap_pct=0.05)
    assert not ok
    ok2, _ = risk.check_gap(_bars(100.0, 103.0), max_gap_pct=0.05)
    assert ok2
