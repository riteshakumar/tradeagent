from __future__ import annotations

import numpy as np
import pandas as pd

import config

# ---------------------------------------------------------------------------
# Regime weight tables (used only in neutral/mixed mode)
# ---------------------------------------------------------------------------
_REGIME_WEIGHTS = {
    "bull_trend":     {"rsi": 0.75, "macd": 1.25, "ema": 1.50, "bb": 0.75, "volume": 1.0, "momentum": 1.25, "breakout": 1.50, "supertrend": 1.50, "vwap": 1.0},
    "bear_trend":     {"rsi": 1.20, "macd": 1.00, "ema": 0.80, "bb": 1.20, "volume": 1.1, "momentum": 0.90, "breakout": 1.10, "supertrend": 1.00, "vwap": 1.0},
    "range":          {"rsi": 1.20, "macd": 0.80, "ema": 0.70, "bb": 1.40, "volume": 1.0, "momentum": 0.80, "breakout": 1.00, "supertrend": 0.70, "vwap": 1.0},
    "high_volatility":{"rsi": 0.90, "macd": 0.80, "ema": 0.80, "bb": 1.30, "volume": 1.2, "momentum": 1.00, "breakout": 1.20, "supertrend": 1.00, "vwap": 1.0},
}
_BASE_WEIGHTS = {k: 1.0 for k in ("rsi", "macd", "ema", "bb", "volume", "momentum", "breakout", "supertrend", "vwap")}
_INTRADAY_TIMEFRAMES = {"1Min", "5Min", "15Min", "1Hour"}
_TIMEFRAME_MINUTES = {
    "1Min": 1,
    "5Min": 5,
    "15Min": 15,
    "1Hour": 60,
    "1Day": 390,
}
_PERIODS_PER_DAY = {
    "1Min": 390.0,
    "5Min": 78.0,
    "15Min": 26.0,
    "1Hour": 6.5,
    "1Day": 1.0,
}
_TIMEFRAME_SIGNAL_THRESHOLD_OFFSET = {
    "1Min": 1,
    "5Min": 0,   # ATR-based SL + 2R partial target replaces threshold as noise filter
    "15Min": 0,
    "1Hour": 0,
    "1Day": -1,
}

# ADX thresholds for hard mode switching
_ADX_TREND_MIN = 25   # above this → trending mode (EMA/MACD/Supertrend/Breakout)
_ADX_RANGE_MAX = 20   # below this → ranging mode (RSI/BB only)


def _infer_timeframe(df: pd.DataFrame) -> str:
    if "t" not in df.columns or len(df) < 2:
        return "1Day"
    try:
        ts = pd.to_datetime(df["t"]).sort_values()
        deltas = ts.diff().dropna().dt.total_seconds().div(60.0)
        if deltas.empty:
            return "1Day"
        median_minutes = float(deltas.median())
        if median_minutes <= 2:
            return "1Min"
        if median_minutes <= 10:
            return "5Min"
        if median_minutes <= 30:
            return "15Min"
        if median_minutes <= 180:
            return "1Hour"
    except Exception:
        pass
    return "1Day"


def _resolve_timeframe(timeframe: str | None, df: pd.DataFrame) -> str:
    if timeframe in _TIMEFRAME_MINUTES:
        return timeframe
    return _infer_timeframe(df)


def _is_intraday_timeframe(timeframe: str) -> bool:
    return timeframe in _INTRADAY_TIMEFRAMES


