import pandas as pd
import numpy as np
import config


def _rsi(series: pd.Series, period: int = 14) -> pd.Series:
    delta = series.diff()
    gain = delta.clip(lower=0)
    loss = -delta.clip(upper=0)
    avg_gain = gain.ewm(com=period - 1, min_periods=period).mean()
    avg_loss = loss.ewm(com=period - 1, min_periods=period).mean()
    rs = avg_gain / avg_loss.replace(0, np.nan)
    return 100 - (100 / (1 + rs))


def _ema(series: pd.Series, period: int) -> pd.Series:
    return series.ewm(span=period, adjust=False).mean()


def _macd(series: pd.Series, fast=12, slow=26, signal=9):
    macd_line = _ema(series, fast) - _ema(series, slow)
    signal_line = _ema(macd_line, signal)
    return macd_line, signal_line


def compute_signals(bars: list[dict]) -> dict:
    if len(bars) < 30:
        return {"signal": "hold", "reason": "not enough data", "score": 0, "rsi": None, "price": None}

    df = pd.DataFrame(bars)
    close = df["c"].astype(float)

    rsi = _rsi(close)
    macd_line, signal_line = _macd(close)
    ema20 = _ema(close, 20)
    ema50 = _ema(close, 50)

    last_rsi = rsi.iloc[-1]
    last_macd, last_sig = macd_line.iloc[-1], signal_line.iloc[-1]
    prev_macd, prev_sig = macd_line.iloc[-2], signal_line.iloc[-2]
    price = close.iloc[-1]
    e20, e50 = ema20.iloc[-1], ema50.iloc[-1]

    score = 0
    reasons = []

    if last_rsi < 35:
        score += 2
        reasons.append(f"RSI oversold ({last_rsi:.1f})")
    elif last_rsi > 65:
        score -= 2
        reasons.append(f"RSI overbought ({last_rsi:.1f})")

    bullish_cross = prev_macd < prev_sig and last_macd > last_sig
    bearish_cross = prev_macd > prev_sig and last_macd < last_sig
    if bullish_cross:
        score += 2
        reasons.append("MACD bullish crossover")
    elif bearish_cross:
        score -= 2
        reasons.append("MACD bearish crossover")

    if price > e20 > e50:
        score += 1
        reasons.append("price above EMA20 > EMA50 (uptrend)")
    elif price < e20 < e50:
        score -= 1
        reasons.append("price below EMA20 < EMA50 (downtrend)")

    NO_SIGNAL = "no strong signal"

    t = config.SIGNAL_THRESHOLD
    if score >= t:
        signal = "buy"
    elif score <= -t:
        signal = "sell"
    else:
        signal = "hold"

    return {
        "signal": signal,
        "score": score,
        "rsi": round(last_rsi, 2),
        "price": round(price, 2),
        "reason": "; ".join(reasons) if reasons else NO_SIGNAL,
        "event_score": 0,
        "event_reasons": [],
    }


def apply_event_score(quant: dict, event: dict) -> dict:
    """Merge event score into a quant signal dict and recompute final signal."""
    NO_SIGNAL = "no strong signal"
    combined = quant["score"] + event["event_score"]

    base_reasons = [] if quant["reason"] == NO_SIGNAL else [quant["reason"]]
    all_reasons = base_reasons + event["event_reasons"]

    t = config.SIGNAL_THRESHOLD
    if combined >= t:
        signal = "buy"
    elif combined <= -t:
        signal = "sell"
    else:
        signal = "hold"

    return {
        **quant,
        "signal": signal,
        "score": combined,
        "event_score": event["event_score"],
        "event_reasons": event["event_reasons"],
        "reason": "; ".join(all_reasons) if all_reasons else NO_SIGNAL,
    }
