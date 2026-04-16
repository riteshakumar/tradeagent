from alpaca.trading.client import TradingClient
from alpaca.trading.requests import MarketOrderRequest
from alpaca.trading.enums import OrderSide, TimeInForce
from alpaca.data.historical import StockHistoricalDataClient
from alpaca.data.requests import StockBarsRequest
from alpaca.data.timeframe import TimeFrame, TimeFrameUnit
from datetime import datetime, timedelta
import config


_trading = TradingClient(config.ALPACA_API_KEY, config.ALPACA_SECRET_KEY, paper=config.PAPER_TRADING)
_data = StockHistoricalDataClient(config.ALPACA_API_KEY, config.ALPACA_SECRET_KEY)

# Map config string → (TimeFrame, lookback timedelta)
_TIMEFRAME_MAP = {
    "1Min":  (TimeFrame(1,  TimeFrameUnit.Minute), timedelta(days=2)),
    "5Min":  (TimeFrame(5,  TimeFrameUnit.Minute), timedelta(days=5)),
    "15Min": (TimeFrame(15, TimeFrameUnit.Minute), timedelta(days=10)),
    "1Hour": (TimeFrame(1,  TimeFrameUnit.Hour),   timedelta(days=30)),
    "1Day":  (TimeFrame.Day,                        timedelta(days=60)),
}


def get_account() -> dict:
    acc = _trading.get_account()
    return {
        "equity": float(acc.equity),
        "cash": float(acc.cash),
        "buying_power": float(acc.buying_power),
        "portfolio_value": float(acc.portfolio_value),
    }


def get_positions() -> list[dict]:
    positions = _trading.get_all_positions()
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


def get_bars(symbol: str, timeframe: str | None = None, lookback_days: int | None = None) -> list[dict]:
    tf_key = timeframe or config.BAR_TIMEFRAME
    tf, default_lookback = _TIMEFRAME_MAP.get(tf_key, _TIMEFRAME_MAP["5Min"])
    lookback = timedelta(days=lookback_days) if lookback_days else default_lookback
    req = StockBarsRequest(
        symbol_or_symbols=symbol,
        timeframe=tf,
        start=datetime.now() - lookback,
    )
    bars = _data.get_stock_bars(req)[symbol]
    return [
        {"t": b.timestamp.isoformat(), "o": b.open, "h": b.high, "l": b.low, "c": b.close, "v": b.volume}
        for b in bars
    ]


def place_market_order(symbol: str, qty: float, side: str) -> dict:
    req = MarketOrderRequest(
        symbol=symbol,
        qty=qty,
        side=OrderSide.BUY if side == "buy" else OrderSide.SELL,
        time_in_force=TimeInForce.DAY,
    )
    order = _trading.submit_order(req)
    return {"id": str(order.id), "symbol": symbol, "qty": qty, "side": side, "status": str(order.status)}


def get_orders(limit: int = 20) -> list[dict]:
    from alpaca.trading.requests import GetOrdersRequest
    from alpaca.trading.enums import QueryOrderStatus
    req = GetOrdersRequest(status=QueryOrderStatus.ALL, limit=limit)
    orders = _trading.get_orders(req)
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


def close_position(symbol: str) -> dict:
    resp = _trading.close_position(symbol)
    return {"symbol": symbol, "status": "closed", "order_id": str(resp.id)}


def get_position(symbol: str) -> dict | None:
    """Return single position dict or None if not held."""
    try:
        p = _trading.get_open_position(symbol)
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
