import config


_peak_equity: float = 0.0


def compute_qty(symbol: str, price: float, account: dict) -> float:
    """Position size = MAX_POSITION_PCT of portfolio, floored to 1 share."""
    max_dollars = account["portfolio_value"] * config.MAX_POSITION_PCT
    qty = max_dollars / price
    return max(1.0, round(qty, 0))


def check_drawdown(account: dict) -> bool:
    """Returns True if trading should halt due to drawdown breach."""
    global _peak_equity
    equity = account["equity"]
    if equity > _peak_equity:
        _peak_equity = equity
    if _peak_equity == 0:
        return False
    drawdown = (_peak_equity - equity) / _peak_equity
    return drawdown >= config.MAX_DRAWDOWN_PCT


def already_positioned(symbol: str, positions: list[dict]) -> bool:
    return any(p["symbol"] == symbol for p in positions)