def _resolve_signal_threshold(timeframe: str, threshold: int | None) -> int:
    if threshold is not None:
        return int(threshold)
    base = int(config.SIGNAL_THRESHOLD)
    adjusted = base + _TIMEFRAME_SIGNAL_THRESHOLD_OFFSET.get(timeframe, 0)
    return max(1, min(10, adjusted))


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

    Implementation uses raw numpy arrays for the inner loop (pandas iloc in a loop is
    ~50× slower than numpy array indexing on the same element access pattern).
    """
    close_arr = df["c"].astype(float).values
    hl2 = ((df["h"].astype(float) + df["l"].astype(float)) / 2.0).values
    atr_s = _atr(df, period)
    idx = df.index

    upper_arr = hl2 + multiplier * atr_s.values
    lower_arr = hl2 - multiplier * atr_s.values
    direction_arr = np.ones(len(close_arr), dtype=np.int8)
    st_arr = np.full(len(close_arr), np.nan)

    for i in range(1, len(close_arr)):
        prev_close = close_arr[i - 1]
        # Tighten bands: don't widen the channel when price moves in trend direction
        if prev_close <= upper_arr[i - 1]:
            upper_arr[i] = min(upper_arr[i], upper_arr[i - 1])
        if prev_close >= lower_arr[i - 1]:
            lower_arr[i] = max(lower_arr[i], lower_arr[i - 1])
        # Flip direction on confirmed breakout
        prev_dir = direction_arr[i - 1]
        if prev_dir == -1 and close_arr[i] > upper_arr[i - 1]:
            direction_arr[i] = 1
        elif prev_dir == 1 and close_arr[i] < lower_arr[i - 1]:
            direction_arr[i] = -1
        else:
            direction_arr[i] = prev_dir
        st_arr[i] = lower_arr[i] if direction_arr[i] == 1 else upper_arr[i]

    return pd.Series(st_arr, index=idx), pd.Series(direction_arr, index=idx)


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


def _bb_score(price: float, upper: float, lower: float, bb_width_pct: float | None = None, atr_pct: float | None = None) -> tuple[int, str]:
    """Bollinger Band score with ATR-relative squeeze filter."""
    if np.isnan(upper) or np.isnan(lower):
        return 0, ""
    if bb_width_pct is not None:
        # ATR-relative squeeze: BB width < 0.8× ATR means bands narrower than typical range.
        # Fixed 2% threshold was too coarse — high-priced stocks ($400+) have wider ATR-pct.
        squeeze_thresh = (atr_pct * 0.8) if (atr_pct is not None and atr_pct > 0) else 0.02
        if bb_width_pct < squeeze_thresh:
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
    Filters df to the current session (last date) before computing VWAP
    to avoid cross-day cumsum contamination.
    """
    if len(df) < 5:
        return 0, ""
    # Restrict to current trading session so cumsum resets daily
    if "t" in df.columns:
        try:
            ts = pd.to_datetime(df["t"])
            last_date = ts.iloc[-1].date()
            session_df = df[ts.dt.date == last_date].copy()
            if len(session_df) >= 5:
                df = session_df
        except Exception:
            pass
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


# Timeframe-appropriate ROC thresholds for momentum scoring.
# 3% in 5 bars is rare at 15Min (75 min); trending moves at 0.5-1%/bar never scored.
# 1Day: 3% in 5 days is a genuine momentum move — keep high.
_MOMENTUM_ROC_THRESHOLDS: dict[str, float] = {
    "1Min": 0.5, "5Min": 1.5, "15Min": 1.5, "1Hour": 2.0, "1Day": 3.0
}


def _momentum_score(close: pd.Series, period: int = 5, timeframe: str = "1Day") -> tuple[int, str]:
    """5-period ROC momentum. Threshold adapts to timeframe — lower for intraday."""
    if len(close) < period + 1:
        return 0, ""
    past_price = float(close.iloc[-(period + 1)])
    current_price = float(close.iloc[-1])
    if past_price <= 0:
        return 0, ""
    roc = (current_price - past_price) / past_price * 100
    roc_thresh = _MOMENTUM_ROC_THRESHOLDS.get(timeframe, 3.0)
    if roc >= roc_thresh:
        return 1, f"bullish momentum ROC({period})={roc:.1f}% (thresh={roc_thresh}%)"
    if roc <= -roc_thresh:
        return -1, f"bearish momentum ROC({period})={roc:.1f}% (thresh={roc_thresh}%)"
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

