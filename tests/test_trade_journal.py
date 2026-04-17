"""Unit tests for trade_journal.py."""
from __future__ import annotations

import json
import os
import tempfile

import pytest

import trade_journal


@pytest.fixture(autouse=True)
def tmp_journal(tmp_path, monkeypatch):
    """Redirect journal writes to a temp file for every test."""
    journal_file = str(tmp_path / "test_journal.json")
    monkeypatch.setattr(trade_journal, "_JOURNAL_FILE", journal_file)
    yield journal_file


# ── log_decision ───────────────────────────────────────────────────────────────

def test_log_decision_approve(tmp_journal):
    trade_journal.log_decision("AAPL", "buy", True, "strong momentum", score=5, sentiment=1)
    records = json.loads(open(tmp_journal).read())
    assert len(records) == 1
    r = records[0]
    assert r["type"] == "decision"
    assert r["symbol"] == "AAPL"
    assert r["approved"] is True
    assert r["score"] == 5
    assert r["sentiment"] == 1


def test_log_decision_reject(tmp_journal):
    trade_journal.log_decision("TSLA", "buy", False, "negative news", score=2, macro_day=True)
    records = json.loads(open(tmp_journal).read())
    assert records[0]["approved"] is False
    assert records[0]["macro_day"] is True


def test_log_decision_multiple_appends(tmp_journal):
    trade_journal.log_decision("AAPL", "buy", True, "r1")
    trade_journal.log_decision("MSFT", "buy", False, "r2")
    records = json.loads(open(tmp_journal).read())
    assert len(records) == 2
    assert records[0]["symbol"] == "AAPL"
    assert records[1]["symbol"] == "MSFT"


# ── log_outcome ────────────────────────────────────────────────────────────────

def test_log_outcome_win(tmp_journal):
    trade_journal.log_outcome("NVDA", 100.0, 115.0, 150.0, "take_profit")
    records = json.loads(open(tmp_journal).read())
    assert records[0]["type"] == "outcome"
    assert records[0]["pnl"] == 150.0
    assert records[0]["exit_reason"] == "take_profit"


def test_log_outcome_loss(tmp_journal):
    trade_journal.log_outcome("META", 200.0, 185.0, -150.0, "stop_loss")
    records = json.loads(open(tmp_journal).read())
    assert records[0]["pnl"] == -150.0


# ── get_stats ──────────────────────────────────────────────────────────────────

def test_get_stats_empty(tmp_journal):
    stats = trade_journal.get_stats()
    assert stats["total_decisions"] == 0
    assert stats["approval_rate"] == 0
    assert stats["win_rate"] == 0


def test_get_stats_approval_rate(tmp_journal):
    trade_journal.log_decision("A", "buy", True, "ok")
    trade_journal.log_decision("B", "buy", True, "ok")
    trade_journal.log_decision("C", "buy", False, "no")
    stats = trade_journal.get_stats()
    assert stats["total_decisions"] == 3
    assert stats["approved"] == 2
    assert stats["rejected"] == 1
    assert round(stats["approval_rate"], 2) == 0.67


def test_get_stats_win_rate(tmp_journal):
    trade_journal.log_outcome("A", 100, 110, 100, "take_profit")   # win
    trade_journal.log_outcome("B", 100, 95, -50, "stop_loss")      # loss
    trade_journal.log_outcome("C", 100, 108, 80, "take_profit")    # win
    stats = trade_journal.get_stats()
    assert stats["wins"] == 2
    assert stats["losses"] == 1
    assert round(stats["win_rate"], 2) == 0.67


def test_journal_capped_at_1000(tmp_journal):
    for i in range(1005):
        trade_journal.log_decision(f"SYM{i}", "buy", True, "x")
    records = json.loads(open(tmp_journal).read())
    assert len(records) == 1000
