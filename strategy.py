from __future__ import annotations

import numpy as np
import pandas as pd

import config

# ---------------------------------------------------------------------------
# Regime weight tables (used only in neutral/mixed mode)
# ---------------------------------------------------------------------------
_REGIME_WEIGHTS = {
    "bull_trend":     {"rsi": 0.75, "macd": 1.25, "ema": 1.50, "bb": 0.75, "volume": 1.0, "momentum": 1.25, "breakout": 1.50, "supertrend": 1.50, "vwap": 1.0},
    "bear_trend":     {"rsi": 0.75, "macd": 1.25, "ema": 1.50, "bb": 0.75, "volume": 1.0, "momentum": 1.25, "breakout": 1.50, "supertrend": 1.50, "vwap": 1.0},
    "range":          {"rsi": 1.20, "macd": 0.80, "ema": 0.70, "bb": 1.40, "volume": 1.0, "momentum": 0.80, "breakout": 1.00, "supertrend": 0.70, "vwap": 1.0},
    "high_volatility":{"rsi": 0.90, "macd": 0.80, "ema": 0.80, "bb": 1.30, "volume": 1.2, "momentum": 1.00, "breakout": 1.20, "supertrend": 1.00, "vwap": 1.0},
}
_BASE_WEIGHTS = {k: 1.0 for k in ("rsi", "macd", "ema", "bb", "volume", "momentum", "breakout", "supertrend", "vwap")}

# ADX thresholds for hard mode switching
_ADX_TREND_MIN = 25   # above this → trending mode (EMA/MACD/Supertrend/Breakout)
_ADX_RANGE_MAX = 20   # below this → ranging mode (RSI/BB only)


# ---------------------------------------------------------------------------
# Indicator calculations
# ---------------------------------------------------------------------------

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


def _adx(df: pd.DataFrame, period: int = 14) -> pd.Series:
    """Average Directional Index — measures trend strength (direction-agnostic)."""
    high = df["h"].astype(float)
    low = df["l"].astype(float)
    close = df["c"].astype(float)
    prev_high = high.shift(1)
    prev_low = low.shift(1)
    prev_close = close.shift(1)

    tr = pd.concat([high - low, (high - prev_close).abs(), (low - prev_close).abs()], axis=1).max(axis=1)
    dm_plus = high - prev_high
    dm_minus = prev_low - low
    dm_plus = dm_plus.where((dm_plus > dm_minus) & (dm_plus > 0), 0.0)
    dm_minus = dm_minus.where((dm_minus > dm_plus) & (dm_minus > 0), 0.0)

    atr_s = tr.ewm(com=period - 1, min_periods=period).mean()
    di_plus = 100 * dm_plus.ewm(com=period - 1, min_periods=period).mean() / atr_s.replace(0, np.nan)
    di_minus = 100 * dm_minus.ewm(com=period - 1, min_periods=period).mean() / atr_s.replace(0, np.nan)
    di_sum = (di_plus + di_minus).replace(0, np.nan)
    dx = 100 * (di_plus - di_minus).abs() / di_sum
    return dx.ewm(com=period - 1, min_periods=period).mean()


def _supertrend(df: pd.DataFrame, multiplier: float = 3.0, period: int = 10) -> tuple[pd.Series, pd.Series]:
    """
    Supertrend indicator: ATR-based adaptive trend line.
    Returns (supertrend_line, direction) where direction = +1 (bullish) or -1 (bearish).
    Cleaner than EMA stacking: flips only on confirmed breakouts above/below the band.
    """
    high = df["h"].astype(float)
    low = df["l"].astype(float)
    close = df["c"].astype(float)
    hl2 = (high + low) / 2.0
    atr_s = _atr(df, period)

    upper_band = hl2 + multiplier * atr_s
    lower_band = hl2 - multiplier * atr_s

    supertrend = pd.Series(np.nan, index=close.index)
    direction = pd.Series(1, index=close.index)

    for i in range(1, len(close)):
        prev_upper = upper_band.iloc[i - 1]
        prev_lower = lower_band.iloc[i - 1]
        prev_close = close.iloc[i - 1]
        prev_dir = direction.iloc[i - 1]

        # Tighten bands: don't widen the channel when price moves in trend direction
        cur_upper = upper_band.iloc[i]
        cur_lower = lower_band.iloc[i]
        if prev_close <= prev_upper:
            upper_band.iloc[i] = min(cur_upper, prev_upper)
        if prev_close >= prev_lower:
            lower_band.iloc[i] = max(cur_lower, prev_lower)

        # Flip direction on confirmed breakout
        if prev_dir == -1 and close.iloc[i] > upper_band.iloc[i - 1]:
            direction.iloc[i] = 1
        elif prev_dir == 1 and close.iloc[i] < lower_band.iloc[i - 1]:
            direction.iloc[i] = -1
        else:
            direction.iloc[i] = prev_dir

        supertrend.iloc[i] = lower_band.iloc[i] if direction.iloc[i] == 1 else upper_band.iloc[i]

    return supertrend, direction


