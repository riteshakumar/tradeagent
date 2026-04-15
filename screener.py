"""
Dynamic stock discovery — most active, top gainers, top losers, ETFs.
Uses Alpaca's screener API (no extra subscription needed).
"""
import requests
import config

_HEADERS = {
    "APCA-API-KEY-ID": config.ALPACA_API_KEY,
    "APCA-API-SECRET-KEY": config.ALPACA_SECRET_KEY,
}
_BASE = "https://data.alpaca.markets/v1beta1/screener"

# Curated ETF universe by theme
ETF_UNIVERSE = {
    "Broad Market": ["SPY", "QQQ", "IWM", "DIA", "VTI"],
    "Tech":         ["XLK", "SOXX", "IGV", "ARKK", "SMH"],
    "Energy":       ["XLE", "OIH", "UNG", "USO"],
    "Finance":      ["XLF", "KRE", "IAI"],
    "Healthcare":   ["XLV", "IBB", "XBI"],
    "Bonds":        ["TLT", "AGG", "HYG", "LQD"],
    "Commodities":  ["GLD", "SLV", "PDBC"],
    "Volatility":   ["VXX", "UVXY"],
}


def most_active(top_n: int = 10) -> list[dict]:
    """Top N stocks by trading volume today."""
    try:
        r = requests.get(
            f"{_BASE}/stocks/most-actives",
            headers=_HEADERS,
            params={"by": "volume", "top": top_n},
            timeout=5,
        )
        r.raise_for_status()
        return [
            {"symbol": s["symbol"], "volume": s.get("volume"), "trade_count": s.get("trade_count")}
            for s in r.json().get("most_actives", [])
        ]
    except Exception as e:
        return [{"symbol": "ERROR", "volume": None, "trade_count": None, "error": str(e)}]


def top_gainers(top_n: int = 10) -> list[dict]:
    """Top N stocks by % gain today."""
    try:
        r = requests.get(
            f"{_BASE}/stocks/movers",
            headers=_HEADERS,
            params={"top": top_n},
            timeout=5,
        )
        r.raise_for_status()
        return [
            {
                "symbol": s["symbol"],
                "change_pct": round(s.get("percent_change", 0), 2),
                "price": s.get("price"),
            }
            for s in r.json().get("gainers", [])
        ]
    except Exception as e:
        return [{"symbol": "ERROR", "change_pct": None, "price": None, "error": str(e)}]


def top_losers(top_n: int = 10) -> list[dict]:
    """Top N stocks by % loss today."""
    try:
        r = requests.get(
            f"{_BASE}/stocks/movers",
            headers=_HEADERS,
            params={"top": top_n},
            timeout=5,
        )
        r.raise_for_status()
        return [
            {
                "symbol": s["symbol"],
                "change_pct": round(s.get("percent_change", 0), 2),
                "price": s.get("price"),
            }
            for s in r.json().get("losers", [])
        ]
    except Exception as e:
        return [{"symbol": "ERROR", "change_pct": None, "price": None, "error": str(e)}]


def etf_list(themes: list[str] | None = None) -> list[str]:
    """Return ETF symbols for selected themes (or all if themes=None)."""
    selected = themes or list(ETF_UNIVERSE.keys())
    symbols = []
    for theme in selected:
        symbols.extend(ETF_UNIVERSE.get(theme, []))
    return symbols


def _clean(symbols: list[str]) -> list[str]:
    """Remove error placeholders and non-standard tickers (warrants, rights, units)."""
    return [s for s in symbols if s != "ERROR" and "." not in s and len(s) <= 5]


def build_watchlist(source: str, top_n: int = 10, etf_themes: list[str] | None = None) -> list[str]:
    """
    Build a dynamic watchlist.
    source: "static" | "most_active" | "gainers" | "losers" | "etf"
    """
    if source == "most_active":
        return _clean([s["symbol"] for s in most_active(top_n)])
    if source == "gainers":
        return _clean([s["symbol"] for s in top_gainers(top_n)])
    if source == "losers":
        return _clean([s["symbol"] for s in top_losers(top_n)])
    if source == "etf":
        return etf_list(etf_themes)
    return config.WATCHLIST  # fallback to static
