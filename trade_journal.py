"""
Trade journal — logs agent decisions and trade outcomes for confidence calibration.
Append-only JSON, capped at 1000 entries. Read by dashboard for stats.
"""
import json
import logging
import os
from datetime import datetime, timezone

log = logging.getLogger(__name__)
_JOURNAL_FILE = os.path.join(os.path.dirname(__file__), "trade_journal.json")


def _load() -> list[dict]:
    try:
        if os.path.exists(_JOURNAL_FILE):
            with open(_JOURNAL_FILE) as f:
                return json.load(f)
    except Exception:
        pass
    return []


def _save(records: list[dict]) -> None:
    try:
        with open(_JOURNAL_FILE, "w") as f:
            json.dump(records[-1000:], f, indent=2)
    except Exception as exc:
        log.debug("trade_journal write error: %s", exc)


def log_decision(
    symbol: str,
    action: str,
    approved: bool,
    reason: str,
    size_multiplier: float = 1.0,
    score: int = 0,
    sentiment: int = 0,
    macro_day: bool = False,
) -> None:
    records = _load()
    records.append({
        "type": "decision",
        "time": datetime.now(timezone.utc).isoformat(),
        "symbol": symbol,
        "action": action,
        "approved": approved,
        "reason": reason,
        "size_multiplier": size_multiplier,
        "score": score,
        "sentiment": sentiment,
        "macro_day": macro_day,
    })
    _save(records)


def log_outcome(
    symbol: str,
    entry_price: float,
    exit_price: float,
    pnl: float,
    exit_reason: str,
) -> None:
    records = _load()
    records.append({
        "type": "outcome",
        "time": datetime.now(timezone.utc).isoformat(),
        "symbol": symbol,
        "entry_price": entry_price,
        "exit_price": exit_price,
        "pnl": pnl,
        "exit_reason": exit_reason,
    })
    _save(records)


def get_stats() -> dict:
    """Return basic approval and win-rate stats."""
    try:
        records = _load()
        decisions = [r for r in records if r.get("type") == "decision"]
        outcomes  = [r for r in records if r.get("type") == "outcome"]
        total  = len(decisions)
        appr   = sum(1 for d in decisions if d["approved"])
        wins   = sum(1 for o in outcomes if float(o.get("pnl", 0)) > 0)
        losses = sum(1 for o in outcomes if float(o.get("pnl", 0)) <= 0)
        return {
            "total_decisions":  total,
            "approved":         appr,
            "rejected":         total - appr,
            "approval_rate":    round(appr / total, 3) if total else 0,
            "total_outcomes":   len(outcomes),
            "wins":             wins,
            "losses":           losses,
            "win_rate":         round(wins / len(outcomes), 3) if outcomes else 0,
        }
    except Exception:
        return {}
