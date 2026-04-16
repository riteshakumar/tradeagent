from __future__ import annotations

import numpy as np
import pandas as pd

import config


_REGIME_WEIGHTS = {
    "bull_trend": {"rsi": 0.75, "macd": 1.25, "ema": 1.50, "bb": 0.75, "volume": 1.0},
    "bear_trend": {"rsi": 0.75, "macd": 1.25, "ema": 1.50, "bb": 0.75, "volume": 1.0},
    "range": {"rsi": 1.2, "macd": 0.8, "ema": 0.7, "bb": 1.4, "volume": 1.0},
    "high_volatility": {"rsi": 0.9, "macd": 0.8, "ema": 0.8, "bb": 1.3, "volume": 1.2},
}
_BASE_WEIGHTS = {"rsi": 1.0, "macd": 1.0, "ema": 1.0, "bb": 1.0, "volume": 1.0}


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


def _macd(series: pd.Series, fast: int = 12, slow: int = 26, signal: int = 9) -> tuple[pd.Series, pd.Series]:
    macd_line = _ema(series, fast) - _ema(series, slow)
    signal_line = _ema(macd_line, signal)
    return macd_line, signal_line


def _atr(df: pd.DataFrame, period: int = 14) -> pd.Series:
    high, low, close = df["h"].astype(float), df["l"].astype(float), df["c"].astype(float)
    prev_close = close.shift(1)
    tr = pd.concat([high - low, (high - prev_close).abs(), (low - prev_close).abs()], axis=1).max(axis=1)
    return tr.ewm(com=period - 1, min_periods=period).mean()


def _bollinger(series: pd.Series, period: int = 20, n_std: float = 2.0) -> tuple[pd.Series, pd.Series, pd.Series]:
    mid = series.rolling(period).mean()
    sigma = series.rolling(period).std()
    return mid, mid + n_std * sigma, mid - n_std * sigma


def _rsi_score(rsi: float) -> tuple[int, str]:
    if rsi < 25:
        return 3, f"RSI extreme oversold ({rsi:.1f})"
    if rsi < 35:
        return 2, f"RSI oversold ({rsi:.1f})"
    if rsi < 45:
        return 1, f"RSI mild bullish ({rsi:.1f})"
    if rsi > 75:
        return -3, f"RSI extreme overbought ({rsi:.1f})"
    if rsi > 65:
        return -2, f"RSI overbought ({rsi:.1f})"
    if rsi > 55:
        return -1, f"RSI mild bearish ({rsi:.1f})"
    return 0, ""


def _macd_score(macd_line: pd.Series, signal_line: pd.Series) -> tuple[int, str]:
    last_m, last_s = macd_line.iloc[-1], signal_line.iloc[-1]
    prev_m, prev_s = macd_line.iloc[-2], signal_line.iloc[-2]
    if prev_m < prev_s and last_m > last_s:
        return 2, "MACD bullish crossover"
    if prev_m > prev_s and last_m < last_s:
        return -2, "MACD bearish crossover"
    if last_m > last_s:
        return 1, "MACD above signal (bullish momentum)"
    if last_m < last_s:
        return -1, "MACD below signal (bearish momentum)"
    return 0, ""


def _ema_score(price: float, e20: float, e50: float, e200: float) -> tuple[int, str]:
    if price > e20 > e50 > e200:
        return 2, "strong uptrend (price > EMA20 > EMA50 > EMA200)"
    if price > e20 > e50:
        return 1, "uptrend (price > EMA20 > EMA50)"
    if price < e20 < e50 < e200:
        return -2, "strong downtrend (price < EMA20 < EMA50 < EMA200)"
    if price < e20 < e50:
        return -1, "downtrend (price < EMA20 < EMA50)"
    return 0, ""


def _bb_score(price: float, upper: float, lower: float) -> tuple[int, str]:
    if np.isnan(upper) or np.isnan(lower):
        return 0, ""
    if price < lower:
        return 2, f"price below lower BB ({price:.2f} < {lower:.2f})"
    if price > upper:
        return -2, f"price above upper BB ({price:.2f} > {upper:.2f})"
    bb_range = upper - lower
    if bb_range > 0:
        pct = (price - lower) / bb_range
        if pct < 0.2:
            return 1, "price near lower BB (approaching oversold)"
        if pct > 0.8:
            return -1, "price near upper BB (approaching overbought)"
    return 0, ""


def _volume_score(volume: pd.Series, current_score: float) -> tuple[int, str]:
    if len(volume) < 20:
        return 0, ""
    avg_vol = float(volume.iloc[-20:].mean())
    last_vol = float(volume.iloc[-1])
    if avg_vol <= 0:
        return 0, ""
    ratio = last_vol / avg_vol
    if ratio > 1.5 and current_score > 0:
        return 1, f"volume spike confirms move ({ratio:.1f}x avg)"
    if ratio > 1.5 and current_score < 0:
        return -1, f"volume spike confirms move ({ratio:.1f}x avg)"
    return 0, ""


