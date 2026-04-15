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
    return [
        {
            "symbol": p.symbol,
            "qty": float(p.qty),
            "avg_entry": float(p.avg_entry_price),
            "current_price": float(p.current_price),
            "unrealized_pnl": float(p.unrealized_pl),
            "unrealized_pnl_pct": float(p.unrealized_plpc),
        }
        for p in positions
    ]


def get_bars(symbol: str, timeframe: str | None = None) -> list[dict]:
    tf_key = timeframe or config.BAR_TIMEFRAME
    tf, lookback = _TIMEFRAME_MAP.get(tf_key, _TIMEFRAME_MAP["5Min"])
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


def close_position(symbol: str) -> dict:
    resp = _trading.close_position(symbol)
    return {"symbol": symbol, "status": "closed", "order_id": str(resp.id)}
