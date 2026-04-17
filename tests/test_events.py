"""Unit tests for events.py — keyword sentiment and macro day detection."""
from __future__ import annotations

from datetime import date
from unittest.mock import patch

import config
import events


def _make_news(*headlines: str, created: str = "") -> list[dict]:
    return [{"headline": h, "summary": "", "source": "", "created": created, "symbols": []} for h in headlines]


# ── sentiment_trend ────────────────────────────────────────────────────────────

def test_sentiment_trend_positive():
    with patch.object(events, "fetch_news", return_value=_make_news(
        "AAPL beats earnings estimates with record revenue",
        "Apple upgraded to outperform by analyst",
        "Stock surges on strong quarterly results",
    )):
        assert events.sentiment_trend("AAPL") == 1


def test_sentiment_trend_negative():
    with patch.object(events, "fetch_news", return_value=_make_news(
        "CEO resigns amid fraud investigation",
        "Company misses earnings, cuts guidance",
        "Analyst downgrades to underperform on losses",
    )):
        assert events.sentiment_trend("XYZ") == -1


def test_sentiment_trend_neutral():
    with patch.object(events, "fetch_news", return_value=_make_news(
        "Company reports quarterly results",
        "Stock moves sideways amid market uncertainty",
    )):
        assert events.sentiment_trend("AAPL") == 0


def test_sentiment_trend_neutral_on_empty():
    with patch.object(events, "fetch_news", return_value=[]):
        assert events.sentiment_trend("AAPL") == 0


def test_sentiment_trend_returns_zero_on_api_error():
    with patch.object(events, "fetch_news", side_effect=Exception("network error")):
        assert events.sentiment_trend("AAPL") == 0


# ── is_high_impact_macro_day ───────────────────────────────────────────────────

def test_macro_day_detected_fomc(monkeypatch):
    monkeypatch.setattr(config, "MACRO_SUPPRESSION_ENABLED", True)
    with patch.object(events, "fetch_news", return_value=_make_news(
        "Federal Reserve FOMC decision: rates held steady",
    )):
        assert events.is_high_impact_macro_day() is True


def test_macro_day_detected_cpi(monkeypatch):
    monkeypatch.setattr(config, "MACRO_SUPPRESSION_ENABLED", True)
    with patch.object(events, "fetch_news", return_value=_make_news(
        "Consumer price index CPI report shows inflation at 3.2%",
    )):
        assert events.is_high_impact_macro_day() is True


def test_macro_day_not_detected_on_normal_news(monkeypatch):
    monkeypatch.setattr(config, "MACRO_SUPPRESSION_ENABLED", True)
    with patch.object(events, "fetch_news", return_value=_make_news(
        "Apple unveils new iPhone model",
        "Tech sector rallies on chip demand",
    )):
        assert events.is_high_impact_macro_day() is False


def test_macro_day_disabled_by_config(monkeypatch):
    monkeypatch.setattr(config, "MACRO_SUPPRESSION_ENABLED", False)
    # Even with FOMC headline, should return False when disabled
    with patch.object(events, "fetch_news", return_value=_make_news(
        "FOMC rate decision today",
    )):
        assert events.is_high_impact_macro_day() is False


def test_macro_day_recurring_pattern_extends_calendar(monkeypatch):
    monkeypatch.setattr(config, "MACRO_SUPPRESSION_ENABLED", True)
    assert events.is_high_impact_macro_day_for_date(date(2027, 1, 1), news=[]) is True


# ── is_earnings_period ─────────────────────────────────────────────────────────

def test_earnings_period_upcoming():
    with patch.object(events, "fetch_news", return_value=_make_news(
        "AAPL reports earnings on Thursday — analysts expect beat",
    )):
        assert events.is_earnings_period("AAPL") is True


def test_earnings_period_false_on_normal_news():
    with patch.object(events, "fetch_news", return_value=_make_news(
        "Apple launches new MacBook Pro lineup",
    )):
        assert events.is_earnings_period("AAPL") is False


def test_earnings_period_false_on_api_error():
    with patch.object(events, "fetch_news", side_effect=Exception("timeout")):
        assert events.is_earnings_period("AAPL") is False


def test_is_earnings_period_from_news_respects_as_of_window():
    news = _make_news(
        "AAPL reports earnings on Thursday - analysts expect a beat",
        created="2026-01-01T12:00:00Z",
    )

    assert events.is_earnings_period_from_news(news, as_of="2026-01-05T12:00:00Z", pre_days=5) is True
    assert events.is_earnings_period_from_news(news, as_of="2026-01-10T12:00:00Z", pre_days=5) is False


def test_get_historical_event_score_ignores_future_headlines():
    news = [
        {
            "headline": "AAPL misses earnings and cuts guidance",
            "summary": "",
            "source": "",
            "created": "2026-01-05T12:00:00Z",
            "symbols": ["AAPL"],
        },
        {
            "headline": "AAPL beats earnings and raises guidance",
            "summary": "",
            "source": "",
            "created": "2026-01-07T12:00:00Z",
            "symbols": ["AAPL"],
        },
    ]

    past_only = events.get_historical_event_score(
        "AAPL",
        news,
        as_of="2026-01-06T12:00:00Z",
        run_earnings=True,
        run_geo=False,
        run_macro=False,
    )

    assert past_only["event_score"] < 0
    assert any("earnings" in reason for reason in past_only["event_reasons"])
