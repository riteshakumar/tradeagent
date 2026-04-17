"""
LLM result cache — keyed on (symbol, full-signal-hash).
Entries expire after AGENT_CACHE_TTL_SEC.
"""
import hashlib
import json
import time
import config

_TTL   = int(getattr(config, "AGENT_CACHE_TTL_SEC", 300))
_store: dict[str, tuple[float, dict]] = {}   # key → (ts, result_dict)


def _key(symbol: str, signal: dict) -> str:
    # Hash the full signal dict so different signals never collide on same score
    payload = json.dumps(signal, sort_keys=True, default=str)
    h = hashlib.md5(payload.encode()).hexdigest()
    return f"{symbol}:{h}"


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
