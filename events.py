"""
Event-driven signal layer.

Three event types:
  1. Geopolitical  — oil/defense stocks react to conflict/sanctions headlines
  2. Earnings      — parse earnings beats/misses/guidance from news
  3. Macro         — inflation/rates data impacts rate-sensitive sectors

Each returns an EventSignal with score (-3..+3) and reason string.
Score is added on top of the quant score in strategy.py.
"""
import json
import logging
from datetime import date, datetime, timezone
import requests
import config

log = logging.getLogger(__name__)

# ── Sector maps ────────────────────────────────────────────────────────────────
SECTOR_MAP = {
    "geopolitical": {
        "oil":     ["XOM", "CVX", "OXY", "MRO", "USO", "XLE", "COP"],
        "defense": ["LMT", "RTX", "NOC", "GD", "BA", "HII", "LHX"],
    },
    "macro": {
        "reits":        ["VNQ", "XLRE", "AMT", "PLD", "SPG"],
        "growth_tech":  ["QQQ", "ARKK", "NVDA", "META", "AMZN", "GOOGL"],
        "bonds":        ["TLT", "AGG", "IEF"],
        "banks":        ["JPM", "BAC", "GS", "XLF"],
    },
}

_NEWS_URL = "https://data.alpaca.markets/v1beta1/news"
_HEADERS = {
    "APCA-API-KEY-ID": config.ALPACA_API_KEY,
    "APCA-API-SECRET-KEY": config.ALPACA_SECRET_KEY,
}
_EARNINGS_TRIGGER_KW = ("earnings", "eps", "guidance", "beat", "miss")
_EARNINGS_POST_KW = ("earnings", "eps", "quarterly result", "reports q", "beat", "miss", "guidance")
_EARNINGS_UPCOMING_PATTERNS = (
    "reports on", "will report", "scheduled to report",
    "earnings date", "due to report", "reports earnings",
    "earnings call", "q1 earnings", "q2 earnings",
    "q3 earnings", "q4 earnings", "fiscal", "announces results",
)


# ── News fetcher ───────────────────────────────────────────────────────────────
def _fetch_news_page(
    symbols: list[str] | None = None,
    keywords: str | None = None,
    limit: int = 10,
    start: str | None = None,
    end: str | None = None,
    sort: str = "desc",
    page_token: str | None = None,
) -> tuple[list[dict], str | None]:
    params = {"limit": limit, "sort": sort}
    if symbols:
        params["symbols"] = ",".join(symbols)
    if keywords:
        params["keywords"] = keywords
    if start:
        params["start"] = start
    if end:
        params["end"] = end
    if page_token:
        params["page_token"] = page_token
    try:
        r = requests.get(_NEWS_URL, headers=_HEADERS, params=params, timeout=5)
        r.raise_for_status()
        payload = r.json()
        return [
            {
                "headline": a.get("headline", ""),
                "summary":  a.get("summary", ""),
                "source":   a.get("source", ""),
                "created":  a.get("created_at", ""),
                "symbols":  a.get("symbols", []),
            }
            for a in payload.get("news", [])
        ], payload.get("next_page_token")
    except Exception as e:
        log.warning("News fetch failed: %s", e)
        return [], None


def fetch_news(
    symbols: list[str] | None = None,
    keywords: str | None = None,
    limit: int = 10,
    start: str | None = None,
    end: str | None = None,
    sort: str = "desc",
) -> list[dict]:
    news, _ = _fetch_news_page(
        symbols=symbols,
        keywords=keywords,
        limit=limit,
        start=start,
        end=end,
        sort=sort,
    )
    return news


def fetch_news_range(
    symbols: list[str] | None = None,
    keywords: str | None = None,
    start: str | None = None,
    end: str | None = None,
    sort: str = "desc",
    page_limit: int = 50,
    max_items: int = 250,
) -> list[dict]:
    items: list[dict] = []
    page_token: str | None = None
    batch_limit = max(1, int(page_limit))
    target = max(1, int(max_items))

    while len(items) < target:
        page_items, page_token = _fetch_news_page(
            symbols=symbols,
            keywords=keywords,
            limit=min(batch_limit, target - len(items)),
            start=start,
            end=end,
            sort=sort,
            page_token=page_token,
        )
        if not page_items:
            break
        items.extend(page_items)
        if not page_token:
            break

    return items[:target]