def detect_regime(df: pd.DataFrame) -> dict:
    close = df["c"].astype(float)
    if len(close) < 60:
        return {
            "regime": "range",
            "confidence": 0.25,
            "trend_strength": 0.0,
            "realized_vol": 0.0,
        }

    ema20 = _ema(close, 20).iloc[-1]
    ema50 = _ema(close, 50).iloc[-1]
    price = float(close.iloc[-1])
    trend_strength = ((ema20 - ema50) / price) if price else 0.0
    realized_vol = float(close.pct_change().dropna().tail(20).std())

    trend_threshold = config.TREND_STRENGTH_THRESHOLD
    vol_threshold = config.HIGH_VOL_THRESHOLD

    if trend_strength >= trend_threshold:
        regime = "bull_trend"
        confidence = min(1.0, abs(trend_strength) / (trend_threshold * 2.0))
    elif trend_strength <= -trend_threshold:
        regime = "bear_trend"
        confidence = min(1.0, abs(trend_strength) / (trend_threshold * 2.0))
    elif realized_vol >= vol_threshold:
        regime = "high_volatility"
        confidence = min(1.0, realized_vol / (vol_threshold * 2.0))
    else:
        regime = "range"
        confidence = 0.6

    return {
        "regime": regime,
        "confidence": round(confidence, 4),
        "trend_strength": round(float(trend_strength), 6),
        "realized_vol": round(realized_vol, 6),
    }


def _score_components(close: pd.Series, volume: pd.Series, df: pd.DataFrame) -> tuple[dict[str, int], dict[str, str], dict]:
    rsi_series = _rsi(close)
    macd_line, signal_line = _macd(close)
    ema20 = _ema(close, 20)
    ema50 = _ema(close, 50)
    ema200 = _ema(close, 200)
    _, bb_upper, bb_lower = _bollinger(close)

    last_rsi = float(rsi_series.iloc[-1])
    price = float(close.iloc[-1])

    component_scores: dict[str, int] = {}
    component_reasons: dict[str, str] = {}

    for name, (score, reason) in {
        "rsi": _rsi_score(last_rsi),
        "macd": _macd_score(macd_line, signal_line),
        "ema": _ema_score(price, float(ema20.iloc[-1]), float(ema50.iloc[-1]), float(ema200.iloc[-1])),
        "bb": _bb_score(price, float(bb_upper.iloc[-1]), float(bb_lower.iloc[-1])),
    }.items():
        if score:
            component_scores[name] = score
            component_reasons[name] = reason

    regime = detect_regime(df)
    base_score = float(sum(component_scores.values()))
    vol_score, vol_reason = _volume_score(volume, base_score)
    if vol_score:
        component_scores["volume"] = vol_score
        component_reasons["volume"] = vol_reason
    return component_scores, component_reasons, regime


def compute_signals(bars: list[dict]) -> dict:
    empty = {
        "signal": "hold",
        "reason": "not enough data",
        "score": 0,
        "rsi": None,
        "price": None,
        "atr": None,
        "event_score": 0,
        "event_reasons": [],
        "regime": "range",
        "regime_confidence": 0.0,
    }
    if len(bars) < 30:
        return empty

    df = pd.DataFrame(bars)
    for col in ("h", "l", "v"):
        if col not in df.columns:
            df[col] = df["c"]
    close = df["c"].astype(float)
    volume = df["v"].astype(float)

    component_scores, component_reasons, regime = _score_components(close, volume, df)
    weights = _BASE_WEIGHTS
    if config.ENABLE_REGIME_SWITCHING:
        weights = _REGIME_WEIGHTS.get(regime["regime"], _BASE_WEIGHTS)

    weighted_score = 0.0
    reasons: list[str] = []
    for name, raw in component_scores.items():
        weight = float(weights.get(name, 1.0))
        weighted_score += raw * weight
        reasons.append(f"{component_reasons[name]} [{name} x{weight:.2f}]")

    score = int(round(weighted_score))
    t = config.SIGNAL_THRESHOLD
    if score >= t:
        signal = "buy"
    elif score <= -t:
        signal = "sell"
    else:
        signal = "hold"

    atr_series = _atr(df)
    last_atr = float(atr_series.iloc[-1]) if not np.isnan(atr_series.iloc[-1]) else None
    last_rsi = float(_rsi(close).iloc[-1])
    price = float(close.iloc[-1])

    return {
        "signal": signal,
        "score": score,
        "rsi": round(last_rsi, 2),
        "price": round(price, 2),
        "atr": round(last_atr, 4) if last_atr else None,
        "reason": "; ".join(reasons) if reasons else "no strong signal",
        "event_score": 0,
        "event_reasons": [],
        "regime": regime["regime"],
        "regime_confidence": regime["confidence"],
        "regime_trend_strength": regime["trend_strength"],
        "regime_realized_vol": regime["realized_vol"],
    }


def apply_event_score(quant: dict, event: dict) -> dict:
    no_signal = "no strong signal"
    combined = quant["score"] + event["event_score"]
    base = [] if quant["reason"] == no_signal else [quant["reason"]]
    all_reasons = base + event["event_reasons"]

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
        "reason": "; ".join(all_reasons) if all_reasons else no_signal,
    }
