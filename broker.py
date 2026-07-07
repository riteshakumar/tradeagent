from alpaca.trading.client import TradingClient
from alpaca.trading.requests import MarketOrderRequest
from alpaca.trading.enums import OrderSide, TimeInForce
from alpaca.data.historical import StockHistoricalDataClient, CryptoHistoricalDataClient
from alpaca.data.requests import StockBarsRequest, CryptoBarsRequest
from alpaca.data.timeframe import TimeFrame, TimeFrameUnit
from datetime import datetime, timedelta
import logging
import time

from tenacity import retry, wait_exponential, stop_after_attempt, retry_if_exception

import config

log = logging.getLogger(__name__)

# Clients are constructed lazily so importing this module has no side effects
# (no credentials needed at import time — simplifies tests and CI).
_trading_client: TradingClient | None = None
_data_client: StockHistoricalDataClient | None = None
_crypto_data_client: CryptoHistoricalDataClient | None = None


def _trading_c() -> TradingClient:
    global _trading_client
    if _trading_client is None:
        _trading_client = TradingClient(
            config.ALPACA_API_KEY, config.ALPACA_SECRET_KEY, paper=config.PAPER_TRADING
        )
    return _trading_client


def _data_c() -> StockHistoricalDataClient:
    global _data_client
    if _data_client is None:
        _data_client = StockHistoricalDataClient(config.ALPACA_API_KEY, config.ALPACA_SECRET_KEY)
    return _data_client


def _crypto_data_c() -> CryptoHistoricalDataClient:
    global _crypto_data_client
    if _crypto_data_client is None:
        _crypto_data_client = CryptoHistoricalDataClient(config.ALPACA_API_KEY, config.ALPACA_SECRET_KEY)
    return _crypto_data_client


def is_crypto(symbol: str) -> bool:
    return "/" in symbol

# Map config string → (TimeFrame, lookback timedelta)
_TIMEFRAME_MAP = {
    "1Min":  (TimeFrame(1,  TimeFrameUnit.Minute), timedelta(days=2)),
    "5Min":  (TimeFrame(5,  TimeFrameUnit.Minute), timedelta(days=5)),
    "15Min": (TimeFrame(15, TimeFrameUnit.Minute), timedelta(days=10)),
    "1Hour": (TimeFrame(1,  TimeFrameUnit.Hour),   timedelta(days=30)),
    "1Day":  (TimeFrame.Day,                        timedelta(days=60)),
}

def _is_transient(exc: BaseException) -> bool:
    """
    Retry only transient failures: network errors, timeouts, rate limits (429),
    and server errors (5xx). Auth failures, bad requests, and other 4xx fail
    fast — retrying misconfiguration just adds 30s of backoff before the same error.
    """
    import requests as _requests

    if isinstance(exc, (_requests.exceptions.ConnectionError, _requests.exceptions.Timeout)):
        return True
    try:
        from alpaca.common.exceptions import APIError as _APIError
    except ImportError:
        return False
    if isinstance(exc, _APIError):
        code = getattr(exc, "status_code", None)
        if code is None:
            return True  # can't classify — assume transient
        try:
            code = int(code)
        except (TypeError, ValueError):
            return True
        return code == 429 or code >= 500
    return False


# Retry config for read-only API calls: 3 attempts, 2–30s exponential backoff,
# transient errors only (see _is_transient).
# NOT applied to place_market_order / close_position (would risk double-fills).
_READ_RETRY = dict(
    wait=wait_exponential(multiplier=1, min=2, max=30),
    stop=stop_after_attempt(3),
    retry=retry_if_exception(_is_transient),
    reraise=True,
)


@retry(**_READ_RETRY)
def get_clock():
    """Return the Alpaca market clock (reuses the shared lazy trading client)."""
    return _trading_c().get_clock()


@retry(**_READ_RETRY)
def get_account() -> dict:
    acc = _trading_c().get_account()
    return {
        "equity": float(acc.equity),
        "cash": float(acc.cash),
        "buying_power": float(acc.buying_power),
        "portfolio_value": float(acc.portfolio_value),
    }


@retry(**_READ_RETRY)
def get_positions() -> list[dict]:
    positions = _trading_c().get_all_positions()
    rows: list[dict] = []
    for p in positions:
        qty = float(p.qty)
        current = float(p.current_price)
        rows.append(
            {
                "symbol": p.symbol,
                "qty": abs(qty),
                "side": "long" if qty >= 0 else "short",
                "avg_entry": float(p.avg_entry_price),
                "current_price": current,
                "market_value": abs(current * qty),
                "unrealized_pnl": float(p.unrealized_pl),
                "unrealized_pnl_pct": float(p.unrealized_plpc),
            }
        )
    return rows