def detect_regime(df: pd.DataFrame, timeframe: str = "1Day") -> dict:
    close = df["c"].astype(float)
    if len(close) < 60:
        return {"regime": "range", "confidence": 0.25, "trend_strength": 0.0, "realized_vol": 0.0}

    ema20 = _ema(close, 20).iloc[-1]
    ema50 = _ema(close, 50).iloc[-1]
    price = float(close.iloc[-1])
    trend_strength = ((ema20 - ema50) / price) if price else 0.0
    # 60-bar window: 3 trading days at 15Min, 60 days at 1Day — stable regime detection.
    # 20-bar was 1 day at 15Min; a single volatile day flipped regime and cut position size.
    bar_vol = float(close.pct_change().dropna().tail(60).std())
    realized_vol = bar_vol * (_PERIODS_PER_DAY.get(timeframe, 1.0) ** 0.5)

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
    timeframe: str = "1Day",
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

    # ATR for BB squeeze filter (ATR-relative threshold replaces fixed 2%)
    atr_series = _atr(df)
    last_atr   = float(atr_series.iloc[-1]) if not np.isnan(atr_series.iloc[-1]) else None
    atr_pct    = (last_atr / price) if (last_atr is not None and price > 0) else None

    adx_series = _adx(df)
    adx_value  = float(adx_series.iloc[-1]) if not np.isnan(adx_series.iloc[-1]) else 0.0

    # Supertrend
    st_line, st_dir = _supertrend(df)

    component_scores: dict[str, int] = {}
    component_reasons: dict[str, str] = {}

    # ------------------------------------------------------------------
    # Hard mode switching
    # ------------------------------------------------------------------
    if not config.ENABLE_REGIME_SWITCHING:
        for name, (score, reason) in {
            "rsi":        _rsi_score(last_rsi, prev_rsi),
            "macd":       _macd_score(macd_line, signal_line),
            "ema":        _ema_score(price, e20, e50, e200, e20_prev, e50_prev),
            "bb":         _bb_score(price, last_upper, last_lower, bb_width_pct, atr_pct),
            "supertrend": _supertrend_score(st_dir),
        }.items():
            if score:
                component_scores[name] = score
                component_reasons[name] = reason

        bo_score, bo_reason = _breakout_score(close, volume)
        if bo_score:
            component_scores["breakout"] = bo_score
            component_reasons["breakout"] = bo_reason

    elif adx_value >= _ADX_TREND_MIN:
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
            "bb":  _bb_score(price, last_upper, last_lower, bb_width_pct, atr_pct),
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
            "bb":         _bb_score(price, last_upper, last_lower, bb_width_pct, atr_pct),
            "supertrend": _supertrend_score(st_dir),
        }.items():
            if score:
                component_scores[name] = score
                component_reasons[name] = reason

        bo_score, bo_reason = _breakout_score(close, volume)
        if bo_score:
            component_scores["breakout"] = bo_score
            component_reasons["breakout"] = bo_reason

    # Momentum (always active) — threshold adapts to timeframe
    mom_score, mom_reason = _momentum_score(close, timeframe=timeframe)
    if mom_score:
        component_scores["momentum"] = mom_score
        component_reasons["momentum"] = mom_reason

    # VWAP (only for intraday timeframes)
    if is_intraday:
        vw_score, vw_reason = _vwap_score(df)
        if vw_score:
            component_scores["vwap"] = vw_score
            component_reasons["vwap"] = vw_reason

    regime     = detect_regime(df, timeframe=timeframe)
    base_score = float(sum(component_scores.values()))
    vol_score, vol_reason = _volume_score(volume, base_score)
    if vol_score:
        component_scores["volume"] = vol_score
        component_reasons["volume"] = vol_reason

    # Agreement check moved to callers — they apply 0.5× soft penalty instead of hard zero.
    return component_scores, component_reasons, regime, adx_value


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def compute_signals(
    bars: list[dict],
    market_trend: int = 0,
    earnings_soon: bool = False,
    threshold: int | None = None,
    timeframe: str | None = None,
    disabled_components: set[str] | None = None,
) -> dict:
    """
    Compute trading signals from OHLCV bars.

    Args:
        bars: List of bar dicts with keys c, h, l, v, t.
        market_trend: +1 = SPY above EMA200 (bull), -1 = bear, 0 = unknown.
                      buy signals suppressed when -1.
        earnings_soon: If True, suppress buy signals (earnings risk window).
        threshold: Optional signal threshold override. Defaults to
                   config.SIGNAL_THRESHOLD when not provided.
        timeframe: Optional timeframe override. Used for intraday detection,
                   regime volatility normalisation, and default threshold tuning.
    """
    empty = {
        "signal": "hold", "reason": "not enough data", "score": 0,
        "rsi": None, "price": None, "atr": None, "adx": None,
        "event_score": 0, "event_reasons": [],
        "regime": "range", "regime_confidence": 0.0,
        "market_trend": market_trend,
        "timeframe": timeframe or "1Day",
        "ema200_ready": False,
    }
    if len(bars) < 30:
        return empty

    df = pd.DataFrame(bars)
    for col in ("h", "l", "v"):
        if col not in df.columns:
            df[col] = df["c"]
    close  = df["c"].astype(float)
    volume = df["v"].astype(float)
    resolved_timeframe = _resolve_timeframe(timeframe, df)
    is_intraday = _is_intraday_timeframe(resolved_timeframe)

    component_scores, component_reasons, regime, adx_value = _score_components(
        close,
        volume,
        df,
        timeframe=resolved_timeframe,
        is_intraday=is_intraday,
    )
    disabled = {str(name).strip().lower() for name in (disabled_components or set()) if str(name).strip()}
    # Soft agreement: 0.75× multiplier when indicators conflict instead of full zero-wipe.
    # Strong signals still clear threshold after reduction; weak mixed signals become hold.
    # 0.75× (was 0.5×): less aggressive — mixed signals are penalised but not killed.
    _agree_factor = 1.0 if _check_indicator_agreement(component_scores) else 0.75
    if disabled:
        component_scores = {name: score for name, score in component_scores.items() if name not in disabled}
        component_reasons = {name: reason for name, reason in component_reasons.items() if name not in disabled}
        if not _check_indicator_agreement(component_scores):
            _agree_factor = min(_agree_factor, 0.75)

    weights = _BASE_WEIGHTS
    if config.ENABLE_REGIME_SWITCHING:
        weights = _REGIME_WEIGHTS.get(regime["regime"], _BASE_WEIGHTS)

    weighted_score = 0.0
    reasons: list[str] = []
    for name, raw in component_scores.items():
        weight = float(weights.get(name, 1.0))
        weighted_score += raw * weight
        reasons.append(f"{component_reasons[name]} [{name} x{weight:.2f}]")
    if _agree_factor < 1.0:
        weighted_score *= _agree_factor
        reasons.append(f"[agreement penalty: ×{_agree_factor:.1f}]")

    # SPY bear-market penalty: raises effective threshold by 1 (soft, not hard block)
    # Hard block was killing dip-buy opportunities; _ema_score already penalises downtrends.
    if market_trend == -1:
        weighted_score -= 0.5
        reasons.append("[SPY bear penalty: -0.5]")

    score = int(round(weighted_score))
    t = _resolve_signal_threshold(resolved_timeframe, threshold)
    signal = "buy" if score >= t else ("sell" if score <= -t else "hold")

    # ------------------------------------------------------------------
    # Gate: Stock's own EMA200
    # NOTE: _ema_score already returns -1/-2 for downtrends.
    # Hard-blocking below EMA200 double-penalises oversold bounces where
    # RSI/BB both signal buy. Store ema200 info for reference only.
    # ------------------------------------------------------------------
    ema200_val = float(_ema(close, 200).iloc[-1])
    stock_price = float(close.iloc[-1])
    ema200_ready = len(close) >= 200 and not np.isnan(ema200_val)

    # ------------------------------------------------------------------
    # Gate: Earnings risk window (keep as hard block — earnings gaps are real)
    # ------------------------------------------------------------------
    if signal == "buy" and earnings_soon:
        signal = "hold"
        reasons.append("[buy suppressed: earnings period]")

    atr_series = _atr(df)
    last_atr   = float(atr_series.iloc[-1]) if not np.isnan(atr_series.iloc[-1]) else None
    last_rsi   = float(_rsi(close).iloc[-1])
    component_field_map = {
        "ema_score": "ema",
        "macd_score": "macd",
        "rsi_score": "rsi",
        "bb_score": "bb",
        "supertrend_score": "supertrend",
        "vwap_score": "vwap",
        "breakout_score": "breakout",
        "momentum_score": "momentum",
    }

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
        "timeframe":             resolved_timeframe,
        "market_trend":          market_trend,
        "earnings_soon":         earnings_soon,
        "ema200_ready":          ema200_ready,
        # Individual component scores — exposed for agent context
        **{field: component_scores.get(component, 0) for field, component in component_field_map.items()},
        "adx_score": 1 if adx_value >= _ADX_TREND_MIN else (-1 if 0 < adx_value < _ADX_RANGE_MAX else 0),
    }


