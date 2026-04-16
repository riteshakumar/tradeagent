import logging
import time
from datetime import date, datetime, timezone
from typing import Callable

import config

log = logging.getLogger(__name__)

_peak_equity: float = 0.0
_drawdown_halted: bool = False
_last_order_time: dict[str, float] = {}  # symbol -> epoch time of last order

_daily_anchor_date: date | None = None
_daily_anchor_equity: float = 0.0
_daily_loss_halted: bool = False
_daily_loss_pct: float = 0.0

_DEFAULT_SYMBOL_SECTORS = {
    "AAPL": "technology",
    "MSFT": "technology",
    "NVDA": "technology",
    "TSLA": "consumer_discretionary",
    "AMZN": "consumer_discretionary",
    "META": "technology",
    "GOOGL": "communication_services",
    "JPM": "financials",
    "BAC": "financials",
    "GS": "financials",
    "XLF": "financials",
    "XLE": "energy",
    "CVX": "energy",
    "XOM": "energy",
    "USO": "energy",
    "XLK": "technology",
    "QQQ": "technology",
    "SPY": "broad_market",
    "DIA": "broad_market",
    "IWM": "broad_market",
    "VTI": "broad_market",
    "TLT": "fixed_income",
    "AGG": "fixed_income",
    "IEF": "fixed_income",
    "VNQ": "real_estate",
    "XLRE": "real_estate",
    "ARKK": "technology",
    "SOXX": "technology",
}


def _now_utc() -> datetime:
    return datetime.now(timezone.utc)


def _market_notional(position: dict) -> float:
    qty = float(position.get("qty", 0))
    price = float(position.get("current_price", 0))
    if "market_value" in position:
        try:
            return abs(float(position["market_value"]))
        except (TypeError, ValueError):
            pass
    return abs(qty * price)


def resolve_sector(symbol: str) -> str:
    sym = symbol.upper()
    if sym in config.SYMBOL_SECTORS:
        return config.SYMBOL_SECTORS[sym]
    return _DEFAULT_SYMBOL_SECTORS.get(sym, "unknown")


def compute_qty(
    price: float,
    account: dict,
    atr: float | None = None,
    realized_vol: float | None = None,
) -> float:
    """
    Volatility-adjusted position sizing.

    Priority:
    1. Vol-targeting (if realized_vol provided): size so each position contributes
       equal annualized dollar volatility → TSLA gets smaller positions than MSFT.
       Formula: qty = (portfolio × RISK_PCT) / (price × annual_vol)
    2. ATR-based (fallback if atr provided): qty = risk_dollars / (1.5 × ATR)
    3. Fixed-fraction (last resort): qty = max_dollars / price

    All methods are capped by MAX_POSITION_PCT of portfolio value.
    """
    portfolio    = float(account["portfolio_value"])
    max_dollars  = portfolio * config.MAX_POSITION_PCT
    risk_dollars = portfolio * config.RISK_PER_TRADE_PCT

    if price <= 0:
        return 1.0

    qty: float

    if realized_vol and realized_vol > 0:
        # Annualise daily vol: annual_vol = daily_vol × sqrt(252)
        annual_vol = realized_vol * (252 ** 0.5)
        dollar_vol_per_share = price * annual_vol
        if dollar_vol_per_share > 0:
            vol_qty = risk_dollars / dollar_vol_per_share
            qty = min(vol_qty, max_dollars / price)
        else:
            qty = max_dollars / price

    elif atr and atr > 0:
        stop_dist = 1.5 * atr
        atr_qty   = risk_dollars / stop_dist if stop_dist > 0 else 0
        qty = min(atr_qty, max_dollars / price)

    else:
        qty = max_dollars / price

    return max(1.0, round(qty, 0))


def check_cooldown(symbol: str) -> bool:
    last = _last_order_time.get(symbol, 0)
    elapsed = time.time() - last
    if elapsed < config.ORDER_COOLDOWN_SEC:
        log.warning("%s: cooldown active - %.0fs remaining", symbol, config.ORDER_COOLDOWN_SEC - elapsed)
        return False
    return True


def record_order(symbol: str) -> None:
    _last_order_time[symbol] = time.time()