@retry(**_READ_RETRY)
def get_bars(symbol: str, timeframe: str | None = None, lookback_days: int | None = None) -> list[dict]:
    tf_key = timeframe or config.BAR_TIMEFRAME
    tf, default_lookback = _TIMEFRAME_MAP.get(tf_key, _TIMEFRAME_MAP["5Min"])
    lookback = timedelta(days=lookback_days) if lookback_days else default_lookback
    start = datetime.now() - lookback
    if is_crypto(symbol):
        req = CryptoBarsRequest(symbol_or_symbols=symbol, timeframe=tf, start=start)
        bars = _crypto_data_c().get_crypto_bars(req)[symbol]
    else:
        req = StockBarsRequest(symbol_or_symbols=symbol, timeframe=tf, start=start)
        bars = _data_c().get_stock_bars(req)[symbol]
    return [
        {"t": b.timestamp.isoformat(), "o": b.open, "h": b.high, "l": b.low, "c": b.close, "v": b.volume}
        for b in bars
    ]


def place_market_order(symbol: str, qty: float, side: str) -> dict:
    # No retry — retrying order submission risks double-fills.
    # Crypto markets are 24/7 → use GTC; equities → DAY.
    tif = TimeInForce.GTC if is_crypto(symbol) else TimeInForce.DAY
    req = MarketOrderRequest(
        symbol=symbol,
        qty=qty,
        side=OrderSide.BUY if side == "buy" else OrderSide.SELL,
        time_in_force=tif,
    )
    order = _trading_c().submit_order(req)
    return {"id": str(order.id), "symbol": symbol, "qty": qty, "side": side, "status": str(order.status)}


@retry(**_READ_RETRY)
def get_orders(limit: int = 20) -> list[dict]:
    from alpaca.trading.requests import GetOrdersRequest
    from alpaca.trading.enums import QueryOrderStatus
    req = GetOrdersRequest(status=QueryOrderStatus.ALL, limit=limit)
    orders = _trading_c().get_orders(req)
    return [
        {
            "time":       o.created_at.strftime("%Y-%m-%d %H:%M"),
            "symbol":     o.symbol,
            "side":       str(o.side).split(".")[-1],
            "qty":        float(o.qty or 0),
            "filled_qty": float(o.filled_qty or 0),
            "status":     str(o.status).split(".")[-1],
            "filled_avg": float(o.filled_avg_price) if o.filled_avg_price else None,
            "value":      round(float(o.filled_qty or 0) * float(o.filled_avg_price or 0), 2),
        }
        for o in orders
    ]


def place_sliced_order(
    symbol: str,
    qty: float,
    side: str,
    max_slice_qty: int | None = None,
    delay_sec: float | None = None,
) -> list[dict]:
    """TWAP-style slicer: submits qty in chunks to reduce market impact.
    No retry — retrying sliced orders risks over-fills.
    """
    slice_size = float(max_slice_qty or config.ORDER_SLICE_MAX_QTY)
    delay = delay_sec if delay_sec is not None else config.ORDER_SLICE_DELAY_SEC
    remaining = float(qty)
    orders: list[dict] = []
    while remaining > 0:
        this_slice = min(remaining, slice_size)
        order = place_market_order(symbol, this_slice, side)
        orders.append(order)
        remaining -= this_slice
        log.info(
            "Slice %d/%d: %s %s x%.0f (%.0f remaining)",
            len(orders),
            int(qty / slice_size) + (1 if qty % slice_size else 0),
            side,
            symbol,
            this_slice,
            remaining,
        )
        if remaining > 0:
            time.sleep(delay)
    return orders


def close_position(symbol: str) -> dict:
    # No retry — closing the same position twice would flip the side.
    resp = _trading_c().close_position(symbol)
    return {"symbol": symbol, "status": "closed", "order_id": str(resp.id)}


@retry(**_READ_RETRY)
def get_position(symbol: str) -> dict | None:
    """Return single position dict or None if not held."""
    try:
        p = _trading_c().get_open_position(symbol)
        return {
            "symbol": p.symbol,
            "qty": float(p.qty),
            "side": "long" if float(p.qty) > 0 else "short",
            "avg_entry": float(p.avg_entry_price),
            "current_price": float(p.current_price),
            "unrealized_pnl": float(p.unrealized_pl),
            "unrealized_pnl_pct": float(p.unrealized_plpc),
        }
    except Exception:
        return None