def _vwap_full(df: pd.DataFrame) -> pd.Series:
    """Session-reset VWAP for every bar in df (recomputes from session start each day)."""
    close = df["c"].astype(float)
    volume = df["v"].astype(float)
    vwap = pd.Series(np.nan, index=df.index, dtype=float)
    if "t" in df.columns:
        try:
            dates = pd.to_datetime(df["t"]).dt.date
            for _date, grp in df.groupby(dates):
                idx = grp.index
                cum_tpv = (close.loc[idx] * volume.loc[idx]).cumsum()
                cum_vol = volume.loc[idx].cumsum().replace(0, np.nan)
                vwap.loc[idx] = cum_tpv / cum_vol
            return vwap
        except Exception:
            pass
    cum_tpv = (close * volume).cumsum()
    cum_vol = volume.cumsum().replace(0, np.nan)
    return cum_tpv / cum_vol


def precompute_series(df: pd.DataFrame, timeframe: str | None = None) -> dict:
    """
    Compute all indicator Series for the full df at once — O(n).
    Use with signal_at_index() for fast per-bar signal lookup.
    Replaces the O(n²) pattern of calling compute_signals(window[:i]) per bar.
    """
    close = df["c"].astype(float)
    volume = df["v"].astype(float)
    resolved_tf = _resolve_timeframe(timeframe, df)
    is_intraday = _is_intraday_timeframe(resolved_tf)
    periods_per_day = _PERIODS_PER_DAY.get(resolved_tf, 1.0)

    rsi_s = _rsi(close)
    macd_line, signal_line = _macd(close)
    ema20_s = _ema(close, 20)
    ema50_s = _ema(close, 50)
    ema200_s = _ema(close, 200)
    bb_mid, bb_upper, bb_lower = _bollinger(close)
    atr_s = _atr(df)
    adx_s = _adx(df)
    st_line, st_dir = _supertrend(df)  # has internal loop but runs once

    vol_avg20 = volume.rolling(20, min_periods=1).mean()
    mom_roc = close.pct_change(5) * 100                    # 5-period ROC %
    roll_high20 = close.shift(1).rolling(20).max()         # prior-20 high (excludes current)
    roll_low20 = close.shift(1).rolling(20).min()          # prior-20 low

    vwap_s = _vwap_full(df) if is_intraday else pd.Series(np.nan, index=df.index, dtype=float)

    # For regime detection per bar
    trend_strength_s = (ema20_s - ema50_s) / close.replace(0, np.nan)
    realized_vol_s = close.pct_change().rolling(60, min_periods=20).std() * (periods_per_day ** 0.5)

    return {
        "timeframe": resolved_tf,
        "is_intraday": is_intraday,
        "close": close, "volume": volume,
        "rsi": rsi_s,
        "macd_line": macd_line, "signal_line": signal_line,
        "ema20": ema20_s, "ema50": ema50_s, "ema200": ema200_s,
        "bb_upper": bb_upper, "bb_lower": bb_lower, "bb_mid": bb_mid,
        "atr": atr_s, "adx": adx_s,
        "st_dir": st_dir,
        "vol_avg20": vol_avg20,
        "mom_roc": mom_roc,
        "roll_high20": roll_high20, "roll_low20": roll_low20,
        "vwap": vwap_s,
        "trend_strength": trend_strength_s, "realized_vol": realized_vol_s,
    }


