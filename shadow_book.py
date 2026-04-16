"""Shadow mode ledger: tracks hypothetical trades and outcomes."""
from __future__ import annotations

import json
import os
from datetime import datetime, timezone
from tempfile import NamedTemporaryFile

_PATH = os.path.join(os.path.dirname(__file__), "shadow_book.json")


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _default_state() -> dict:
    return {"positions": [], "trades": [], "intents": []}


def _atomic_write(path: str, payload: dict) -> None:
    with NamedTemporaryFile("w", delete=False, dir=os.path.dirname(path), encoding="utf-8") as tmp:
        json.dump(payload, tmp, indent=2)
        tmp_path = tmp.name
    os.replace(tmp_path, path)


def _load() -> dict:
    if not os.path.exists(_PATH):
        return _default_state()
    try:
        with open(_PATH, encoding="utf-8") as f:
            payload = json.load(f)
        if not isinstance(payload, dict):
            return _default_state()
        payload.setdefault("positions", [])
        payload.setdefault("trades", [])
        payload.setdefault("intents", [])
        return payload
    except Exception:
        return _default_state()


def _save(state: dict) -> None:
    _atomic_write(_PATH, state)


def record_intent(symbol: str, action: str, qty: float, price: float, reason: str, score: int) -> None:
    state = _load()
    state["intents"].append(
        {
            "time": _utc_now(),
            "symbol": symbol.upper(),
            "action": action.lower(),
            "qty": float(qty),
            "price": float(price),
            "score": int(score),
            "reason": reason,
        }
    )
    _save(state)


def get_position(symbol: str) -> dict | None:
    sym = symbol.upper()
    for p in _load()["positions"]:
        if p.get("symbol", "").upper() == sym:
            return p
    return None


def open_position(symbol: str, side: str, qty: float, price: float, reason: str, score: int) -> dict:
    sym = symbol.upper()
    side_norm = side.lower()
    if side_norm not in {"long", "short"}:
        raise ValueError("side must be long or short")

    state = _load()
    existing = None
    for p in state["positions"]:
        if p.get("symbol", "").upper() == sym:
            existing = p
            break

    if existing:
        if existing["side"] != side_norm:
            raise ValueError(f"existing {existing['side']} position for {sym}")
        total_qty = float(existing["qty"]) + float(qty)
        if total_qty <= 0:
            raise ValueError("resulting quantity must be positive")
        avg = ((float(existing["entry_price"]) * float(existing["qty"])) + (float(price) * float(qty))) / total_qty
        existing["qty"] = total_qty
        existing["entry_price"] = round(avg, 6)
        existing["updated_at"] = _utc_now()
        existing["last_reason"] = reason
        existing["last_score"] = int(score)
        _save(state)
        return existing

    position = {
        "symbol": sym,
        "side": side_norm,
        "qty": float(qty),
        "entry_price": float(price),
        "entry_time": _utc_now(),
        "updated_at": _utc_now(),
        "last_reason": reason,
        "last_score": int(score),
        "last_price": float(price),
    }
    state["positions"].append(position)
    _save(state)
    return position


def update_mark(symbol: str, price: float) -> None:
    state = _load()
    updated = False
    for p in state["positions"]:
        if p.get("symbol", "").upper() == symbol.upper():
            p["last_price"] = float(price)
            p["updated_at"] = _utc_now()
            updated = True
    if updated:
        _save(state)


def close_position(symbol: str, price: float, reason: str = "") -> dict | None:
    sym = symbol.upper()
    state = _load()
    idx = None
    pos = None
    for i, p in enumerate(state["positions"]):
        if p.get("symbol", "").upper() == sym:
            idx = i
            pos = p
            break
    if pos is None or idx is None:
        return None

    qty = float(pos["qty"])
    entry = float(pos["entry_price"])
    exit_px = float(price)
    if pos["side"] == "long":
        pnl = (exit_px - entry) * qty
    else:
        pnl = (entry - exit_px) * qty
    pnl_pct = (pnl / (entry * qty)) * 100 if qty > 0 and entry > 0 else 0.0

    trade = {
        "symbol": sym,
        "side": pos["side"],
        "qty": qty,
        "entry_price": entry,
        "exit_price": exit_px,
        "entry_time": pos["entry_time"],
        "exit_time": _utc_now(),
        "pnl": round(pnl, 4),
        "pnl_pct": round(pnl_pct, 4),
        "close_reason": reason or pos.get("last_reason", ""),
    }
    state["trades"].append(trade)
    state["positions"].pop(idx)
    _save(state)
    return trade


def summary() -> dict:
    state = _load()
    open_positions = state["positions"]
    closed = state["trades"]
    realized = sum(float(t.get("pnl", 0)) for t in closed)
    wins = sum(1 for t in closed if float(t.get("pnl", 0)) > 0)
    losses = sum(1 for t in closed if float(t.get("pnl", 0)) <= 0)
    win_rate = (wins / len(closed) * 100.0) if closed else 0.0

    return {
        "open_positions": open_positions,
        "closed_trades": closed[-200:],
        "intents": state["intents"][-500:],
        "realized_pnl": round(realized, 4),
        "wins": wins,
        "losses": losses,
        "win_rate_pct": round(win_rate, 2),
    }


def clear() -> None:
    _save(_default_state())