def _coerce_datetime(value: datetime | str | None) -> datetime | None:
    if value is None:
        return None
    if isinstance(value, datetime):
        dt = value
    else:
        try:
            dt = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
        except ValueError:
            return None
    if dt.tzinfo is not None:
        return dt.astimezone(timezone.utc).replace(tzinfo=None)
    return dt


def _visible_news(
    news: list[dict],
    as_of: datetime | str | None = None,
    max_age_days: float | None = None,
) -> list[dict]:
    as_of_dt = _coerce_datetime(as_of)
    visible: list[dict] = []
    for item in news:
        created_dt = _coerce_datetime(item.get("created"))
        if as_of_dt is not None and created_dt is not None:
            if created_dt > as_of_dt:
                continue
            if max_age_days is not None:
                age_days = (as_of_dt - created_dt).total_seconds() / 86400.0
                if age_days > max_age_days:
                    continue
        visible.append(item)
    return visible


def has_earnings_news(
    news: list[dict],
    as_of: datetime | str | None = None,
    max_age_days: float = 7.0,
) -> bool:
    for item in _visible_news(news, as_of=as_of, max_age_days=max_age_days):
        headline = item.get("headline", "").lower()
        if headline and any(kw in headline for kw in _EARNINGS_TRIGGER_KW):
            return True
    return False


# ── LLM sentiment scorer ───────────────────────────────────────────────────────
def _llm_score(prompt: str) -> dict:
    """
    Ask the configured LLM to return JSON: {score: int, reason: str, confidence: str}
    score: -3 (very bearish) .. +3 (very bullish)
    Falls back to {"score": 0, "reason": "agent disabled", "confidence": "low"} if USE_AGENT=false.
    """
    if not config.USE_AGENT:
        return {"score": 0, "reason": "agent disabled — no LLM scoring", "confidence": "low"}

    system = (
        "You are a financial sentiment analyst. "
        "Analyze the provided news headlines and return ONLY valid JSON in this exact format: "
        '{"score": <integer -3 to 3>, "reason": "<one sentence>", "confidence": "<low|medium|high>"} '
        "where score -3=very bearish, 0=neutral, +3=very bullish. No other text."
    )

    if config.AGENT_PROVIDER == "openai":
        import openai
        client = openai.OpenAI(api_key=config.OPENAI_API_KEY)
        resp = client.chat.completions.create(
            model=config.OPENAI_MODEL,
            messages=[{"role": "system", "content": system}, {"role": "user", "content": prompt}],
            max_tokens=100,
            temperature=0,
        )
        raw = resp.choices[0].message.content.strip()
    else:
        import anthropic
        client = anthropic.Anthropic(api_key=config.ANTHROPIC_API_KEY)
        resp = client.messages.create(
            model=config.ANTHROPIC_MODEL,
            max_tokens=100,
            system=system,
            messages=[{"role": "user", "content": prompt}],
        )
        raw = resp.content[0].text.strip()

    try:
        return json.loads(raw)
    except Exception:
        return {"score": 0, "reason": f"parse error: {raw[:80]}", "confidence": "low"}


# ── Event signal builders ──────────────────────────────────────────────────────
def geopolitical_signal(symbol: str) -> dict:
    """
    Score a symbol based on geopolitical headlines.
    Relevant for oil and defense stocks.
    Returns: {score, reason, confidence, event_type}
    """
    sector = None
    for s, tickers in SECTOR_MAP["geopolitical"].items():
        if symbol in tickers:
            sector = s
            break

    if sector is None:
        return {"score": 0, "reason": "not a geopolitical-sensitive stock", "confidence": "low", "event_type": "geopolitical"}

    keywords = "Iran Hormuz war sanctions oil defense conflict" if sector == "oil" else "defense spending military conflict NATO war"
    news = fetch_news(symbols=[symbol], keywords=keywords, limit=8)
    headlines = "\n".join(f"- {n['headline']}" for n in news if n.get("headline"))

    if not headlines.strip():
        return {"score": 0, "reason": "no relevant geopolitical news found", "confidence": "low", "event_type": "geopolitical"}

    prompt = (
        f"Symbol: {symbol} (sector: {sector})\n"
        f"Context: Geopolitical events affecting {sector} stocks.\n"
        f"Headlines:\n{headlines}\n\n"
        f"Score the bullish/bearish impact on {symbol} from these headlines."
    )
    result = _llm_score(prompt)
    result["event_type"] = "geopolitical"
    return result


