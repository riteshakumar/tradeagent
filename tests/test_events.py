"""Unit tests for events.py — keyword sentiment and macro day detection."""
from __future__ import annotations

from unittest.mock import patch

import config
import events


def _make_news(*headlines: str) -> list[dict]:
    return [{"headline": h, "summary": "", "source": "", "created": "", "symbols": []} for h in headlines]


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