def signal_at_index(
    idx: int,
    pre: dict,
    market_trend: int = 0,
    earnings_soon: bool = False,
    threshold: int | None = None,
    disabled_components: set[str] | None = None,
) -> dict:
    """
    Compute trading signal for bar at idx using precomputed series from precompute_series().
    O(1) per bar vs O(n) for compute_signals(). Call precompute_series() once per df.
    """
    timeframe = pre["timeframe"]
    is_intraday = pre["is_intraday"]
    close = pre["close"]
    volume = pre["volume"]

    _empty = {
        "signal": "hold", "reason": "not enough data", "score": 0,
        "rsi": None, "price": None, "atr": None, "adx": None,
        "event_score": 0, "event_reasons": [], "regime": "range",
        "regime_confidence": 0.0, "market_trend": market_trend,
        "timeframe": timeframe, "ema200_ready": False,
        "regime_trend_strength": 0.0, "regime_realized_vol": 0.0,
        "ema_score": 0, "macd_score": 0, "rsi_score": 0, "bb_score": 0,
        "supertrend_score": 0, "vwap_score": 0, "breakout_score": 0,
        "momentum_score": 0, "adx_score": 0, "earnings_soon": earnings_soon,
    }
    if idx < 30 or idx >= len(close):
        return _empty

    price = float(close.iloc[idx])

    # --- Extract scalar values from precomputed series ---
    def _f(s: pd.Series) -> float:
        v = s.iloc[idx]
        return float(v) if not (v != v) else float("nan")  # handles NaN

    last_rsi = _f(pre["rsi"])
    prev_rsi = float(pre["rsi"].iloc[idx - 1]) if idx > 0 else None
    if prev_rsi != prev_rsi:
        prev_rsi = None  # NaN → None

    macd_slice = pre["macd_line"].iloc[idx - 1: idx + 1]
    sig_slice  = pre["signal_line"].iloc[idx - 1: idx + 1]

    e20  = _f(pre["ema20"]);  e50 = _f(pre["ema50"]);  e200 = _f(pre["ema200"])
    e20_prev = float(pre["ema20"].iloc[idx - 1]) if idx > 0 else None
    e50_prev = float(pre["ema50"].iloc[idx - 1]) if idx > 0 else None
    if e20_prev != e20_prev: e20_prev = None
    if e50_prev != e50_prev: e50_prev = None

    bb_upper = _f(pre["bb_upper"]); bb_lower = _f(pre["bb_lower"])
    bb_mid_v = _f(pre["bb_mid"])
    bb_width_pct = ((bb_upper - bb_lower) / bb_mid_v) if bb_mid_v and bb_mid_v > 0 and bb_mid_v == bb_mid_v else None

    atr_v  = _f(pre["atr"])
    atr_v  = atr_v if atr_v == atr_v else None
    # ATR-pct for BB squeeze filter (computed early — needed before bb_sc below)
    _bb_atr_pct = (atr_v / price) if (atr_v is not None and price > 0) else None

    adx_val = _f(pre["adx"])
    adx_val = adx_val if adx_val == adx_val else 0.0

    st_dir_slice = pre["st_dir"].iloc[max(0, idx - 1): idx + 1]

    last_vol  = float(volume.iloc[idx])
    avg_vol20 = _f(pre["vol_avg20"])
    avg_vol20 = avg_vol20 if avg_vol20 == avg_vol20 else 0.0

    mom_roc_v = _f(pre["mom_roc"])
    roll_high = _f(pre["roll_high20"]); roll_low = _f(pre["roll_low20"])

    vwap_v = _f(pre["vwap"])

    # --- Regime detection from precomputed scalars ---
    ts_v = _f(pre["trend_strength"]); rv_v = _f(pre["realized_vol"])
    ts_v = ts_v if ts_v == ts_v else 0.0; rv_v = rv_v if rv_v == rv_v else 0.0
    t_thresh = config.TREND_STRENGTH_THRESHOLD; v_thresh = config.HIGH_VOL_THRESHOLD
    if ts_v >= t_thresh:
        regime_name = "bull_trend"
        regime_conf = min(1.0, abs(ts_v) / (t_thresh * 2.0))
    elif ts_v <= -t_thresh:
        regime_name = "bear_trend"
        regime_conf = min(1.0, abs(ts_v) / (t_thresh * 2.0))
    elif rv_v >= v_thresh:
        regime_name = "high_volatility"
        regime_conf = min(1.0, rv_v / (v_thresh * 2.0))
    else:
        regime_name, regime_conf = "range", 0.6

    regime = {"regime": regime_name, "confidence": round(regime_conf, 4),
               "trend_strength": round(ts_v, 6), "realized_vol": round(rv_v, 6)}

    # --- Score components (reuse existing scoring functions with scalar/slice inputs) ---
    component_scores: dict[str, int] = {}
    component_reasons: dict[str, str] = {}
    disabled = {str(n).strip().lower() for n in (disabled_components or set()) if str(n).strip()}

    def _add(name: str, score: int, reason: str) -> None:
        if name not in disabled and score:
            component_scores[name] = score
            component_reasons[name] = reason

    rsi_sc, rsi_r = _rsi_score(last_rsi, prev_rsi)
    macd_sc, macd_r = _macd_score(macd_slice, sig_slice) if len(macd_slice) >= 2 else (0, "")
    ema_sc, ema_r = _ema_score(price, e20, e50, e200, e20_prev, e50_prev)
    bb_sc, bb_r = _bb_score(price, bb_upper, bb_lower, bb_width_pct, _bb_atr_pct)
    st_sc, st_r = _supertrend_score(st_dir_slice) if len(st_dir_slice) >= 2 else (0, "")

    # Breakout inline (needs precomputed rolling high/low)
    if roll_high == roll_high and roll_low == roll_low and avg_vol20 > 0:
        vol_ok = (last_vol / avg_vol20) >= 2.0
        if price > roll_high and vol_ok:
            bo_sc, bo_r = 2, f"20d breakout+vol ({price:.2f}>{roll_high:.2f}, {last_vol/avg_vol20:.1f}x)"
        elif price < roll_low and vol_ok:
            bo_sc, bo_r = -2, f"20d breakdown+vol ({price:.2f}<{roll_low:.2f}, {last_vol/avg_vol20:.1f}x)"
        else:
            bo_sc, bo_r = 0, ""
    else:
        bo_sc, bo_r = 0, ""

    # ADX mode switching
    if not config.ENABLE_REGIME_SWITCHING:
        _add("rsi", rsi_sc, rsi_r); _add("macd", macd_sc, macd_r)
        _add("ema", ema_sc, ema_r); _add("bb", bb_sc, bb_r)
        _add("supertrend", st_sc, st_r); _add("breakout", bo_sc, bo_r)
    elif adx_val >= _ADX_TREND_MIN:
        _add("macd", macd_sc, macd_r); _add("ema", ema_sc, ema_r)
        _add("supertrend", st_sc, st_r); _add("breakout", bo_sc, bo_r)
    elif 0 < adx_val < _ADX_RANGE_MAX:
        _add("rsi", rsi_sc, rsi_r); _add("bb", bb_sc, bb_r)
    else:
        _add("rsi", rsi_sc, rsi_r); _add("macd", macd_sc, macd_r)
        _add("ema", ema_sc, ema_r); _add("bb", bb_sc, bb_r)
        _add("supertrend", st_sc, st_r); _add("breakout", bo_sc, bo_r)

    # Momentum (always) — threshold adapts to timeframe
    _mom_thresh = _MOMENTUM_ROC_THRESHOLDS.get(timeframe, 3.0)
    if mom_roc_v == mom_roc_v:
        if mom_roc_v >= _mom_thresh:
            _add("momentum", 1, f"bullish momentum ROC(5)={mom_roc_v:.1f}% (thresh={_mom_thresh}%)")
        elif mom_roc_v <= -_mom_thresh:
            _add("momentum", -1, f"bearish momentum ROC(5)={mom_roc_v:.1f}% (thresh={_mom_thresh}%)")

    # VWAP (intraday only)
    if is_intraday and vwap_v == vwap_v and vwap_v > 0:
        diff_pct = (price - vwap_v) / vwap_v * 100
        if diff_pct > 0.5:
            _add("vwap", 1, f"price above VWAP by {diff_pct:.1f}%")
        elif diff_pct < -0.5:
            _add("vwap", -1, f"price below VWAP by {abs(diff_pct):.1f}%")

    # Soft agreement: 0.75× on weighted_score instead of zeroing all components.
    # Strong signals still clear threshold after reduction; weak mixed signals become hold.
    _agree_factor = 1.0 if _check_indicator_agreement(component_scores) else 0.75

    # Volume confirm (after agreement check — uses pre-agreement component sum)
    base_score = float(sum(component_scores.values()))
    if avg_vol20 > 0:
        ratio = last_vol / avg_vol20
        if ratio > 2.0 and base_score > 0:
            _add("volume", 1, f"volume surge confirms move ({ratio:.1f}x avg)")
        elif ratio > 2.0 and base_score < 0:
            _add("volume", -1, f"volume surge confirms move ({ratio:.1f}x avg)")

    # Regime weights
    weights = _BASE_WEIGHTS
    if config.ENABLE_REGIME_SWITCHING:
        weights = _REGIME_WEIGHTS.get(regime_name, _BASE_WEIGHTS)

    weighted_score = 0.0
    reasons: list[str] = []
    for name, raw in component_scores.items():
        w = float(weights.get(name, 1.0))
        weighted_score += raw * w
        reasons.append(f"{component_reasons[name]} [{name} x{w:.2f}]")
    if _agree_factor < 1.0:
        weighted_score *= _agree_factor
        reasons.append(f"[agreement penalty: ×{_agree_factor:.1f}]")

    if market_trend == -1:
        weighted_score -= 0.5
        reasons.append("[SPY bear penalty: -0.5]")

    score = int(round(weighted_score))
    t = _resolve_signal_threshold(timeframe, threshold)
    signal = "buy" if score >= t else ("sell" if score <= -t else "hold")

    if signal == "buy" and earnings_soon:
        signal = "hold"
        reasons.append("[buy suppressed: earnings period]")

    ema200_ready = idx >= 200 and e200 == e200

    component_field_map = {
        "ema_score": "ema", "macd_score": "macd", "rsi_score": "rsi",
        "bb_score": "bb", "supertrend_score": "supertrend", "vwap_score": "vwap",
        "breakout_score": "breakout", "momentum_score": "momentum",
    }

    return {
        "signal": signal, "score": score,
        "rsi":   round(last_rsi, 2) if last_rsi == last_rsi else None,
        "price": round(price, 2),
        "atr":   round(atr_v, 4) if atr_v is not None else None,
        "adx":   round(adx_val, 2) if adx_val else None,
        "reason": "; ".join(reasons) if reasons else "no strong signal",
        "event_score": 0, "event_reasons": [],
        "regime": regime_name, "regime_confidence": regime["confidence"],
        "regime_trend_strength": regime["trend_strength"],
        "regime_realized_vol": regime["realized_vol"],
        "timeframe": timeframe, "market_trend": market_trend,
        "earnings_soon": earnings_soon, "ema200_ready": ema200_ready,
        **{field: component_scores.get(comp, 0) for field, comp in component_field_map.items()},
        "adx_score": 1 if adx_val >= _ADX_TREND_MIN else (-1 if 0 < adx_val < _ADX_RANGE_MAX else 0),
    }