def earnings_signal(symbol: str, news: list[dict] | None = None) -> dict:
    """
    Score a symbol based on recent earnings news (beats, misses, guidance).
    Returns: {score, reason, confidence, event_type}
    """
    if news is None:
        news = fetch_news(symbols=[symbol], keywords="earnings EPS revenue guidance beat miss forecast", limit=8)
    headlines = "\n".join(f"- {n['headline']}: {n['summary'][:120]}" for n in news if n.get("headline"))

    if not headlines.strip():
        return {"score": 0, "reason": "no earnings news found", "confidence": "low", "event_type": "earnings"}

    prompt = (
        f"Symbol: {symbol}\n"
        f"Context: Recent earnings news.\n"
        f"Headlines:\n{headlines}\n\n"
        f"Score the bullish/bearish impact on {symbol} based on earnings beats, misses, and guidance."
    )
    result = _llm_score(prompt)
    result["event_type"] = "earnings"
    return result


def macro_signal(symbol: str) -> dict:
    """
    Score a symbol based on macro data (inflation, rates, Fed decisions).
    Relevant for REITs, growth tech, bonds, banks.
    Returns: {score, reason, confidence, event_type}
    """
    sector = None
    for s, tickers in SECTOR_MAP["macro"].items():
        if symbol in tickers:
            sector = s
            break

    if sector is None:
        return {"score": 0, "reason": "not a macro-sensitive stock", "confidence": "low", "event_type": "macro"}

    news = fetch_news(keywords="inflation CPI Fed interest rates Federal Reserve FOMC Treasury yield", limit=10)
    headlines = "\n".join(f"- {n['headline']}" for n in news if n.get("headline"))

    if not headlines.strip():
        return {"score": 0, "reason": "no macro news found", "confidence": "low", "event_type": "macro"}

    sector_context = {
        "reits":       "REITs benefit from lower rates (cheaper borrowing, higher valuations)",
        "growth_tech": "Growth tech benefits from lower rates (higher DCF valuations)",
        "bonds":       "Bond prices rise when rates fall",
        "banks":       "Banks benefit from higher rates (wider net interest margin)",
    }

    prompt = (
        f"Symbol: {symbol} (sector: {sector})\n"
        f"Context: {sector_context.get(sector, '')}\n"
        f"Macro headlines:\n{headlines}\n\n"
        f"Score the bullish/bearish macro impact on {symbol}."
    )
    result = _llm_score(prompt)
    result["event_type"] = "macro"
    return result


# ── Earnings proximity detection ──────────────────────────────────────────────
def is_earnings_period(symbol: str, pre_days: int = 5, post_days: int = 2) -> bool:
    """
    Return True if the symbol is in an earnings risk window:
      - Earnings imminent: upcoming earnings language detected in recent news
      - Just reported: earnings headline within the last post_days days

    Uses Alpaca news API. Returns False on any error (fail-open for trading).
    pre_days:  block new buys this many days BEFORE expected earnings
    post_days: block new buys this many days AFTER earnings (post-earnings vol)
    """
    try:
        news = fetch_news(
            symbols=[symbol],
            keywords="earnings report quarterly results EPS guidance beat miss",
            limit=15,
        )
        return is_earnings_period_from_news(
            news,
            as_of=datetime.now(timezone.utc),
            pre_days=pre_days,
            post_days=post_days,
        )
    except Exception:
        return False  # Fail-open: don't block trading on API errors


def is_earnings_period_from_news(
    news: list[dict],
    as_of: datetime | str | None = None,
    pre_days: int = 5,
    post_days: int = 2,
) -> bool:
    """
    Historical-safe version of is_earnings_period that only considers headlines
    visible on or before ``as_of`` and applies the documented pre/post windows.
    """
    as_of_dt = _coerce_datetime(as_of)
    visible = _visible_news(news, as_of=as_of_dt, max_age_days=float(max(pre_days, post_days)))

    for item in visible:
        headline = item.get("headline", "").lower()
        if not headline:
            continue

        created_dt = _coerce_datetime(item.get("created"))
        age_days = None
        if as_of_dt is not None and created_dt is not None:
            age_days = (as_of_dt - created_dt).total_seconds() / 86400.0

        if any(pattern in headline for pattern in _EARNINGS_UPCOMING_PATTERNS):
            if age_days is None or age_days <= pre_days:
                return True

        if any(kw in headline for kw in _EARNINGS_POST_KW):
            if age_days is not None and age_days <= post_days:
                return True

    return False


