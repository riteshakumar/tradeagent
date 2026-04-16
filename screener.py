"""
Dynamic stock discovery — most active, top gainers, top losers, ETFs, sectors.
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
    "Broad Market": ["SPY", "QQQ", "IWM", "DIA", "VTI", "RSP"],
    "Tech":         ["XLK", "SOXX", "IGV", "ARKK", "SMH", "QTEC"],
    "Energy":       ["XLE", "OIH", "UNG", "USO", "AMLP"],
    "Finance":      ["XLF", "KRE", "IAI", "KBE"],
    "Healthcare":   ["XLV", "IBB", "XBI", "IHI"],
    "Bonds":        ["TLT", "AGG", "HYG", "LQD", "IEF", "SHY"],
    "Commodities":  ["GLD", "SLV", "PDBC", "CPER", "DBA"],
    "Real Estate":  ["VNQ", "XLRE", "IYR"],
    "Utilities":    ["XLU", "VPU"],
    "Industrials":  ["XLI", "ITA", "IYT"],
    "Consumer":     ["XLY", "XLP", "IBUY"],
    "Volatility":   ["VXX", "UVXY", "SVXY"],
}

# Representative sector stocks (large-cap leaders per sector)
SECTOR_STOCKS = {
    "Tech":         ["AAPL", "MSFT", "NVDA", "META", "GOOGL", "AMZN", "AMD", "AVGO", "ORCL", "ADBE"],
    "Finance":      ["JPM", "BAC", "GS", "MS", "WFC", "BLK", "C", "AXP", "V", "MA"],
    "Energy":       ["XOM", "CVX", "COP", "SLB", "EOG", "OXY", "MPC", "PSX", "VLO", "HES"],
    "Healthcare":   ["JNJ", "UNH", "LLY", "ABBV", "MRK", "PFE", "TMO", "ABT", "DHR", "BMY"],
    "Consumer":     ["TSLA", "AMZN", "HD", "MCD", "NKE", "SBUX", "TGT", "LOW", "GM", "F"],
    "Industrials":  ["CAT", "BA", "HON", "UNP", "LMT", "RTX", "GE", "MMM", "DE", "FDX"],
    "Real Estate":  ["AMT", "PLD", "CCI", "EQIX", "SPG", "PSA", "O", "WELL", "DLR", "AVB"],
    "Utilities":    ["NEE", "DUK", "SO", "D", "AEP", "EXC", "XEL", "ES", "WEC", "AWK"],
    "Broad Market": ["SPY", "QQQ", "IWM", "AAPL", "MSFT", "AMZN", "GOOGL", "NVDA", "META", "TSLA"],
}

# Combined ETFs + stocks per sector (for "Sector" watchlist source)
SECTOR_UNIVERSE: dict[str, list[str]] = {}
for _sector in set(list(ETF_UNIVERSE.keys()) + list(SECTOR_STOCKS.keys())):
    _syms: list[str] = []
    _syms.extend(ETF_UNIVERSE.get(_sector, []))
    _syms.extend(SECTOR_STOCKS.get(_sector, []))
    SECTOR_UNIVERSE[_sector] = list(dict.fromkeys(_syms))  # dedup, preserve order


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


def _clean(rows: list[dict], price_field: str = "price") -> list[str]:
    """
    Filter out:
    - error placeholders
    - non-standard tickers (warrants, rights: contain '.' or len > 5)
    - stocks below MIN_STOCK_PRICE
    - stocks below MIN_STOCK_VOLUME (if volume field present)
    """
    out = []
    for r in rows:
        sym = r.get("symbol", "")
        if sym == "ERROR" or "." in sym or len(sym) > 5:
            continue
        price = r.get(price_field) or r.get("price")
        if price is not None and float(price) < config.MIN_STOCK_PRICE:
            continue
        vol = r.get("volume")
        if vol is not None and float(vol) < config.MIN_STOCK_VOLUME:
            continue
        out.append(sym)
    return out


def trending(top_n: int = 15) -> list[str]:
    """
    Return symbols that are trending right now: merge top gainers + most active,
    deduplicated, ordered by activity. Used for the live ticker tape header.
    """
    half = max(3, top_n // 2)
    gainers  = _clean(top_gainers(half + 3))
    actives  = _clean(most_active(half + 3))
    seen: dict[str, None] = {}
    for sym in gainers + actives:
        seen[sym] = None
    return list(seen.keys())[:top_n]


def sector_list(sectors: list[str] | None = None) -> list[str]:
    """Return ETF + stock symbols for the requested sectors."""
    selected = sectors or list(SECTOR_UNIVERSE.keys())
    syms: list[str] = []
    for s in selected:
        syms.extend(SECTOR_UNIVERSE.get(s, []))
    return list(dict.fromkeys(syms))


def build_watchlist(
    source: str,
    top_n: int = 10,
    etf_themes: list[str] | None = None,
    sectors: list[str] | None = None,
) -> list[str]:
    """
    Build a dynamic watchlist.
    source: "static" | "most_active" | "gainers" | "losers" | "etf" | "sector" | "trending"
    """
    if source == "most_active":
        return _clean(most_active(top_n))
    if source == "gainers":
        return _clean(top_gainers(top_n))
    if source == "losers":
        return _clean(top_losers(top_n))
    if source == "etf":
        return etf_list(etf_themes)
    if source == "sector":
        return sector_list(sectors)
    if source == "trending":
        return trending(top_n)
    return config.WATCHLIST  # fallback to static
