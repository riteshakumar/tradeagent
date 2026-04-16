"""
LLM result cache — keyed on (symbol, signal, score).
Entries expire after CACHE_TTL_SEC to ensure fresh reasoning each tick cycle.
"""
import time
import config

_TTL = int(getattr(config, "AGENT_CACHE_TTL_SEC", 300))  # default 5 min
_store: dict[str, tuple[float, bool, str]] = {}           # key → (ts, approved, reason)


def _key(symbol: str, signal: dict) -> str:
    return f"{symbol}:{signal.get('signal')}:{signal.get('score')}"


def get(symbol: str, signal: dict) -> tuple[bool, str] | None:
    """Return cached (approved, reason) or None if missing/expired."""
    entry = _store.get(_key(symbol, signal))
    if entry and time.time() - entry[0] < _TTL:
        return entry[1], entry[2]
    return None


def set(symbol: str, signal: dict, approved: bool, reason: str):
    _store[_key(symbol, signal)] = (time.time(), approved, reason)


def clear():
    _store.clear()
