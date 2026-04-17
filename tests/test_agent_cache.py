"""Unit tests for agent_cache.py."""
from __future__ import annotations

import time

import agent_cache


def _sig(score: int = 3) -> dict:
    return {"signal": "buy", "score": score, "price": 100.0}


def _result(approved: bool = True) -> dict:
    return {"approved": approved, "reason": "test", "size_multiplier": 1.0, "suggested_stop_pct": None}


def test_cache_miss_on_empty():
    agent_cache._store.clear()
    assert agent_cache.get("AAPL", _sig()) is None


def test_cache_hit_after_set():
    agent_cache._store.clear()
    agent_cache.set("AAPL", _sig(), _result(True))
    cached = agent_cache.get("AAPL", _sig())
    assert cached is not None
    assert cached["approved"] is True


def test_cache_miss_different_symbol():
    agent_cache._store.clear()
    agent_cache.set("AAPL", _sig(), _result(True))
    assert agent_cache.get("MSFT", _sig()) is None


def test_cache_miss_different_score():
    agent_cache._store.clear()
    agent_cache.set("AAPL", _sig(score=3), _result(True))
    # Different score → different cache key
    assert agent_cache.get("AAPL", _sig(score=5)) is None


def test_cache_expiry(monkeypatch):
    # _TTL is a module-level constant — patch it directly on agent_cache
    monkeypatch.setattr(agent_cache, "_TTL", 1)
    agent_cache._store.clear()
    agent_cache.set("AAPL", _sig(), _result(True))
    # Should hit immediately
    assert agent_cache.get("AAPL", _sig()) is not None
    # Expire by winding back the stored timestamp beyond TTL
    key = next(iter(agent_cache._store))
    ts, val = agent_cache._store[key]
    agent_cache._store[key] = (ts - 10, val)   # 10s ago > 1s TTL
    assert agent_cache.get("AAPL", _sig()) is None


def test_cache_stores_reject():
    agent_cache._store.clear()
    agent_cache.set("TSLA", _sig(), _result(False))
    cached = agent_cache.get("TSLA", _sig())
    assert cached is not None
    assert cached["approved"] is False
    assert cached["size_multiplier"] == 1.0
