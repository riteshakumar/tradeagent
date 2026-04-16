"""Persist a dynamic watchlist to watchlist.json alongside config.py defaults."""
import json
import os
from tempfile import NamedTemporaryFile

_PATH = os.path.join(os.path.dirname(__file__), "watchlist.json")


def load() -> list[str]:
    if not os.path.exists(_PATH):
        return []
    try:
        with open(_PATH, encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return []


def save(symbols: list[str]):
    payload = sorted(set(s.upper().strip() for s in symbols if s and s.strip()))
    with NamedTemporaryFile("w", delete=False, dir=os.path.dirname(_PATH), encoding="utf-8") as tmp:
        json.dump(payload, tmp, indent=2)
        tmp_path = tmp.name
    os.replace(tmp_path, _PATH)


def add(symbol: str):
    current = load()
    sym = symbol.upper().strip()
    if sym not in current:
        current.append(sym)
        save(current)


def remove(symbol: str):
    current = load()
    sym = symbol.upper().strip()
    save([s for s in current if s != sym])