def _vwap(df: pd.DataFrame) -> pd.Series:
    """
    Session VWAP from cumulative (price × volume) / cumulative volume.
    Uses the full bar window — for intraday use, caller should pass same-session bars.
    """
    close = df["c"].astype(float)
    volume = df["v"].astype(float)
    typical = close  # simplified: use close as typical price
    cum_tpv = (typical * volume).cumsum()
    cum_vol = volume.cumsum().replace(0, np.nan)
    return cum_tpv / cum_vol


# ---------------------------------------------------------------------------
# Scoring functions
# ---------------------------------------------------------------------------

def _rsi_score(rsi: float, prev_rsi: float | None = None) -> tuple[int, str]:
    """RSI with slope confirmation — oversold only bullish when turning up."""
    slope_up = prev_rsi is not None and rsi > prev_rsi
    slope_down = prev_rsi is not None and rsi < prev_rsi
    slope_known = prev_rsi is not None

    if rsi < 25:
        if slope_up:
            return 3, f"RSI extreme oversold + reversing up ({rsi:.1f}↑)"
        return 2 if not slope_known else 1, f"RSI extreme oversold {'(still falling) ' if slope_known else ''}({rsi:.1f})"
    if rsi < 35:
        if slope_up:
            return 2, f"RSI oversold + reversing up ({rsi:.1f}↑)"
        return 1 if not slope_known else 0, f"RSI oversold {'(still falling) ' if slope_known else ''}({rsi:.1f})"
    if rsi < 45:
        return 1, f"RSI mild bullish ({rsi:.1f})"
    if rsi > 75:
        if slope_down:
            return -3, f"RSI extreme overbought + reversing down ({rsi:.1f}↓)"
        return -2 if not slope_known else -1, f"RSI extreme overbought {'(still rising) ' if slope_known else ''}({rsi:.1f})"
    if rsi > 65:
        if slope_down:
            return -2, f"RSI overbought + reversing down ({rsi:.1f}↓)"
        return -1 if not slope_known else 0, f"RSI overbought {'(still rising) ' if slope_known else ''}({rsi:.1f})"
    if rsi > 55:
        return -1, f"RSI mild bearish ({rsi:.1f})"
    return 0, ""


def _macd_score(macd_line: pd.Series, signal_line: pd.Series) -> tuple[int, str]:
    """MACD with histogram expansion + zero-line context."""
    last_m, last_s = macd_line.iloc[-1], signal_line.iloc[-1]
    prev_m, prev_s = macd_line.iloc[-2], signal_line.iloc[-2]
    hist_curr = last_m - last_s
    hist_prev = prev_m - prev_s

    if prev_m < prev_s and last_m > last_s:
        return (3, "MACD bullish crossover above zero") if last_m > 0 else (2, "MACD bullish crossover below zero")
    if prev_m > prev_s and last_m < last_s:
        return (-3, "MACD bearish crossover below zero") if last_m < 0 else (-2, "MACD bearish crossover above zero")
    if last_m > last_s and hist_curr > hist_prev:
        return 1, f"MACD above signal + expanding ({hist_curr:.4f}↑)"
    if last_m < last_s and hist_curr < hist_prev:
        return -1, f"MACD below signal + expanding ({hist_curr:.4f}↓)"
    return 0, ""