def regime_params(regime: str, market_trend: int, realized_vol: float = 0.0, is_crypto: bool = False) -> dict:
    """
    Map (stock regime, SPY trend, realized_vol) → per-bar trade profile.

    Returns:
        sl_mult_factor   – multiply base SL_ATR_MULT by this (e.g. 0.75 = tighter stop)
        size_factor      – multiply computed qty by this (0.0–1.0)
        threshold_offset – add to base threshold (positive = more selective)
        allow_short      – override shorts on/off (None = respect config default)

    Optimized via grid search (Apr 2026) across META/GOOGL/AMZN/MSFT/QQQ/AAPL:
      - Range regime dominates (89% of bars): wider SL + higher size maximises sharpe×return
      - Bear params: tighter SL + smaller size to limit drawdown in downturns
      - Bull_trend params: unchanged (only 2% of bars, no measurable difference)
    """
    # Crypto: high vol is normal — don't penalise size/threshold, just widen stop
    if is_crypto:
        if regime == "bear_trend":
            return {"sl_mult_factor": 2.0, "size_factor": 0.7, "threshold_offset": 0, "allow_short": False}
        if regime == "bull_trend":
            return {"sl_mult_factor": 2.0, "size_factor": 1.0, "threshold_offset": 0, "allow_short": False}
        return {"sl_mult_factor": 2.0, "size_factor": 0.9, "threshold_offset": 0, "allow_short": False}

    # High-volatility regime: widen stop to absorb noise, cut size, raise bar
    if regime == "high_volatility" or realized_vol > 0.025:
        return {"sl_mult_factor": 1.5, "size_factor": 0.5, "threshold_offset": 1, "allow_short": False}

    # Bear trend on stock — SPY also bearish: tight stop, minimal size, allow shorts
    # Optimized: sl=0.5, sz=0.4 (vs original sl=0.75, sz=0.6)
    if regime == "bear_trend" and market_trend == -1:
        return {"sl_mult_factor": 0.5, "size_factor": 0.4, "threshold_offset": 1, "allow_short": True}

    # Bear trend on stock but SPY still bullish (stock-specific weakness): cautious
    # Optimized: sl=0.5, sz=0.44 (vs original sl=1.0, sz=0.7)
    if regime == "bear_trend":
        return {"sl_mult_factor": 0.5, "size_factor": 0.44, "threshold_offset": 1, "allow_short": False}

    # SPY bearish but stock not yet bear — defensive, allow shorts
    # Optimized: sl=0.5, sz=0.4 (vs original sl=0.75, sz=0.6)
    if market_trend == -1:
        return {"sl_mult_factor": 0.5, "size_factor": 0.4, "threshold_offset": 1, "allow_short": True}

    # Bull trend — let winners run (unchanged: only 2% of bars, params make no diff)
    if regime == "bull_trend":
        return {"sl_mult_factor": 1.25, "size_factor": 1.0, "threshold_offset": 0, "allow_short": False}

    # Sideways/range (dominant regime, 89% of bars) — wider SL + higher size
    # Optimized: sl=1.5, sz=1.1 (vs original sl=1.0, sz=0.9) — score +37%
    return {"sl_mult_factor": 1.5, "size_factor": 1.1, "threshold_offset": 0, "allow_short": False}