def evaluate_drawdown(account: dict) -> dict:
    global _peak_equity, _drawdown_halted
    equity = float(account["equity"])
    if _peak_equity <= 0:
        _peak_equity = equity
    if equity > _peak_equity:
        _peak_equity = equity
    drawdown = (_peak_equity - equity) / _peak_equity if _peak_equity > 0 else 0.0

    just_triggered = False
    if not _drawdown_halted and drawdown >= config.MAX_DRAWDOWN_PCT:
        _drawdown_halted = True
        just_triggered = True
    return {
        "peak_equity": _peak_equity,
        "equity": equity,
        "drawdown_pct": drawdown,
        "halted": _drawdown_halted,
        "just_triggered": just_triggered,
    }


def check_drawdown(account: dict) -> bool:
    return evaluate_drawdown(account)["halted"]


def update_daily_loss_guard(account: dict, now: datetime | None = None) -> dict:
    global _daily_anchor_date, _daily_anchor_equity, _daily_loss_halted, _daily_loss_pct
    ts = now or _now_utc()
    today = ts.date()
    equity = float(account["equity"])

    if _daily_anchor_date != today or _daily_anchor_equity <= 0:
        _daily_anchor_date = today
        _daily_anchor_equity = equity
        _daily_loss_halted = False
        _daily_loss_pct = 0.0

    if _daily_anchor_equity > 0:
        _daily_loss_pct = (_daily_anchor_equity - equity) / _daily_anchor_equity
    else:
        _daily_loss_pct = 0.0

    if config.DAILY_LOSS_STOP_PCT > 0 and _daily_loss_pct >= config.DAILY_LOSS_STOP_PCT:
        _daily_loss_halted = True

    return {
        "anchor_date": _daily_anchor_date,
        "anchor_equity": _daily_anchor_equity,
        "daily_loss_pct": _daily_loss_pct,
        "halted": _daily_loss_halted,
    }


def is_daily_loss_halted() -> bool:
    return _daily_loss_halted


def reset_halts(reset_peak: bool = False) -> None:
    global _drawdown_halted, _daily_loss_halted, _daily_anchor_equity, _daily_anchor_date, _daily_loss_pct, _peak_equity
    _drawdown_halted = False
    _daily_loss_halted = False
    _daily_loss_pct = 0.0
    _daily_anchor_equity = 0.0
    _daily_anchor_date = None
    if reset_peak:
        _peak_equity = 0.0


def already_positioned(symbol: str, positions: list[dict]) -> bool:
    return any(p["symbol"].upper() == symbol.upper() for p in positions)


def is_watchlist_allowed(symbol: str, watchlist: list[str]) -> bool:
    allowed = symbol.upper() in [s.upper() for s in watchlist]
    if not allowed:
        log.warning("%s: not in active watchlist - skipping", symbol)
    return allowed


def check_buying_power(price: float, qty: float, account: dict) -> bool:
    cost = price * qty
    has_power = float(account["buying_power"]) >= cost
    if not has_power:
        log.warning("Insufficient buying power: need $%.2f, have $%.2f", cost, account["buying_power"])
    return has_power


def check_position_size(price: float, account: dict) -> bool:
    max_dollars = float(account["portfolio_value"]) * config.MAX_POSITION_PCT
    if price > max_dollars:
        log.warning(
            "Single share price $%.2f exceeds max position size $%.2f - skipping",
            price,
            max_dollars,
        )
        return False
    return True


def check_cash_buffer(account: dict, buffer_pct: float = 0.05) -> bool:
    min_cash = float(account["portfolio_value"]) * buffer_pct
    if float(account["cash"]) < min_cash:
        log.warning("Cash $%.2f below %.0f%% buffer $%.2f - skipping", account["cash"], buffer_pct * 100, min_cash)
        return False
    return True