# ── Keyword sets for fast (no-LLM) sentiment scoring ──────────────────────────
_POS_KW = frozenset([
    "beat", "beats", "upgrade", "upgraded", "outperform", "record", "strong",
    "growth", "surge", "surges", "gain", "gains", "rally", "buyback", "dividend",
    "raised", "raises", "bullish", "profit", "revenue", "wins", "approved",
    "partnership", "launch", "launched", "acquisition",
])
_NEG_KW = frozenset([
    "miss", "misses", "downgrade", "downgraded", "underperform", "recall",
    "fraud", "lawsuit", "lawsuits", "resign", "resigned", "layoff", "layoffs",
    "loss", "losses", "decline", "declines", "weak", "warning", "cut", "cuts",
    "bearish", "debt", "investigation", "fine", "penalty", "delay", "canceled",
    "concern", "concerns", "risk", "risks", "breach", "hack",
])

_MACRO_KW = frozenset([
    "federal reserve", "fomc", "rate decision", "powell", "fed meeting",
    "consumer price index", "cpi report", "inflation data", "pce index",
    "nonfarm payroll", "jobs report", "unemployment rate", "nfp",
    "gdp report", "retail sales data", "ppi report", "trade deficit",
])

# Hardcoded high-impact macro dates (FOMC decisions, CPI releases, NFP) for 2025-2026.
# Update annually; used as a reliable first-pass before the news scan.
_KNOWN_MACRO_DATES: frozenset[date] = frozenset([
    # FOMC 2025
    date(2025, 1, 29), date(2025, 3, 19), date(2025, 5, 7),
    date(2025, 6, 18), date(2025, 7, 30), date(2025, 9, 17),
    date(2025, 10, 29), date(2025, 12, 10),
    # FOMC 2026
    date(2026, 1, 28), date(2026, 3, 18), date(2026, 4, 29),
    date(2026, 6, 17), date(2026, 7, 29), date(2026, 9, 16),
    date(2026, 10, 28), date(2026, 12, 9),
    # CPI 2025 (approx 2nd-3rd Wed each month)
    date(2025, 1, 15), date(2025, 2, 12), date(2025, 3, 12),
    date(2025, 4, 10), date(2025, 5, 13), date(2025, 6, 11),
    date(2025, 7, 11), date(2025, 8, 13), date(2025, 9, 10),
    date(2025, 10, 15), date(2025, 11, 13), date(2025, 12, 10),
    # CPI 2026
    date(2026, 1, 14), date(2026, 2, 11), date(2026, 3, 11),
    date(2026, 4, 10), date(2026, 5, 13), date(2026, 6, 10),
    # NFP 2025 (first Fri of month)
    date(2025, 1, 10), date(2025, 2, 7), date(2025, 3, 7),
    date(2025, 4, 4), date(2025, 5, 2), date(2025, 6, 6),
    date(2025, 7, 3), date(2025, 8, 1), date(2025, 9, 5),
    date(2025, 10, 3), date(2025, 11, 7), date(2025, 12, 5),
    # NFP 2026
    date(2026, 1, 9), date(2026, 2, 6), date(2026, 3, 6),
    date(2026, 4, 3), date(2026, 5, 1), date(2026, 6, 5),
])


def sentiment_trend(symbol: str) -> int:
    """
    Fast keyword-based sentiment score for a ticker — no LLM, no cost.
    Returns +1 (positive), 0 (neutral), -1 (negative).
    Used for pre-market curation and signal enrichment.
    """
    try:
        news = fetch_news(symbols=[symbol], limit=20)
        pos = neg = 0
        for n in news:
            text = (n.get("headline", "") + " " + n.get("summary", "")).lower()
            pos += sum(1 for kw in _POS_KW if kw in text)
            neg += sum(1 for kw in _NEG_KW if kw in text)
        if pos == 0 and neg == 0:
            return 0
        net = pos - neg
        if net >= 2:
            return 1
        if net <= -2:
            return -1
        return 0
    except Exception:
        return 0