def detect_market_phase(spy_closes: list[float], lookback: int = 20) -> str:
    """
    Classify current market phase from recent SPY closes.
    Returns: 'bull' | 'bear' | 'volatile' | 'sideways'
    """
    if len(spy_closes) < lookback:
        return "sideways"
    arr = spy_closes[-lookback:]
    import numpy as _np
    returns = _np.diff(arr) / _np.array(arr[:-1])
    realized_vol = float(_np.std(returns) * _np.sqrt(252))
    ema_short = float(pd.Series(arr).ewm(span=10, adjust=False).mean().iloc[-1])
    ema_long  = float(pd.Series(arr).ewm(span=20, adjust=False).mean().iloc[-1])
    peak      = max(arr)
    drawdown  = (arr[-1] - peak) / peak if peak > 0 else 0.0

    if realized_vol > 0.30:        # annualized vol > 30%
        return "volatile"
    if arr[-1] < ema_short < ema_long or drawdown < -0.05:
        return "bear"
    if arr[-1] > ema_short > ema_long:
        return "bull"
    return "sideways"


def apply_event_score(quant: dict, event: dict, threshold: int | None = None) -> dict:
    no_signal = "no strong signal"
    combined  = quant["score"] + event["event_score"]
    base      = [] if quant["reason"] == no_signal else [quant["reason"]]
    all_reasons = base + event["event_reasons"]

    timeframe = str(quant.get("timeframe") or "1Day")
    t = _resolve_signal_threshold(timeframe, threshold)
    if combined >= t:
        signal = "buy"
    elif combined <= -t:
        signal = "sell"
    else:
        signal = "hold"

    if quant.get("earnings_soon") and signal == "buy":
        signal = "hold"

    return {
        **quant,
        "signal":        signal,
        "score":         combined,
        "event_score":   event["event_score"],
        "event_reasons": event["event_reasons"],
        "reason":        "; ".join(all_reasons) if all_reasons else no_signal,
    }
