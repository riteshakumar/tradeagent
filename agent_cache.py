"""
LLM result cache — keyed on (symbol, signal, score).
Entries expire after AGENT_CACHE_TTL_SEC.
"""
import time
import config

_TTL   = int(getattr(config, "AGENT_CACHE_TTL_SEC", 300))
_store: dict[str, tuple[float, dict]] = {}   # key → (ts, result_dict)


def _key(symbol: str, signal: dict) -> str:
    return f"{symbol}:{signal.get('signal')}:{signal.get('score')}"


def get(symbol: str, signal: dict) -> dict | None:
    """Return cached result dict or None if missing/expired."""
    entry = _store.get(_key(symbol, signal))
    if entry and time.time() - entry[0] < _TTL:
        return entry[1]
    return None


def set(symbol: str, signal: dict, result: dict) -> None:
    _store[_key(symbol, signal)] = (time.time(), result)


def clear() -> None:
    _store.clear()
