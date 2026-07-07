"""
Persistent per-position trading state.

Stores trailing-stop peaks, partial scale-out flags, per-position stop
overrides, and exit-review hold counters in position_state.json so a
process restart mid-position does not:
  - reset trailing-stop high-water marks (stop would trail from a stale peak)
  - forget that a position already scaled out 50% (would scale out twice)
  - drop agent-suggested dynamic stops

Writes are atomic (temp file + os.replace), mirroring settings_store.py.
`sync(open_symbols)` prunes state for symbols no longer held, so stale
entries from crashed sessions or manual closes are cleaned on startup.
"""
from __future__ import annotations

import json
import logging
import os
from tempfile import NamedTemporaryFile

log = logging.getLogger(__name__)

_PATH = os.path.join(os.path.dirname(__file__), "position_state.json")

# Public dicts — main.py aliases these directly. Mutate in place; never rebind.
peak_prices: dict[str, float] = {}
partial_done: dict[str, bool] = {}
position_stops: dict[str, float] = {}
exit_holds: dict[str, int] = {}

_SECTIONS = {
    "peak_prices": peak_prices,
    "partial_done": partial_done,
    "position_stops": position_stops,
    "exit_holds": exit_holds,
}


def load() -> None:
    """Load persisted state from disk (no-op if file missing/corrupt)."""
    if not os.path.exists(_PATH):
        return
    try:
        with open(_PATH, encoding="utf-8") as f:
            payload = json.load(f)
    except Exception as exc:
        log.warning("position_state: failed to load %s (%s) — starting fresh", _PATH, exc)
        return
    if not isinstance(payload, dict):
        return
    for name, target in _SECTIONS.items():
        section = payload.get(name)
        if isinstance(section, dict):
            target.clear()
            target.update(section)


def save() -> None:
    """Atomically persist current state. Failures are logged, never raised."""
    try:
        payload = {name: dict(d) for name, d in _SECTIONS.items()}
        with NamedTemporaryFile("w", delete=False, dir=os.path.dirname(_PATH), encoding="utf-8") as tmp:
            json.dump(payload, tmp, indent=2)
            tmp_path = tmp.name
        os.replace(tmp_path, _PATH)
    except Exception as exc:
        log.error("position_state: save failed — %s", exc)


def clear_symbol(symbol: str) -> None:
    """Drop all state for a symbol (call when its position is closed) and persist."""
    removed = False
    for d in _SECTIONS.values():
        if d.pop(symbol, None) is not None:
            removed = True
    if removed:
        save()


def sync(open_symbols: set[str] | list[str]) -> None:
    """Prune state for symbols no longer held, then persist if anything changed."""
    held = set(open_symbols)
    stale = {s for d in _SECTIONS.values() for s in d if s not in held}
    if not stale:
        return
    log.info("position_state: pruning stale symbols %s", sorted(stale))
    for d in _SECTIONS.values():
        for s in stale:
            d.pop(s, None)
    save()


def clear_all() -> None:
    """Wipe all state (used by tests)."""
    for d in _SECTIONS.values():
        d.clear()


# Load persisted state at import so main.py aliases see it immediately.
load()