def check_sector_exposure(symbol: str, price: float, qty: float, positions: list[dict], account: dict) -> tuple[bool, str]:
    if config.MAX_SECTOR_EXPOSURE_PCT <= 0:
        return True, "disabled"

    target_sector = resolve_sector(symbol)
    if target_sector == "unknown":
        return True, "unknown sector"

    current_sector_notional = sum(
        _market_notional(p)
        for p in positions
        if resolve_sector(p["symbol"]) == target_sector
    )
    proposed_notional = current_sector_notional + (price * qty)
    cap_dollars = float(account["portfolio_value"]) * config.MAX_SECTOR_EXPOSURE_PCT
    if proposed_notional > cap_dollars:
        return False, (
            f"sector cap exceeded ({target_sector}: ${proposed_notional:,.0f} > ${cap_dollars:,.0f})"
        )
    return True, "ok"


def _fetch_closes(symbol: str, lookback_days: int) -> list[float]:
    import broker

    bars = broker.get_bars(symbol, timeframe="1Day", lookback_days=lookback_days)
    return [float(b["c"]) for b in bars if "c" in b]


def check_correlation_cap(
    symbol: str,
    positions: list[dict],
    close_fetcher: Callable[[str, int], list[float]] | None = None,
) -> tuple[bool, str]:
    if not config.ENABLE_CORRELATION_CAP:
        return True, "disabled"

    held_symbols = [p["symbol"].upper() for p in positions if p["symbol"].upper() != symbol.upper()]
    if not held_symbols:
        return True, "ok"

    fetch = close_fetcher or _fetch_closes
    target = fetch(symbol, config.CORRELATION_LOOKBACK_DAYS)
    if len(target) < 20:
        return True, "insufficient data"

    import numpy as np

    high_corr_count = 0
    for other in held_symbols:
        other_series = fetch(other, config.CORRELATION_LOOKBACK_DAYS)
        n = min(len(target), len(other_series))
        if n < 20:
            continue
        a = np.array(target[-n:], dtype=float)
        b = np.array(other_series[-n:], dtype=float)
        if np.std(a) == 0 or np.std(b) == 0:
            continue
        corr = float(np.corrcoef(a, b)[0, 1])
        if abs(corr) >= config.MAX_CORRELATION:
            high_corr_count += 1

    if high_corr_count >= config.MAX_CORRELATED_POSITIONS:
        return False, f"correlation cap exceeded ({high_corr_count} highly-correlated holdings)"
    return True, "ok"


def pre_trade_checks(
    symbol: str,
    price: float,
    account: dict,
    positions: list[dict],
    watchlist: list[str] | None = None,
    atr: float | None = None,
    close_fetcher: Callable[[str, int], list[float]] | None = None,
) -> tuple[bool, str]:
    """Run all pre-trade safety checks. Returns (ok, reason)."""
    if watchlist and not is_watchlist_allowed(symbol, watchlist):
        return False, f"{symbol} not in active watchlist"

    if already_positioned(symbol, positions):
        return False, f"already have a position in {symbol}"

    if not check_cooldown(symbol):
        return False, f"cooldown active for {symbol}"

    if not check_position_size(price, account):
        return False, f"share price ${price:,.2f} exceeds max position size"

    drawdown_state = evaluate_drawdown(account)
    if drawdown_state["halted"]:
        return False, f"drawdown halt active ({drawdown_state['drawdown_pct']*100:.2f}%)"

    daily_state = update_daily_loss_guard(account)
    if daily_state["halted"]:
        return False, f"daily loss stop active ({daily_state['daily_loss_pct']*100:.2f}%)"

    qty = compute_qty(price, account, atr=atr)
    if not check_buying_power(price, qty, account):
        return False, f"insufficient buying power (need ${price * qty:,.2f})"

    if not check_cash_buffer(account):
        return False, "cash below 5% reserve buffer"

    ok, reason = check_sector_exposure(symbol, price, qty, positions, account)
    if not ok:
        return False, reason

    ok, reason = check_correlation_cap(symbol, positions, close_fetcher=close_fetcher)
    if not ok:
        return False, reason

    return True, "ok"


def snapshot() -> dict:
    return {
        "peak_equity": _peak_equity,
        "drawdown_halted": _drawdown_halted,
        "daily_anchor_date": str(_daily_anchor_date) if _daily_anchor_date else "",
        "daily_anchor_equity": _daily_anchor_equity,
        "daily_loss_halted": _daily_loss_halted,
        "daily_loss_pct": _daily_loss_pct,
    }
