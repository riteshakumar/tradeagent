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
import requests
import config

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


# ── News fetcher ───────────────────────────────────────────────────────────────
def fetch_news(symbols: list[str] | None = None, keywords: str | None = None, limit: int = 10) -> list[dict]:
    params = {"limit": limit, "sort": "desc"}
    if symbols:
        params["symbols"] = ",".join(symbols)
    if keywords:
        params["keywords"] = keywords
    try:
        r = requests.get(_NEWS_URL, headers=_HEADERS, params=params, timeout=5)
        r.raise_for_status()
        return [
            {
                "headline": a.get("headline", ""),
                "summary":  a.get("summary", ""),
                "source":   a.get("source", ""),
                "created":  a.get("created_at", ""),
                "symbols":  a.get("symbols", []),
            }
            for a in r.json().get("news", [])
        ]
    except Exception as e:
        return [{"headline": f"[news fetch error: {e}]", "summary": "", "source": "", "created": "", "symbols": []}]


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
    headlines = "\n".join(f"- {n['headline']}" for n in news if n["headline"])

    if not headlines.strip() or "[news fetch error" in headlines:
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


def earnings_signal(symbol: str) -> dict:
    """
    Score a symbol based on recent earnings news (beats, misses, guidance).
    Returns: {score, reason, confidence, event_type}
    """
    news = fetch_news(symbols=[symbol], keywords="earnings EPS revenue guidance beat miss forecast", limit=8)
    headlines = "\n".join(f"- {n['headline']}: {n['summary'][:120]}" for n in news if n["headline"])

    if not headlines.strip() or "[news fetch error" in headlines:
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
    headlines = "\n".join(f"- {n['headline']}" for n in news if n["headline"])

    if not headlines.strip() or "[news fetch error" in headlines:
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
        from datetime import datetime, timezone, timedelta
        news = fetch_news(
            symbols=[symbol],
            keywords="earnings report quarterly results EPS guidance beat miss",
            limit=15,
        )
        now = datetime.now(timezone.utc)

        for n in news:
            headline = n.get("headline", "").lower()
            if not headline or "[news fetch error" in headline:
                break

            # Check if the news is very recent (post-earnings vol window)
            created_str = n.get("created", "")
            if created_str:
                try:
                    dt = datetime.fromisoformat(created_str.replace("Z", "+00:00"))
                    age_days = (now - dt).total_seconds() / 86400
                    if age_days <= post_days:
                        earnings_kws = ("earnings", "eps", "quarterly result", "reports q", "beat", "miss", "guidance")
                        if any(kw in headline for kw in earnings_kws):
                            return True  # Just reported — stay out of the vol
                except Exception:
                    pass

            # Check for upcoming earnings language
            upcoming_patterns = (
                "reports on", "will report", "scheduled to report",
                "earnings date", "due to report", "reports earnings",
                "earnings call", "q1 earnings", "q2 earnings",
                "q3 earnings", "q4 earnings", "fiscal", "announces results",
            )
            if any(p in headline for p in upcoming_patterns):
                return True  # Upcoming earnings detected

        return False
    except Exception:
        return False  # Fail-open: don't block trading on API errors


# ── Unified event score for a symbol ──────────────────────────────────────────
def get_event_score(symbol: str, run_earnings: bool = True, run_geo: bool = True, run_macro: bool = True) -> dict:
    """
    Run all applicable event signals for a symbol and return combined score.
    """
    signals = []
    if run_geo:
        signals.append(geopolitical_signal(symbol))
    if run_earnings:
        signals.append(earnings_signal(symbol))
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