def _ema_score(price: float, e20: float, e50: float, e200: float,
               e20_prev: float | None = None, e50_prev: float | None = None) -> tuple[int, str]:
    """EMA alignment with slope confirmation."""
    e20_rising  = e20_prev is None or e20 > e20_prev
    e50_rising  = e50_prev is None or e50 > e50_prev
    e20_falling = e20_prev is None or e20 < e20_prev
    e50_falling = e50_prev is None or e50 < e50_prev

    if price > e20 > e50 > e200:
        return (2, "strong uptrend (price>EMA20>EMA50>EMA200, EMAs rising)") if (e20_rising and e50_rising) \
            else (1, "uptrend aligned, flat EMAs")
    if price > e20 > e50:
        return 1, "uptrend (price > EMA20 > EMA50)"
    if price < e20 < e50 < e200:
        return (-2, "strong downtrend (price<EMA20<EMA50<EMA200, EMAs falling)") if (e20_falling and e50_falling) \
            else (-1, "downtrend aligned, flat EMAs")
    if price < e20 < e50:
        return -1, "downtrend (price < EMA20 < EMA50)"
    return 0, ""


def _bb_score(price: float, upper: float, lower: float, bb_width_pct: float | None = None) -> tuple[int, str]:
    """Bollinger Band score with squeeze filter."""
    if np.isnan(upper) or np.isnan(lower):
        return 0, ""
    if bb_width_pct is not None and bb_width_pct < 0.02:
        return 0, ""
    if price < lower:
        return 2, f"price below lower BB ({price:.2f} < {lower:.2f})"
    if price > upper:
        return -2, f"price above upper BB ({price:.2f} > {upper:.2f})"
    bb_range = upper - lower
    if bb_range > 0:
        pct = (price - lower) / bb_range
        if pct < 0.2:
            return 1, "price near lower BB"
        if pct > 0.8:
            return -1, "price near upper BB"
    return 0, ""


def _supertrend_score(direction: pd.Series, prev_direction: pd.Series | None = None) -> tuple[int, str]:
    """
    +2 = bullish flip (just turned up) or sustained bull trend
    +1 = sustained bull (no flip this bar)
    −2/−1 = bear equivalents
    Flips are stronger signals than continuation.
    """
    if len(direction) < 2:
        return 0, ""
    cur_dir  = int(direction.iloc[-1])
    prev_dir = int(direction.iloc[-2])

    if prev_dir == -1 and cur_dir == 1:
        return 2, "Supertrend flipped bullish ↑"
    if prev_dir == 1 and cur_dir == -1:
        return -2, "Supertrend flipped bearish ↓"
    if cur_dir == 1:
        return 1, "Supertrend bullish (above trend line)"
    if cur_dir == -1:
        return -1, "Supertrend bearish (below trend line)"
    return 0, ""


def _vwap_score(df: pd.DataFrame) -> tuple[int, str]:
    """
    +1 if price > VWAP (institutional net buying pressure)
    −1 if price < VWAP (institutional net selling pressure)
    Only meaningful for intraday bars; low weight on daily.
    """
    if len(df) < 5:
        return 0, ""
    vwap_series = _vwap(df)
    last_vwap = float(vwap_series.iloc[-1])
    price = float(df["c"].astype(float).iloc[-1])
    if np.isnan(last_vwap) or last_vwap <= 0:
        return 0, ""
    diff_pct = (price - last_vwap) / last_vwap * 100
    if diff_pct > 0.5:
        return 1, f"price above VWAP by {diff_pct:.1f}%"
    if diff_pct < -0.5:
        return -1, f"price below VWAP by {abs(diff_pct):.1f}%"
    return 0, ""


def _volume_score(volume: pd.Series, current_score: float) -> tuple[int, str]:
    """Volume surge (≥2× avg) confirms directional move."""
    if len(volume) < 20:
        return 0, ""
    avg_vol = float(volume.iloc[-20:].mean())
    last_vol = float(volume.iloc[-1])
    if avg_vol <= 0:
        return 0, ""
    ratio = last_vol / avg_vol
    if ratio > 2.0 and current_score > 0:
        return 1, f"volume surge confirms move ({ratio:.1f}x avg)"
    if ratio > 2.0 and current_score < 0:
        return -1, f"volume surge confirms move ({ratio:.1f}x avg)"
    return 0, ""