def is_high_impact_macro_day() -> bool:
    """
    Return True on days with major scheduled macro events (FOMC, CPI, NFP, GDP).
    Checks hardcoded calendar first (zero latency), then falls back to news scan.
    """
    if not config.MACRO_SUPPRESSION_ENABLED:
        return False
    today = date.today()
    if today in _KNOWN_MACRO_DATES:
        log.info("Macro calendar hit: %s is a known high-impact event date", today)
        return True
    try:
        news = fetch_news(limit=15)  # broad market, no symbol filter
        for n in news:
            text = (n.get("headline", "") + " " + n.get("summary", "")).lower()
            if any(kw in text for kw in _MACRO_KW):
                return True
        return False
    except Exception:
        return False


# ── Unified event score for a symbol ──────────────────────────────────────────
def get_event_score(
    symbol: str,
    run_earnings: bool = True,
    run_geo: bool = True,
    run_macro: bool = True,
    news: list[dict] | None = None,
) -> dict:
    """
    Run all applicable event signals for a symbol and return combined score.
    """
    signals = []
    if run_geo:
        signals.append(geopolitical_signal(symbol))
    if run_earnings:
        signals.append(earnings_signal(symbol, news=news))
    if run_macro:
        signals.append(macro_signal(symbol))

    # Only count signals with score != 0
    active = [s for s in signals if s["score"] != 0]
    total_score = sum(s["score"] for s in active)
    # Cap combined event score at ±3
    total_score = max(-3, min(3, total_score))

    reasons = [f"[{s['event_type']}] {s['reason']}" for s in active]

    return {
        "event_score": total_score,
        "event_reasons": reasons,
        "signals": signals,
    }


def _historical_earnings_signal(
    symbol: str,
    news: list[dict],
    as_of: datetime | str | None = None,
) -> dict:
    relevant_news = [
        item
        for item in _visible_news(news, as_of=as_of, max_age_days=7.0)
        if item.get("headline") and has_earnings_news([item], as_of=as_of, max_age_days=7.0)
    ]
    if not relevant_news:
        return {"score": 0, "reason": "no earnings news found", "confidence": "low", "event_type": "earnings"}

    pos = neg = 0
    for item in relevant_news:
        text = (item.get("headline", "") + " " + item.get("summary", "")).lower()
        pos += sum(1 for kw in _POS_KW if kw in text)
        neg += sum(1 for kw in _NEG_KW if kw in text)

    if pos == 0 and neg == 0:
        return {
            "score": 0,
            "reason": "earnings headlines are mixed or low signal",
            "confidence": "low",
            "event_type": "earnings",
        }

    net = pos - neg
    magnitude = abs(net)
    if magnitude >= 4:
        score = 3
        confidence = "high"
    elif magnitude >= 2:
        score = 2
        confidence = "medium"
    else:
        score = 1
        confidence = "low"

    score = score if net > 0 else -score
    direction = "bullish" if score > 0 else "bearish"
    reason = f"historical earnings headlines skew {direction} for {symbol} ({pos} positive vs {neg} negative cues)"
    return {
        "score": score,
        "reason": reason,
        "confidence": confidence,
        "event_type": "earnings",
    }


def get_historical_event_score(
    symbol: str,
    news: list[dict],
    as_of: datetime | str | None = None,
    run_earnings: bool = True,
    run_geo: bool = False,
    run_macro: bool = False,
) -> dict:
    """
    Deterministic historical event replay for backtests.

    This intentionally avoids LLM calls and only uses headlines that were
    already available on or before ``as_of``.
    """
    signals = []
    if run_geo:
        signals.append(
            {"score": 0, "reason": "historical geopolitical replay unavailable", "confidence": "low", "event_type": "geopolitical"}
        )
    if run_earnings:
        signals.append(_historical_earnings_signal(symbol, news, as_of=as_of))
    if run_macro:
        signals.append(
            {"score": 0, "reason": "historical macro replay unavailable", "confidence": "low", "event_type": "macro"}
        )

    active = [signal for signal in signals if signal["score"] != 0]
    total_score = max(-3, min(3, sum(signal["score"] for signal in active)))
    reasons = [f"[{signal['event_type']}] {signal['reason']}" for signal in active]

    return {
        "event_score": total_score,
        "event_reasons": reasons,
        "signals": signals,
    }
