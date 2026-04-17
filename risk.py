import logging
import time
from datetime import date, datetime, timezone
from typing import Callable

import config

log = logging.getLogger(__name__)

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


class RiskManager:
    """
    Encapsulates all mutable risk state.
    Use the module-level singleton `_manager` via the public wrapper functions below.
    Instantiate a fresh RiskManager() in tests to avoid cross-test contamination.
    """

    def __init__(self) -> None:
        self.peak_equity: float = 0.0
        self.drawdown_halted: bool = False
        self.last_order_time: dict[str, float] = {}

        self.daily_anchor_date: date | None = None
        self.daily_anchor_equity: float = 0.0
        self.daily_loss_halted: bool = False
        self.daily_loss_pct: float = 0.0

    # ------------------------------------------------------------------
    # Drawdown
    # ------------------------------------------------------------------

    def evaluate_drawdown(self, account: dict) -> dict:
        equity = float(account["equity"])
        if self.peak_equity <= 0:
            self.peak_equity = equity
        if equity > self.peak_equity:
            self.peak_equity = equity
        drawdown = (self.peak_equity - equity) / self.peak_equity if self.peak_equity > 0 else 0.0

        just_triggered = False
        if not self.drawdown_halted and drawdown >= config.MAX_DRAWDOWN_PCT:
            self.drawdown_halted = True
            just_triggered = True
        return {
            "peak_equity": self.peak_equity,
            "equity": equity,
            "drawdown_pct": drawdown,
            "halted": self.drawdown_halted,
            "just_triggered": just_triggered,
        }

    # ------------------------------------------------------------------
    # Daily loss guard
    # ------------------------------------------------------------------

    def update_daily_loss_guard(self, account: dict, now: datetime | None = None) -> dict:
        ts = now or datetime.now(timezone.utc)
        today = ts.date()
        equity = float(account["equity"])

        if self.daily_anchor_date != today or self.daily_anchor_equity <= 0:
            self.daily_anchor_date = today
            self.daily_anchor_equity = equity
            self.daily_loss_halted = False
            self.daily_loss_pct = 0.0

        if self.daily_anchor_equity > 0:
            self.daily_loss_pct = (self.daily_anchor_equity - equity) / self.daily_anchor_equity
        else:
            self.daily_loss_pct = 0.0

        if config.DAILY_LOSS_STOP_PCT > 0 and self.daily_loss_pct >= config.DAILY_LOSS_STOP_PCT:
            self.daily_loss_halted = True

        return {
            "anchor_date": self.daily_anchor_date,
            "anchor_equity": self.daily_anchor_equity,
            "daily_loss_pct": self.daily_loss_pct,
            "halted": self.daily_loss_halted,
        }

    # ------------------------------------------------------------------
    # Order cooldown
    # ------------------------------------------------------------------

    def check_cooldown(self, symbol: str) -> bool:
        last = self.last_order_time.get(symbol, 0)
        elapsed = time.time() - last
        if elapsed < config.ORDER_COOLDOWN_SEC:
            log.warning("%s: cooldown active - %.0fs remaining", symbol, config.ORDER_COOLDOWN_SEC - elapsed)
            return False
        return True

    def record_order(self, symbol: str) -> None:
        self.last_order_time[symbol] = time.time()

    # ------------------------------------------------------------------
    # Reset / snapshot
    # ------------------------------------------------------------------

    def reset_halts(self, reset_peak: bool = False) -> None:
        self.drawdown_halted = False
        self.daily_loss_halted = False
        self.daily_loss_pct = 0.0
        self.daily_anchor_equity = 0.0
        self.daily_anchor_date = None
        if reset_peak:
            self.peak_equity = 0.0

    def snapshot(self) -> dict:
        return {
            "peak_equity": self.peak_equity,
            "drawdown_halted": self.drawdown_halted,
            "daily_anchor_date": str(self.daily_anchor_date) if self.daily_anchor_date else "",
            "daily_anchor_equity": self.daily_anchor_equity,
            "daily_loss_halted": self.daily_loss_halted,
            "daily_loss_pct": self.daily_loss_pct,
        }


# Module-level singleton — used by all production code.
# Tests should create their own RiskManager() instances.
_manager = RiskManager()


# ===========================================================================
# Public API — thin wrappers around the singleton.
# All callers use these functions; the class is an implementation detail.
# ===========================================================================

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
    return _manager.check_cooldown(symbol)


def record_order(symbol: str) -> None:
    _manager.record_order(symbol)


def evaluate_drawdown(account: dict) -> dict:
    return _manager.evaluate_drawdown(account)


def check_drawdown(account: dict) -> bool:
    return _manager.evaluate_drawdown(account)["halted"]


def update_daily_loss_guard(account: dict, now: datetime | None = None) -> dict:
    return _manager.update_daily_loss_guard(account, now)


def is_daily_loss_halted() -> bool:
    return _manager.daily_loss_halted


def reset_halts(reset_peak: bool = False) -> None:
    _manager.reset_halts(reset_peak)


def snapshot() -> dict:
    return _manager.snapshot()


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


def check_time_of_day(now: datetime | None = None) -> tuple[bool, str]:
    """
    Block new entries during the first MARKET_OPEN_BUFFER_MIN minutes after
    open and the last MARKET_CLOSE_BUFFER_MIN minutes before close (ET).
    Returns (ok, reason).
    """
    if config.MARKET_OPEN_BUFFER_MIN <= 0 and config.MARKET_CLOSE_BUFFER_MIN <= 0:
        return True, "time filter disabled"
    try:
        from zoneinfo import ZoneInfo
        from datetime import timedelta
        et = ZoneInfo("America/New_York")
        ts = (now or _now_utc()).astimezone(et)
        base = ts.replace(second=0, microsecond=0)
        mkt_open  = base.replace(hour=9,  minute=30)
        mkt_close = base.replace(hour=16, minute=0)
        open_cutoff  = mkt_open  + timedelta(minutes=config.MARKET_OPEN_BUFFER_MIN)
        close_cutoff = mkt_close - timedelta(minutes=config.MARKET_CLOSE_BUFFER_MIN)
        if ts < open_cutoff:
            mins_left = int((open_cutoff - ts).total_seconds() / 60) + 1
            return False, f"opening buffer active ({mins_left}min remaining)"
        if ts > close_cutoff:
            return False, f"closing buffer active (last {config.MARKET_CLOSE_BUFFER_MIN}min of session)"
    except Exception as exc:
        log.warning("time-of-day check error — proceeding without filter: %s", exc)
    return True, "ok"


def check_gap(bars: list[dict], max_gap_pct: float | None = None) -> tuple[bool, str]:
    """
    Block entries when the most recent bar opened with a gap larger than
    max_gap_pct vs the previous close (catches gap-up chasing / gap-down panic).
    Returns (ok, reason).
    """
    threshold = max_gap_pct if max_gap_pct is not None else config.GAP_FILTER_PCT
    if threshold <= 0 or len(bars) < 2:
        return True, "gap filter disabled"
    try:
        prev_close = float(bars[-2]["c"])
        curr_open  = float(bars[-1].get("o", bars[-1]["c"]))
        if prev_close <= 0:
            return True, "invalid prev close"
        gap = (curr_open - prev_close) / prev_close
        if abs(gap) >= threshold:
            direction = "up" if gap > 0 else "down"
            return False, f"gap-{direction} {abs(gap)*100:.1f}% exceeds {threshold*100:.0f}% filter"
    except Exception as exc:
        log.warning("gap check error — proceeding without filter: %s", exc)
    return True, "ok"