def _momentum_score(close: pd.Series, period: int = 5) -> tuple[int, str]:
    """5-period ROC momentum — only scores on significant moves (>3%)."""
    if len(close) < period + 1:
        return 0, ""
    past_price = float(close.iloc[-(period + 1)])
    current_price = float(close.iloc[-1])
    if past_price <= 0:
        return 0, ""
    roc = (current_price - past_price) / past_price * 100
    if roc >= 3.0:
        return 1, f"bullish momentum ROC({period})={roc:.1f}%"
    if roc <= -3.0:
        return -1, f"bearish momentum ROC({period})={roc:.1f}%"
    return 0, ""


def _breakout_score(close: pd.Series, volume: pd.Series, period: int = 20) -> tuple[int, str]:
    """
    20-day high/low breakout with ≥2× volume confirmation.
    Captures momentum before RSI/MACD catch up.
    """
    if len(close) < period + 1:
        return 0, ""
    prior_window = close.iloc[-(period + 1):-1]
    recent_high = float(prior_window.max())
    recent_low  = float(prior_window.min())
    current = float(close.iloc[-1])

    avg_vol  = float(volume.iloc[-20:].mean()) if len(volume) >= 20 else 0.0
    last_vol = float(volume.iloc[-1])
    vol_ok   = avg_vol > 0 and (last_vol / avg_vol) >= 2.0

    if current > recent_high and vol_ok:
        return 2, f"{period}d breakout+vol ({current:.2f}>{recent_high:.2f}, {last_vol/avg_vol:.1f}x)"
    if current < recent_low and vol_ok:
        return -2, f"{period}d breakdown+vol ({current:.2f}<{recent_low:.2f}, {last_vol/avg_vol:.1f}x)"
    return 0, ""


def _check_indicator_agreement(component_scores: dict[str, int]) -> bool:
    """Require ≥2 main indicators to agree directionally."""
    main = ["rsi", "macd", "ema", "bb", "breakout", "supertrend"]
    bullish = sum(1 for k in main if component_scores.get(k, 0) > 0)
    bearish = sum(1 for k in main if component_scores.get(k, 0) < 0)
    return bullish >= 2 or bearish >= 2


# ---------------------------------------------------------------------------
# Regime detection
# ---------------------------------------------------------------------------

def detect_regime(df: pd.DataFrame) -> dict:
    close = df["c"].astype(float)
    if len(close) < 60:
        return {"regime": "range", "confidence": 0.25, "trend_strength": 0.0, "realized_vol": 0.0}

    ema20 = _ema(close, 20).iloc[-1]
    ema50 = _ema(close, 50).iloc[-1]
    price = float(close.iloc[-1])
    trend_strength = ((ema20 - ema50) / price) if price else 0.0
    realized_vol   = float(close.pct_change().dropna().tail(20).std())

    trend_threshold = config.TREND_STRENGTH_THRESHOLD
    vol_threshold   = config.HIGH_VOL_THRESHOLD

    if trend_strength >= trend_threshold:
        regime, confidence = "bull_trend", min(1.0, abs(trend_strength) / (trend_threshold * 2.0))
    elif trend_strength <= -trend_threshold:
        regime, confidence = "bear_trend", min(1.0, abs(trend_strength) / (trend_threshold * 2.0))
    elif realized_vol >= vol_threshold:
        regime, confidence = "high_volatility", min(1.0, realized_vol / (vol_threshold * 2.0))
    else:
        regime, confidence = "range", 0.6

    return {
        "regime":       regime,
        "confidence":   round(confidence, 4),
        "trend_strength": round(float(trend_strength), 6),
        "realized_vol": round(realized_vol, 6),
    }


# ---------------------------------------------------------------------------
# Core scoring pipeline
# ---------------------------------------------------------------------------

def _score_components(
    close: pd.Series,
    volume: pd.Series,
    df: pd.DataFrame,
    is_intraday: bool = False,
) -> tuple[dict[str, int], dict[str, str], dict, float]:
    """
    Returns (component_scores, component_reasons, regime, adx_value).

    Hard mode switching based on ADX:
      ADX > 25 (trending)  → only trend-following indicators: EMA, MACD, Supertrend, Breakout
      ADX < 20 (ranging)   → only mean-reversion indicators: RSI, BB
      20 ≤ ADX ≤ 25        → all indicators active, weighted by regime
    """
    rsi_series    = _rsi(close)
    macd_line, signal_line = _macd(close)
    ema20_s = _ema(close, 20)
    ema50_s = _ema(close, 50)
    ema200_s = _ema(close, 200)
    bb_mid, bb_upper, bb_lower = _bollinger(close)

    last_rsi  = float(rsi_series.iloc[-1])
    prev_rsi  = float(rsi_series.iloc[-2]) if len(rsi_series) >= 2 else None
    price     = float(close.iloc[-1])
    e20       = float(ema20_s.iloc[-1])
    e50       = float(ema50_s.iloc[-1])
    e200      = float(ema200_s.iloc[-1])
    e20_prev  = float(ema20_s.iloc[-2]) if len(ema20_s) >= 2 else None
    e50_prev  = float(ema50_s.iloc[-2]) if len(ema50_s) >= 2 else None

    last_upper = float(bb_upper.iloc[-1])
    last_lower = float(bb_lower.iloc[-1])
    last_mid   = float(bb_mid.iloc[-1]) if not np.isnan(bb_mid.iloc[-1]) else None
    bb_width_pct = ((last_upper - last_lower) / last_mid) if last_mid and last_mid > 0 else None

    adx_series = _adx(df)
    adx_value  = float(adx_series.iloc[-1]) if not np.isnan(adx_series.iloc[-1]) else 0.0

    # Supertrend
    st_line, st_dir = _supertrend(df)

    component_scores: dict[str, int] = {}
    component_reasons: dict[str, str] = {}

    # ------------------------------------------------------------------
    # Hard mode switching
    # ------------------------------------------------------------------
    if adx_value >= _ADX_TREND_MIN:
        # TRENDING mode: trend-following only
        for name, (score, reason) in {
            "macd":       _macd_score(macd_line, signal_line),
            "ema":        _ema_score(price, e20, e50, e200, e20_prev, e50_prev),
            "supertrend": _supertrend_score(st_dir),
        }.items():
            if score:
                component_scores[name] = score
                component_reasons[name] = reason

        bo_score, bo_reason = _breakout_score(close, volume)
        if bo_score:
            component_scores["breakout"] = bo_score
            component_reasons["breakout"] = bo_reason

    elif adx_value > 0 and adx_value < _ADX_RANGE_MAX:
        # RANGING mode: mean-reversion only
        for name, (score, reason) in {
            "rsi": _rsi_score(last_rsi, prev_rsi),
            "bb":  _bb_score(price, last_upper, last_lower, bb_width_pct),
        }.items():
            if score:
                component_scores[name] = score
                component_reasons[name] = reason

    else:
        # NEUTRAL / UNKNOWN (20 ≤ ADX ≤ 25 or ADX not computed): all active
        for name, (score, reason) in {
            "rsi":        _rsi_score(last_rsi, prev_rsi),
            "macd":       _macd_score(macd_line, signal_line),
            "ema":        _ema_score(price, e20, e50, e200, e20_prev, e50_prev),
            "bb":         _bb_score(price, last_upper, last_lower, bb_width_pct),
            "supertrend": _supertrend_score(st_dir),
        }.items():
            if score:
                component_scores[name] = score
                component_reasons[name] = reason

        bo_score, bo_reason = _breakout_score(close, volume)
        if bo_score:
            component_scores["breakout"] = bo_score
            component_reasons["breakout"] = bo_reason

    # Momentum (always active)
    mom_score, mom_reason = _momentum_score(close)
    if mom_score:
        component_scores["momentum"] = mom_score
        component_reasons["momentum"] = mom_reason

    # VWAP (only for intraday timeframes)
    if is_intraday:
        vw_score, vw_reason = _vwap_score(df)
        if vw_score:
            component_scores["vwap"] = vw_score
            component_reasons["vwap"] = vw_reason

    regime     = detect_regime(df)
    base_score = float(sum(component_scores.values()))
    vol_score, vol_reason = _volume_score(volume, base_score)
    if vol_score:
        component_scores["volume"] = vol_score
        component_reasons["volume"] = vol_reason

    # Minimum indicator agreement: ≥2 main indicators must agree
    if not _check_indicator_agreement(component_scores):
        component_scores  = {}
        component_reasons = {}

    return component_scores, component_reasons, regime, adx_value


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def compute_signals(bars: list[dict], market_trend: int = 0, earnings_soon: bool = False) -> dict:
    """
    Compute trading signals from OHLCV bars.

    Args:
        bars: List of bar dicts with keys c, h, l, v, t.
        market_trend: +1 = SPY above EMA200 (bull), -1 = bear, 0 = unknown.
                      buy signals suppressed when -1.
        earnings_soon: If True, suppress buy signals (earnings risk window).
    """
    empty = {
        "signal": "hold", "reason": "not enough data", "score": 0,
        "rsi": None, "price": None, "atr": None, "adx": None,
        "event_score": 0, "event_reasons": [],
        "regime": "range", "regime_confidence": 0.0,
        "market_trend": market_trend,
    }
    if len(bars) < 30:
        return empty

    df = pd.DataFrame(bars)
    for col in ("h", "l", "v"):
        if col not in df.columns:
            df[col] = df["c"]
    close  = df["c"].astype(float)
    volume = df["v"].astype(float)

    # Determine if intraday: proxy = many bars but short total time span
    is_intraday = False
    if "t" in df.columns and len(df) >= 2:
        try:
            t0 = pd.to_datetime(df["t"].iloc[0])
            t1 = pd.to_datetime(df["t"].iloc[-1])
            total_hours = (t1 - t0).total_seconds() / 3600
            # If 50+ bars cover < 5 trading days worth of hours, it's intraday
            is_intraday = len(df) >= 50 and total_hours < (5 * 6.5)
        except Exception:
            pass

    component_scores, component_reasons, regime, adx_value = _score_components(close, volume, df, is_intraday)
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
    signal = "buy" if score >= t else ("sell" if score <= -t else "hold")

    # ------------------------------------------------------------------
    # Gate 1: SPY bear-market suppression
    # ------------------------------------------------------------------
    if market_trend == -1 and signal == "buy":
        signal = "hold"
        reasons.append("[buy suppressed: SPY below EMA200]")

    # ------------------------------------------------------------------
    # Gate 2: Stock's own EMA200 — don't buy in individual downtrend
    # ------------------------------------------------------------------
    ema200_val = float(_ema(close, 200).iloc[-1])
    stock_price = float(close.iloc[-1])
    if signal == "buy" and stock_price < ema200_val and not np.isnan(ema200_val):
        signal = "hold"
        reasons.append(f"[buy suppressed: price {stock_price:.2f} below own EMA200 {ema200_val:.2f}]")

    # ------------------------------------------------------------------
    # Gate 3: Earnings risk window
    # ------------------------------------------------------------------
    if signal == "buy" and earnings_soon:
        signal = "hold"
        reasons.append("[buy suppressed: earnings period]")

    atr_series = _atr(df)
    last_atr   = float(atr_series.iloc[-1]) if not np.isnan(atr_series.iloc[-1]) else None
    last_rsi   = float(_rsi(close).iloc[-1])

    return {
        "signal":  signal,
        "score":   score,
        "rsi":     round(last_rsi, 2),
        "price":   round(stock_price, 2),
        "atr":     round(last_atr, 4) if last_atr else None,
        "adx":     round(adx_value, 2) if adx_value else None,
        "reason":  "; ".join(reasons) if reasons else "no strong signal",
        "event_score":  0,
        "event_reasons": [],
        "regime":                regime["regime"],
        "regime_confidence":     regime["confidence"],
        "regime_trend_strength": regime["trend_strength"],
        "regime_realized_vol":   regime["realized_vol"],
        "market_trend":          market_trend,
        "earnings_soon":         earnings_soon,
        # Individual component scores — exposed for agent context
        **{k: component_scores.get(k, 0) for k in (
            "ema_score", "macd_score", "rsi_score", "bb_score",
            "supertrend_score", "vwap_score", "breakout_score",
            "momentum_score", "adx_score",
        )},
    }


def apply_event_score(quant: dict, event: dict) -> dict:
    no_signal = "no strong signal"
    combined  = quant["score"] + event["event_score"]
    base      = [] if quant["reason"] == no_signal else [quant["reason"]]
    all_reasons = base + event["event_reasons"]

    t = config.SIGNAL_THRESHOLD
    if combined >= t:
        signal = "buy"
    elif combined <= -t:
        signal = "sell"
    else:
        signal = "hold"

    if quant.get("market_trend") == -1 and signal == "buy":
        signal = "hold"

    return {
        **quant,
        "signal":        signal,
        "score":         combined,
        "event_score":   event["event_score"],
        "event_reasons": event["event_reasons"],
        "reason":        "; ".join(all_reasons) if all_reasons else no_signal,
    }
