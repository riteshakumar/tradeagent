"""
Backtester with:
  - SPY benchmark comparison
  - Walk-forward validation
  - Parameter grid search optimization
  - Realistic trade modeling (SL/TP, slippage, per-trade fees)
"""
from __future__ import annotations

import itertools
from bisect import bisect_left

import numpy as np
import pandas as pd

import broker
import config
import events
import risk
import strategy

_BT_LOOKBACK = {
    "1Min": 5,
    "5Min": 60,   # ~3 months: enough trades, avoids multi-year regime drift
    "15Min": 90,  # ~4.5 months
    "1Hour": 180, # ~9 months
    "1Day": 365,  # 1 year
}

_ANNUALIZATION_PERIODS = {
    "1Min": 252 * 390,
    "5Min": 252 * 78,
    "15Min": 252 * 26,
    "1Hour": 252 * 6.5,
    "1Day": 252,
}

_TIMEFRAME_RESAMPLE_FREQ = {
    "1Min": "1min",
    "5Min": "5min",
    "15Min": "15min",
    "1Hour": "1h",
    "1Day": "1D",
}
_TIMEFRAME_MINUTES = {
    "1Min": 1,
    "5Min": 5,
    "15Min": 15,
    "1Hour": 60,
    "1Day": 390,
}
_HIGHER_TF = {
    "1Min": "1Day",
    "5Min": "1Day",
    "15Min": "1Day",
    "1Hour": "1Day",
    # "1Day" intentionally omitted: no meaningful "higher" TF above daily in this system.
    # Using 1Hour as higher TF for daily caused 1Hour bear phases to block all daily buys.
}
_PEER_OVERRIDE = {
    "AAPL": ["MSFT", "GOOGL"], "MSFT": ["AAPL", "GOOGL"], "GOOGL": ["META", "MSFT"],
    "NVDA": ["AMD", "AVGO"],   "AMD":  ["NVDA", "INTC"],  "META": ["GOOGL", "SNAP"],
    "TSLA": ["GM", "RIVN"],    "JPM":  ["BAC", "GS"],     "BAC":  ["JPM", "WFC"],
    "XOM":  ["CVX", "COP"],    "AMZN": ["MSFT", "GOOGL"],
}
_MIN_TRADES_BY_TIMEFRAME = {
    "1Min": 20,
    "5Min": 12,
    "15Min": 8,
    "1Hour": 5,
    "1Day": 3,
}


def _execution_slippage_bps(
    price: float,
    side: str,
    slippage_bps: float,
    bar: pd.Series | None = None,
    qty: float = 0.0,
) -> float:
    del side  # Execution cost is direction-agnostic at the bps layer.
    total_bps = float(slippage_bps)
    if bar is None or price <= 0:
        return total_bps

    try:
        high = float(bar.get("h", price))
        low = float(bar.get("l", price))
        volume = max(0.0, float(bar.get("v", 0.0)))
    except Exception:
        return total_bps

    # Model a simple half-spread plus a volatility-dependent impact penalty.
    total_bps += 1.0
    range_bps = max(0.0, ((high - low) / price) * 10_000.0)
    total_bps += min(25.0, range_bps * 0.05)

    if qty > 0 and volume > 0:
        tradable = max(1.0, volume * 0.02)
        impact_ratio = min(1.0, float(qty) / tradable)
        impact_bps = 30.0 * impact_ratio
        if config.ENABLE_ORDER_SLICING and qty > config.ORDER_SLICE_MAX_QTY:
            slices = max(1, int(np.ceil(float(qty) / float(config.ORDER_SLICE_MAX_QTY))))
            impact_bps /= min(5, slices)
        total_bps += impact_bps
    return total_bps


def _apply_slippage(
    price: float,
    side: str,
    slippage_bps: float,
    bar: pd.Series | None = None,
    qty: float = 0.0,
) -> float:
    slip = _execution_slippage_bps(price, side, slippage_bps, bar=bar, qty=qty) / 10_000.0
    if side == "buy":
        return price * (1 + slip)
    return price * (1 - slip)


def _check_bar_exit(
    entry_price: float,
    peak_price: float,
    bar: pd.Series,
    stop_loss_pct: float,
    take_profit_pct: float,
    side: str = "long",
) -> tuple[float, str] | None:
    """
    Returns (exit_price, reason) if stop/TP hit intrabar.
    Stop is trailing: trails from peak_price (highest close since entry), not entry_price.
    This lets winners run before stopping out.
    Conservative ordering: stop checked before take-profit.
    """
    low = float(bar["l"])
    high = float(bar["h"])
    # Trailing stop: trail from highest point reached since entry
    if side == "short":
        stop_px = peak_price * (1 + stop_loss_pct) if stop_loss_pct > 0 else None
        take_px = entry_price * (1 - take_profit_pct) if take_profit_pct > 0 else None
        stop_hit = stop_px is not None and high >= stop_px
        take_hit = take_px is not None and low <= take_px
    else:
        stop_px = peak_price * (1 - stop_loss_pct) if stop_loss_pct > 0 else None
        take_px = entry_price * (1 + take_profit_pct) if take_profit_pct > 0 else None
        stop_hit = stop_px is not None and low <= stop_px
        take_hit = take_px is not None and high >= take_px

    if stop_hit and take_hit:
        return stop_px, "trailing_stop"
    if stop_hit:
        return stop_px, "trailing_stop"
    if take_hit:
        return take_px, "take_profit"
    return None


def _make_trade(
    symbol: str,
    entry_px: float,
    exit_px: float,
    qty: float,
    entry_date: str = "",
    exit_date: str = "",
    exit_reason: str = "signal_exit",
    fees: float = 0.0,
    side: str = "long",
) -> dict:
    gross = (exit_px - entry_px) * qty if side == "long" else (entry_px - exit_px) * qty
    pnl = gross - fees
    notional = qty * entry_px
    return {
        "symbol": symbol,
        "side": side,
        "entry": round(entry_px, 2),
        "exit": round(exit_px, 2),
        "qty": qty,
        "pnl": round(pnl, 2),
        "pnl_pct": round((pnl / notional) * 100, 2) if notional > 0 else 0.0,
        "entry_date": entry_date,
        "exit_date": exit_date,
        "exit_reason": exit_reason,
    }


def _mark_to_market_value(side: str, qty: float, price: float) -> float:
    if qty <= 0:
        return 0.0
    return qty * price if side == "long" else -qty * price


def _position_notional(qty: float, price: float) -> float:
    return abs(float(qty) * float(price))


def _equity_with_position(cash: float, side: str | None, qty: float, price: float) -> float:
    if not side or qty <= 0:
        return float(cash)
    return float(cash) + _mark_to_market_value(side, qty, price)


def _resolve_exit_fill(
    raw_exit_px: float,
    reason: str,
    bar: pd.Series,
    side: str,
    slippage_bps: float,
    qty: float,
) -> float:
    bar_open = float(bar.get("o", raw_exit_px))
    fill_px = float(raw_exit_px)
    if reason == "trailing_stop":
        if side == "long" and bar_open < raw_exit_px:
            fill_px = bar_open
        if side == "short" and bar_open > raw_exit_px:
            fill_px = bar_open
    elif reason == "take_profit":
        if side == "long" and bar_open > raw_exit_px:
            fill_px = bar_open
        if side == "short" and bar_open < raw_exit_px:
            fill_px = bar_open
    exit_side = "sell" if side == "long" else "buy"
    return _apply_slippage(fill_px, exit_side, slippage_bps, bar=bar, qty=qty)


def _account_snapshot(cash: float, equity: float) -> dict:
    buying_power = max(float(cash), float(equity))
    return {
        "equity": float(equity),
        "cash": float(cash),
        "buying_power": buying_power,
        "portfolio_value": float(equity),
    }


def _position_snapshot(symbol: str, side: str, qty: float, current_price: float, avg_entry: float) -> dict:
    market_value = _position_notional(qty, current_price)
    pnl = (current_price - avg_entry) * qty if side == "long" else (avg_entry - current_price) * qty
    pnl_pct = (pnl / (avg_entry * qty)) if avg_entry > 0 and qty > 0 else 0.0
    return {
        "symbol": symbol,
        "qty": float(qty),
        "side": side,
        "avg_entry": float(avg_entry),
        "current_price": float(current_price),
        "market_value": float(market_value),
        "unrealized_pnl": float(pnl),
        "unrealized_pnl_pct": float(pnl_pct),
    }


def _local_close_fetcher(close_history: dict[str, list[float]]):
    def _fetch(symbol: str, lookback_days: int) -> list[float]:
        closes = list(close_history.get(symbol.upper(), []))
        if lookback_days <= 0:
            return closes
        return closes[-lookback_days:]

    return _fetch


def _backtest_pre_trade_checks(
    symbol: str,
    side: str,
    price: float,
    account: dict,
    positions: list[dict],
    now: pd.Timestamp,
    last_order_at: dict[str, pd.Timestamp],
    close_history: dict[str, list[float]],
    atr: float | None = None,
    realized_vol: float | None = None,
    risk_manager: risk.RiskManager | None = None,
) -> tuple[bool, str, float]:
    if price <= 0:
        return False, "invalid price", 0.0

    last_ts = last_order_at.get(symbol.upper())
    if last_ts is not None:
        elapsed = (pd.Timestamp(now) - pd.Timestamp(last_ts)).total_seconds()
        if elapsed < float(config.ORDER_COOLDOWN_SEC):
            return False, "cooldown active", 0.0

    if not risk.check_position_size(price, account):
        return False, "share price exceeds max position size", 0.0
    if not risk.check_cash_buffer(account):
        return False, "cash below reserve buffer", 0.0
    if risk_manager is not None:
        drawdown_state = risk_manager.evaluate_drawdown(account)
        if drawdown_state["halted"]:
            return False, "drawdown halt active", 0.0
        daily_state = risk_manager.update_daily_loss_guard(account, now=pd.Timestamp(now).to_pydatetime())
        if daily_state["halted"]:
            return False, "daily loss stop active", 0.0

    qty = risk.compute_qty(price, account, atr=atr, realized_vol=realized_vol)
    if qty <= 0:
        return False, "qty resolved to zero", 0.0
    # Shorts receive cash at entry (proceeds) — no upfront cost, skip buying_power check.
    if side != "sell" and not risk.check_buying_power(price, qty, account):
        return False, "insufficient buying power", 0.0

    ok, reason = risk.check_sector_exposure(symbol, price, qty, positions, account)
    if not ok:
        return False, reason, 0.0

    ok, reason = risk.check_correlation_cap(
        symbol,
        positions,
        close_fetcher=_local_close_fetcher(close_history),
    )
    if not ok:
        return False, reason, 0.0

    return True, "ok", float(qty)


def _surrogate_agent_decision(
    signal: dict,
    threshold: int,
    for_exit: bool = False,
) -> dict:
    raw_score = int(signal.get("score") or 0)
    abs_score = abs(raw_score)
    regime_conf = float(signal.get("regime_confidence") or 0.0)
    sentiment = int(signal.get("sentiment_trend") or 0)
    peer_ok = bool(signal.get("peer_consensus", True))
    macro_day = bool(signal.get("macro_event_day", False))
    sig_name = str(signal.get("signal") or "hold")

    if not config.USE_AGENT:
        approved = abs_score >= threshold and sig_name in ("buy", "sell")
        return {
            "approved": approved,
            "reason": f"agent disabled — auto-{'approved' if approved else 'rejected'}",
            "size_multiplier": 1.0,
            "suggested_stop_pct": None,
        }

    approved = sig_name in ("buy", "sell") and abs_score >= threshold
    if sig_name == "buy" and sentiment < 0:
        approved = False
    if sig_name == "buy" and not peer_ok:
        approved = False

    if for_exit:
        if sig_name == "sell" and raw_score > threshold + 1 and regime_conf >= 0.5:
            approved = False
        if sig_name == "buy" and raw_score < -(threshold + 1) and regime_conf >= 0.5:
            approved = False

    # 0.07 per score level above threshold — was 0.12, which hit max size at barely-threshold+3.
    # New: score must be 7+ above threshold to reach 1.5× cap — reserved for genuine outliers.
    size_multiplier = 1.0 + min(0.5, 0.07 * max(0, abs_score - threshold + 1) + 0.2 * regime_conf)
    if macro_day:
        size_multiplier -= 0.10
    if sig_name == "buy" and sentiment > 0:
        size_multiplier += 0.10
    if sig_name == "buy" and sentiment < 0:
        size_multiplier -= 0.20
    size_multiplier = float(np.clip(size_multiplier, config.MIN_SIZE_MULTIPLIER, config.MAX_SIZE_MULTIPLIER))

    suggested_stop_pct = None
    if config.AGENT_DYNAMIC_STOPS:
        price = float(signal.get("price") or 0.0)
        atr = float(signal.get("atr") or 0.0)
        realized_vol = float(signal.get("regime_realized_vol") or 0.0)
        candidates: list[float] = []
        if price > 0 and atr > 0:
            candidates.append((1.5 * atr) / price)
        if realized_vol > 0:
            candidates.append(realized_vol * 2.5)
        if candidates:
            suggested_stop_pct = float(np.clip(np.mean(candidates), 0.02, 0.20))

    reason_bits = ["surrogate"]
    if macro_day:
        reason_bits.append("macro_day")
    if sentiment < 0 and sig_name == "buy":
        reason_bits.append("negative_sentiment")
    return {
        "approved": approved,
        "reason": ",".join(reason_bits),
        "size_multiplier": size_multiplier,
        "suggested_stop_pct": suggested_stop_pct,
    }


def _allocate_trade_fees(
    entry_fee_remaining: float,
    exit_fee: float,
    qty_exiting: float,
    position_qty_before_exit: float,
) -> tuple[float, float]:
    if position_qty_before_exit <= 0:
        return float(exit_fee), float(entry_fee_remaining)

    if qty_exiting >= position_qty_before_exit:
        entry_fee_alloc = float(entry_fee_remaining)
    else:
        entry_fee_alloc = float(entry_fee_remaining) * (float(qty_exiting) / float(position_qty_before_exit))

    next_entry_fee_remaining = max(0.0, float(entry_fee_remaining) - entry_fee_alloc)
    return entry_fee_alloc + float(exit_fee), next_entry_fee_remaining


def _compute_stats(
    trades: list[dict],
    initial_cash: float,
    final_equity: float,
    equity_curve: list[dict],
    timeframe: str = "1Day",
) -> dict:
    winning = [t for t in trades if t["pnl"] > 0]
    losing = [t for t in trades if t["pnl"] <= 0]
    total_loss = sum(t["pnl"] for t in losing)

    win_rate = (len(winning) / len(trades) * 100) if trades else 0
    avg_win = float(np.mean([t["pnl"] for t in winning])) if winning else 0.0
    avg_loss = float(np.mean([t["pnl"] for t in losing])) if losing else 0.0
    # None = all-winners (no losers) — avoids non-JSON-serialisable inf/string
    profit_factor: float | None = (
        round(abs(sum(t["pnl"] for t in winning) / total_loss), 2)
        if total_loss != 0 else None
    )

    eq_vals = [e["equity"] for e in equity_curve]
    if len(eq_vals) > 1:
        eq_arr = np.array(eq_vals, dtype=float)
        prev = eq_arr[:-1]
        rets = np.where(prev > 0, np.diff(eq_arr) / prev, 0.0)
        std_rets = float(np.std(rets))
        periods_per_year = float(_ANNUALIZATION_PERIODS.get(timeframe, _ANNUALIZATION_PERIODS["1Day"]))
        sharpe = float(np.mean(rets) / std_rets * np.sqrt(periods_per_year)) if std_rets > 0 else 0.0
        sharpe = sharpe if np.isfinite(sharpe) else 0.0
    else:
        sharpe = 0.0

    eq_series = pd.Series(eq_vals, dtype=float)
    if len(eq_series) > 0 and float(eq_series.max()) > 0:
        running_max = eq_series.cummax()
        dd_series = (running_max - eq_series) / running_max.replace(0, np.nan)
        max_dd = float(dd_series.max() * 100) if np.isfinite(dd_series.max()) else 0.0
    else:
        max_dd = 0.0

    return {
        "total_return_pct": round((final_equity - initial_cash) / initial_cash * 100, 2),
        "win_rate_pct": round(win_rate, 2),
        "avg_win": round(avg_win, 2),
        "avg_loss": round(avg_loss, 2),
        "profit_factor": profit_factor,  # None = no losing trades
        "sharpe": round(sharpe, 3),
        "max_drawdown_pct": round(max_dd, 2),
    }


def _signal_for_threshold(score: int, threshold: int) -> str:
    if score >= threshold:
        return "buy"
    if score <= -threshold:
        return "sell"
    return "hold"


def _prepare_df(bars: list[dict]) -> pd.DataFrame:
    df = pd.DataFrame(bars)
    df["c"] = df["c"].astype(float)
    df["h"] = df["h"].astype(float)
    df["l"] = df["l"].astype(float)
    df["o"] = df["o"].astype(float)
    df["v"] = df["v"].astype(float)
    df["t"] = pd.to_datetime(df["t"])
    return df.sort_values("t").reset_index(drop=True)


def _get_peers(symbol: str) -> list[str]:
    sym = symbol.upper()
    if sym in _PEER_OVERRIDE:
        return _PEER_OVERRIDE[sym]
    try:
        from screener import SECTOR_STOCKS

        for stocks in SECTOR_STOCKS.values():
            if sym in stocks:
                return [s for s in stocks if s != sym][:2]
    except Exception:
        pass
    return []


def _min_trades_for_timeframe(timeframe: str, n_bars: int) -> int:
    return max(_MIN_TRADES_BY_TIMEFRAME.get(timeframe, 3), max(1, int(n_bars * 0.005)))


def _resample_df(df: pd.DataFrame, timeframe: str) -> pd.DataFrame:
    freq = _TIMEFRAME_RESAMPLE_FREQ.get(timeframe)
    if not freq or df.empty:
        return pd.DataFrame(columns=["t", "o", "h", "l", "c", "v"])

    agg = {
        "o": "first",
        "h": "max",
        "l": "min",
        "c": "last",
        "v": "sum",
    }
    resampled = (
        df.set_index("t")
        .sort_index()
        .resample(freq, label="right", closed="right")
        .agg(agg)
        .dropna(subset=["o", "h", "l", "c"])
        .reset_index()
    )
    return resampled


def _build_signal_timeline(
    df: pd.DataFrame,
    timeframe: str,
    market_trend_by_date: dict[str, int] | None = None,
    threshold: int | None = None,
) -> dict[str, list]:
    times: list[pd.Timestamp] = []
    signals: list[str] = []
    for end_idx in range(30, len(df) + 1):
        window_df = df.iloc[:end_idx]
        ts = pd.Timestamp(window_df["t"].iloc[-1])
        bar_date = ts.strftime("%Y-%m-%d")
        mt = market_trend_by_date.get(bar_date, 0) if market_trend_by_date else 0
        sig = strategy.compute_signals(
            window_df.to_dict("records"),
            market_trend=mt,
            threshold=threshold,
            timeframe=timeframe,
        )
        times.append(ts)
        signals.append(sig["signal"])
    return {"times": times, "signals": signals}


def _lookup_timeline_before(timeline: dict[str, list] | None, ts: pd.Timestamp) -> str | None:
    if not timeline:
        return None
    times = timeline.get("times", [])
    if not times:
        return None
    idx = bisect_left(times, ts) - 1
    if idx < 0:
        return None
    return timeline["signals"][idx]


def _build_filter_context(
    symbol: str,
    timeframe: str,
    lookback_days: int,
    df: pd.DataFrame,
    market_trend_by_date: dict[str, int] | None = None,
) -> dict:
    context: dict[str, object] = {"timeframe": timeframe}

    if config.MULTI_TIMEFRAME_ENABLED:
        higher_tf = _HIGHER_TF.get(timeframe)
        if higher_tf and higher_tf != timeframe:
            higher_minutes = _TIMEFRAME_MINUTES.get(higher_tf, 0)
            current_minutes = _TIMEFRAME_MINUTES.get(timeframe, 0)
            try:
                if higher_minutes > current_minutes:
                    higher_df = _resample_df(df, higher_tf)
                else:
                    higher_df = _prepare_df(
                        broker.get_bars(symbol, timeframe=higher_tf, lookback_days=min(max(lookback_days, 90), 180))
                    )
                if len(higher_df) >= 30:
                    context["higher_tf_signal"] = _build_signal_timeline(
                        higher_df,
                        timeframe=higher_tf,
                        market_trend_by_date=market_trend_by_date,
                    )
            except Exception:
                pass

    if config.PEER_CHECK_ENABLED:
        peer_timelines: list[dict[str, list]] = []
        for peer in _get_peers(symbol):
            try:
                peer_df = _prepare_df(
                    broker.get_bars(peer, timeframe="1Day", lookback_days=min(max(lookback_days, 30), 365))
                )
                if len(peer_df) >= 30:
                    peer_timelines.append(
                        _build_signal_timeline(
                            peer_df,
                            timeframe="1Day",
                            market_trend_by_date=market_trend_by_date,
                        )
                    )
            except Exception:
                continue
        if peer_timelines:
            context["peer_daily_signals"] = peer_timelines

    return context


def _normalize_news_timestamp(value: object) -> pd.Timestamp | None:
    if value in (None, ""):
        return None
    ts = pd.to_datetime(value, utc=True, errors="coerce")
    if pd.isna(ts):
        return None
    return ts.tz_convert("UTC").tz_localize(None)


def _build_event_context(symbol: str, df: pd.DataFrame) -> dict:
    if not config.USE_AGENT or df.empty:
        return {}

    start_ts = pd.Timestamp(df["t"].iloc[0]) - pd.Timedelta(days=7)
    end_ts = pd.Timestamp(df["t"].iloc[-1]) + pd.Timedelta(days=1)
    try:
        raw_news = events.fetch_news_range(
            symbols=[symbol],
            start=start_ts.isoformat(),
            end=end_ts.isoformat(),
            sort="asc",
            max_items=max(100, min(600, len(df) * 3)),
        )
    except Exception:
        return {}

    stamped_news: list[tuple[pd.Timestamp, dict]] = []
    for item in raw_news:
        created_ts = _normalize_news_timestamp(item.get("created"))
        if created_ts is None:
            continue
        stamped_news.append((created_ts, item))

    if not stamped_news:
        return {}

    stamped_news.sort(key=lambda item: item[0])
    earnings_stamped = [
        (ts, item)
        for ts, item in stamped_news
        if events.has_earnings_news([item], as_of=item.get("created"), max_age_days=365.0)
    ]
    return {
        "news_times": [ts for ts, _ in stamped_news],
        "news": [item for _, item in stamped_news],
        "earnings_news_times": [ts for ts, _ in earnings_stamped],
        "earnings_news": [item for _, item in earnings_stamped],
    }


def _build_market_event_context(df: pd.DataFrame) -> dict:
    if df.empty:
        return {}
    start_ts = pd.Timestamp(df["t"].iloc[0]) - pd.Timedelta(days=7)
    end_ts = pd.Timestamp(df["t"].iloc[-1]) + pd.Timedelta(days=1)
    try:
        raw_news = events.fetch_news_range(
            keywords="inflation CPI Fed interest rates Federal Reserve FOMC Treasury yield war sanctions oil defense NATO",
            start=start_ts.isoformat(),
            end=end_ts.isoformat(),
            sort="asc",
            max_items=300,
        )
    except Exception:
        return {}

    stamped_news: list[tuple[pd.Timestamp, dict]] = []
    for item in raw_news:
        created_ts = _normalize_news_timestamp(item.get("created"))
        if created_ts is None:
            continue
        stamped_news.append((created_ts, item))
    stamped_news.sort(key=lambda item: item[0])
    return {
        "news_times": [ts for ts, _ in stamped_news],
        "news": [item for _, item in stamped_news],
    }


def _historical_news_before(
    event_context: dict[str, object] | None,
    ts: pd.Timestamp,
    time_key: str = "earnings_news_times",
    news_key: str = "earnings_news",
) -> list[dict]:
    if not event_context:
        return []
    news_times = event_context.get(time_key) or event_context.get("news_times") or []
    visible_news = event_context.get(news_key) or event_context.get("news") or []
    if not news_times or not visible_news:
        return []

    ts_value = pd.Timestamp(ts)
    if ts_value.tzinfo is not None:
        ts_value = ts_value.tz_convert("UTC").tz_localize(None)
    idx = bisect_left(news_times, ts_value)
    return list(visible_news[:idx])


def _build_daily_blacklist_map(event_context: dict[str, object], dates: list[str]) -> dict[str, bool]:
    if not event_context or not event_context.get("news"):
        return {}
    blacklist: dict[str, bool] = {}
    for date_str in dates:
        as_of = pd.Timestamp(f"{date_str} 00:00:00")
        visible_news = _historical_news_before(event_context, as_of, time_key="news_times", news_key="news")
        blacklist[date_str] = events.sentiment_trend_from_news(visible_news, as_of=as_of, max_age_days=7.0) < 0
    return blacklist


def _build_macro_day_map(market_context: dict[str, object], dates: list[str]) -> dict[str, bool]:
    macro_map: dict[str, bool] = {}
    for date_str in dates:
        day = pd.Timestamp(date_str).date()
        visible_news = _historical_news_before(market_context, pd.Timestamp(f"{date_str} 23:59:59"), time_key="news_times", news_key="news")
        macro_map[date_str] = events.is_high_impact_macro_day_for_date(day, news=visible_news)
    return macro_map


def _precompute_bar_signals(
    df: pd.DataFrame,
    symbol: str,
    timeframe: str,
    warmup: int,
    market_trend_by_date: dict[str, int] | None,
    filter_context: dict[str, object] | None,
    event_context: dict[str, object] | None,
    market_event_context: dict[str, object] | None,
    disabled_components: set[str] | None = None,
) -> list[dict | None]:
    """
    Pre-compute threshold-independent signal data for every bar in df.
    Returns a list where index i holds a dict (or None for warmup bars) with:
      score            – combined quant+event score (int)
      gate_blocked     – True when EMA200/SPY/earnings gate suppressed the signal
      filter_blocked   – True when context filters (peer/higher-tf/etc.) suppressed it
      + auxiliary fields needed by surrogate decision and position sizing
    """
    results: list[dict | None] = [None] * len(df)
    fc = dict(filter_context or {})
    date_strings = df["t"].dt.strftime("%Y-%m-%d").tolist()
    if "daily_blacklist" not in fc:
        fc["daily_blacklist"] = _build_daily_blacklist_map(event_context or {}, sorted(set(date_strings)))
    if "macro_day" not in fc:
        fc["macro_day"] = _build_macro_day_map(market_event_context or {}, sorted(set(date_strings)))

    # Vectorised indicator pass: compute all series once on the full df (O(n) total).
    # signal_at_index() then reads values at a given index in O(1).
    # Supertrend is causal (direction[i] only depends on bars 0..i), so there is no
    # look-ahead bias from using the full-df precomputed series.
    _pre = strategy.precompute_series(df, timeframe=timeframe)

    # Per-day event score cache — news barely changes within a day for intraday TFs.
    # Reduces events.get_historical_event_score calls from n_bars → n_days (78× for 5Min).
    _day_event_cache: dict[str, dict] = {}

    for i in range(warmup, len(df)):
        bar = df.iloc[i]
        bar_ts = pd.Timestamp(bar["t"])
        bar_date = bar_ts.strftime("%Y-%m-%d")
        mt = market_trend_by_date.get(bar_date, 0) if market_trend_by_date else 0

        if bar_date not in _day_event_cache:
            sym_news = _historical_news_before(event_context, bar_ts, time_key="news_times", news_key="news")
            earn_news = _historical_news_before(event_context, bar_ts, time_key="earnings_news_times", news_key="earnings_news")
            if not sym_news:
                sym_news = list(earn_news)
            mkt_news = _historical_news_before(market_event_context, bar_ts, time_key="news_times", news_key="news")
            es_flag = events.is_earnings_period_from_news(earn_news, as_of=bar["t"]) if earn_news else False
            ev = events.get_historical_event_score(
                symbol, sym_news, as_of=bar["t"],
                run_earnings=bool(earn_news), run_geo=True, run_macro=True, market_news=mkt_news,
            )
            sent = events.sentiment_trend_from_news(sym_news, as_of=bar["t"], max_age_days=7.0)
            _day_event_cache[bar_date] = {"ev": ev, "earnings_soon": es_flag, "sentiment_trend": sent}

        day_ctx = _day_event_cache[bar_date]
        earnings_soon = day_ctx["earnings_soon"]
        ev = day_ctx["ev"]

        sig = strategy.signal_at_index(
            i, _pre,
            market_trend=mt,
            earnings_soon=earnings_soon,
            threshold=1,
            disabled_components=disabled_components or None,
        )

        if ev["event_score"] != 0:
            sig = strategy.apply_event_score(sig, ev, threshold=1)

        total_score = int(sig.get("score") or 0)
        gate_blocked = (abs(total_score) >= 1 and sig.get("signal") == "hold")
        t1_base = sig.get("signal") or _signal_for_threshold(total_score, 1)
        prev_bar = df.iloc[i - 1: i]
        t1_filtered = _apply_historical_signal_filters(t1_base, prev_bar, bar, timeframe, filter_context=fc)
        filter_blocked = t1_base != "hold" and t1_filtered == "hold"

        results[i] = {
            "score": total_score,
            "gate_blocked": gate_blocked,
            "filter_blocked": filter_blocked,
            "sentiment_trend": day_ctx["sentiment_trend"],
            "macro_event_day": bool(fc.get("macro_day", {}).get(bar_date)),
            "curated_blacklist": bool(fc.get("daily_blacklist", {}).get(bar_date)),
            "peer_consensus": True,
            "regime_confidence": float(sig.get("regime_confidence") or 0.0),
            "atr": sig.get("atr"),
            "regime_realized_vol": sig.get("regime_realized_vol"),
            "price": sig.get("price"),
            "ema200_ready": sig.get("ema200_ready", False),
            "earnings_soon": earnings_soon,
            "market_trend": mt,
            "signal": t1_filtered,
        }

    return results


def _apply_historical_signal_filters(
    signal: str,
    window: pd.DataFrame,
    bar: pd.Series,
    timeframe: str,
    filter_context: dict[str, object] | None = None,
) -> str:
    if signal not in ("buy", "sell"):
        return signal

    ts = pd.Timestamp(bar["t"])
    bar_date = ts.strftime("%Y-%m-%d")

    if signal == "buy" and filter_context:
        daily_blacklist = filter_context.get("daily_blacklist", {})
        if daily_blacklist.get(bar_date):
            return "hold"

    if signal == "buy" and timeframe in _TIMEFRAME_MINUTES and timeframe != "1Day":
        tod_ts = ts.tz_localize("America/New_York") if ts.tzinfo is None else ts
        tod_ok, _ = risk.check_time_of_day(now=tod_ts.to_pydatetime())
        if not tod_ok:
            return "hold"

    if signal == "buy" and len(window) >= 1:
        gap_ok, _ = risk.check_gap(
            pd.concat([window.tail(1), pd.DataFrame([bar])], ignore_index=True).to_dict("records")
        )
        if not gap_ok:
            return "hold"

    higher_tf_signal = _lookup_timeline_before(
        filter_context.get("higher_tf_signal") if filter_context else None,
        ts,
    )
    if signal == "buy" and higher_tf_signal == "sell":
        return "hold"
    # Do NOT block sell signals when higher-TF is bullish — shorts are already gated
    # by score threshold and SPY bear penalty. Blocking here causes 0 short trades.

    # Peer consensus: daily peer signals must not gate intraday entries —
    # AMD/AVGO daily trend has no bearing on whether a 5Min NVDA scalp is valid.
    # Removed hard block entirely; peer context is already factored into the score
    # via the regime/SPY penalty in compute_signals.

    return signal


def _simulate(
    df: pd.DataFrame,
    symbol: str,
    timeframe: str,
    initial_cash: float,
    threshold: int,
    sl_atr_mult: float,
    tp_atr_mult: float,
    slippage_bps: float,
    fee_per_trade: float,
    warmup_override: int | None = None,
    market_trend_by_date: dict[str, int] | None = None,
    filter_context: dict[str, object] | None = None,
    event_context: dict[str, object] | None = None,
    market_event_context: dict[str, object] | None = None,
    disabled_components: set[str] | None = None,
    signal_cache: list[dict | None] | None = None,
) -> tuple[list[dict], list[dict], float]:
    """
    Simulate trades on df.

    market_trend_by_date: dict mapping "YYYY-MM-DD" → +1 (SPY bullish) or -1 (SPY bearish).
    When SPY is bearish, buy signals are suppressed via strategy.compute_signals(market_trend=-1).
    """
    warmup = warmup_override if warmup_override is not None else min(20, len(df) // 4)
    filter_context = dict(filter_context or {})
    date_strings = df["t"].dt.strftime("%Y-%m-%d").tolist()
    if "daily_blacklist" not in filter_context:
        filter_context["daily_blacklist"] = _build_daily_blacklist_map(event_context or {}, sorted(set(date_strings)))
    if "macro_day" not in filter_context:
        filter_context["macro_day"] = _build_macro_day_map(market_event_context or {}, sorted(set(date_strings)))

    cash = float(initial_cash)
    position_qty = 0.0
    position_side: str | None = None
    entry_px = 0.0
    trail_anchor_px = 0.0
    entry_atr = 0.0
    partial_done = False
    entry_date = ""
    entry_fee_remaining = 0.0
    active_stop_pct = 0.0   # set at entry from ATR; widens to trail_stop_pct after partial
    active_tp_pct = 0.0     # set at entry from ATR
    initial_stop_pct = 0.0  # protective SL at entry (never changes)
    trail_stop_pct = 0.0    # wider trailing stop (3-6× initial) applied after partial profit fires
    breakeven_locked = False  # True once price moves +1×SL in favour; floors stop at entry
    bars_held = 0            # bars since entry; SL suppressed for MIN_HOLD_BARS to avoid noise-stops
    _MIN_HOLD_BARS = 3       # don't stop-out until held at least 3 bars (avoids instant whipsaw)
    stop_cooldown = 0
    exit_hold_count = 0
    _STOP_COOLDOWN_BARS = 3
    last_order_at: dict[str, pd.Timestamp] = {}
    risk_manager = risk.RiskManager()
    close_history: dict[str, list[float]] = {symbol.upper(): []}
    trades: list[dict] = []
    equity_curve: list[dict] = []

    def _mark_equity(mark_price: float) -> float:
        return _equity_with_position(cash, position_side, position_qty, mark_price)

    def _current_positions(mark_price: float) -> list[dict]:
        if not position_side or position_qty <= 0:
            return []
        return [_position_snapshot(symbol, position_side, position_qty, mark_price, entry_px)]

    # Lazy precompute — only materialises on cache miss (signal_cache covers all bars normally)
    _pre: dict | None = None

    def _get_pre() -> dict:
        nonlocal _pre
        if _pre is None:
            _pre = strategy.precompute_series(df, timeframe=timeframe)
        return _pre

    def _historical_signal(idx: int, bar_row: pd.Series, threshold_value: int) -> dict:
        bar_ts = pd.Timestamp(bar_row["t"])
        bar_date = bar_ts.strftime("%Y-%m-%d")
        mt = market_trend_by_date.get(bar_date, 0) if market_trend_by_date else 0
        symbol_news = _historical_news_before(event_context, bar_ts, time_key="news_times", news_key="news")
        earnings_news = _historical_news_before(event_context, bar_ts, time_key="earnings_news_times", news_key="earnings_news")
        if not symbol_news:
            symbol_news = list(earnings_news)
        market_news = _historical_news_before(market_event_context, bar_ts, time_key="news_times", news_key="news")
        earnings_soon = events.is_earnings_period_from_news(earnings_news, as_of=bar_row["t"]) if earnings_news else False
        # O(1) signal lookup — indicators already precomputed
        sig = strategy.signal_at_index(
            idx, _get_pre(),
            market_trend=mt,
            earnings_soon=earnings_soon,
            threshold=threshold_value,
            disabled_components=disabled_components or None,
        )
        event_result = events.get_historical_event_score(
            symbol, symbol_news, as_of=bar_row["t"],
            run_earnings=bool(earnings_news), run_geo=True, run_macro=True, market_news=market_news,
        )
        if event_result["event_score"] != 0:
            sig = strategy.apply_event_score(sig, event_result, threshold=threshold_value)
        sig["sentiment_trend"] = events.sentiment_trend_from_news(symbol_news, as_of=bar_row["t"], max_age_days=7.0)
        sig["macro_event_day"] = bool(filter_context.get("macro_day", {}).get(bar_date))
        sig["peer_consensus"] = True
        sig["curated_blacklist"] = bool(filter_context.get("daily_blacklist", {}).get(bar_date))
        prev_bar = df.iloc[max(0, idx - 1): idx]  # tail(1) for gap check only
        sig["signal"] = _apply_historical_signal_filters(
            sig.get("signal") or _signal_for_threshold(int(sig.get("score") or 0), threshold_value),
            prev_bar, bar_row, timeframe, filter_context=filter_context,
        )
        return sig

    for i in range(warmup, len(df)):
        bar = df.iloc[i]
        price = float(bar["c"])
        ts_value = pd.Timestamp(bar["t"])
        ts = ts_value.strftime("%Y-%m-%d %H:%M")
        bar_date = ts[:10]
        macro_day = bool(filter_context.get("macro_day", {}).get(bar_date))
        threshold_value = int(threshold) + (1 if macro_day else 0)
        close_history[symbol.upper()].append(price)  # O(1) incremental — was O(n²) slice
        exited_this_bar = False

        account_before = _account_snapshot(cash, _mark_equity(price))
        risk_manager.update_daily_loss_guard(account_before, now=ts_value.to_pydatetime())
        risk_manager.evaluate_drawdown(account_before)

        if stop_cooldown > 0:
            stop_cooldown -= 1

        if position_side and position_qty > 0:
            # Breakeven lock-in: once price moves +1×SL_distance in favour, floor stop at entry.
            # Using SL distance (not ATR) ensures breakeven triggers at same scale as the stop.
            _be_trigger = active_stop_pct * entry_px  # 1R move needed to lock breakeven
            if _be_trigger > 0 and not breakeven_locked:
                if (position_side == "long" and price >= entry_px + _be_trigger) or \
                   (position_side == "short" and price <= entry_px - _be_trigger):
                    breakeven_locked = True
            if breakeven_locked:
                if position_side == "long" and trail_anchor_px > entry_px:
                    # Tighten sl so stop_px = trail_anchor × (1 - sl) >= entry_px
                    active_stop_pct = min(active_stop_pct, max(0.0, 1.0 - entry_px / trail_anchor_px))
                elif position_side == "short" and 0 < trail_anchor_px < entry_px:
                    active_stop_pct = min(active_stop_pct, max(0.0, entry_px / trail_anchor_px - 1.0))

            bars_held += 1
            # During minimum hold period: use initial_stop_pct (wide protective stop) not active_stop_pct.
            # active_stop_pct may be narrowed by breakeven logic; initial_stop_pct is the entry-time stop.
            _sl_for_check = active_stop_pct if bars_held > _MIN_HOLD_BARS else initial_stop_pct
            exit_on_bar = _check_bar_exit(
                entry_px,
                trail_anchor_px,
                bar,
                _sl_for_check,
                active_tp_pct,
                side=position_side,
            )
            if exit_on_bar is not None:
                if (
                    exit_on_bar[1] == "trailing_stop"
                    and config.EXIT_REVIEW_ENABLED
                    and config.USE_AGENT
                    and exit_hold_count < config.MAX_EXIT_HOLDS
                ):
                    review_sig = _historical_signal(i, bar, threshold_value)
                    score = int(review_sig.get("score") or 0)
                    hold_review = (
                        (position_side == "long" and score >= threshold_value + 1)
                        or (position_side == "short" and score <= -(threshold_value + 1))
                    )
                    hold_review = hold_review and float(review_sig.get("regime_confidence") or 0.0) >= 0.5
                    if hold_review:
                        exit_hold_count += 1
                        exit_on_bar = None
                if exit_on_bar is not None:
                    position_before_exit = position_qty
                    raw_exit_px, reason = exit_on_bar
                    fill_exit_px = _resolve_exit_fill(
                        raw_exit_px,
                        reason,
                        bar,
                        position_side,
                        slippage_bps,
                        position_qty,
                    )
                    if position_side == "long":
                        cash += position_qty * fill_exit_px - fee_per_trade
                    else:
                        cash -= position_qty * fill_exit_px + fee_per_trade
                    trade_fees, entry_fee_remaining = _allocate_trade_fees(
                        entry_fee_remaining=entry_fee_remaining,
                        exit_fee=fee_per_trade,
                        qty_exiting=position_qty,
                        position_qty_before_exit=position_before_exit,
                    )
                    trades.append(
                        _make_trade(
                            symbol=symbol,
                            entry_px=entry_px,
                            exit_px=fill_exit_px,
                            qty=position_qty,
                            entry_date=entry_date,
                            exit_date=ts,
                            exit_reason=reason,
                            fees=trade_fees,
                            side=position_side,
                        )
                    )
                    position_qty = 0.0
                    position_side = None
                    entry_px = 0.0
                    trail_anchor_px = 0.0
                    entry_atr = 0.0
                    partial_done = False
                    entry_date = ""
                    entry_fee_remaining = 0.0
                    active_stop_pct = 0.0
                    active_tp_pct = 0.0
                    initial_stop_pct = 0.0
                    trail_stop_pct = 0.0
                    breakeven_locked = False
                    bars_held = 0
                    exit_hold_count = 0
                    if "stop" in reason:
                        stop_cooldown = _STOP_COOLDOWN_BARS
                    exited_this_bar = True

        # Hard EOD force-exit for intraday TFs:
        # Close ALL positions when the NEXT bar crosses into the 16:00+ ET hour range.
        # Fires exactly once (on the last regular-session bar), avoids overnight gap risk.
        # No conditional skip — AH extended-hours lingering risks reversals (observed empirically).
        if (not exited_this_bar and position_side and position_qty > 0
                and timeframe not in ("1Day",) and i + 1 < len(df)):
            _next_raw = pd.Timestamp(df.iloc[i + 1]["t"])
            try:
                _tz = "America/New_York"
                _ne = (_next_raw.tz_localize("UTC") if _next_raw.tzinfo is None else _next_raw).tz_convert(_tz)
                _ce = (ts_value.tz_localize("UTC") if ts_value.tzinfo is None else ts_value).tz_convert(_tz)
                # Only fire at the FIRST 16:00+ bar (current bar still in regular session ≤ 15:59)
                _is_eod = (_ce.hour < 16) and (_ne.hour >= 16 or _ne.date() != _ce.date())
            except Exception:
                _is_eod = _next_raw.strftime("%Y-%m-%d") != bar_date
            if _is_eod:
                if True:  # always exit — hard close
                    position_before_exit = position_qty
                    _exit_side = "sell" if position_side == "long" else "buy"
                    _fill_eod = _apply_slippage(price, _exit_side, slippage_bps, bar=bar, qty=position_qty)
                    if position_side == "long":
                        cash += position_qty * _fill_eod - fee_per_trade
                    else:
                        cash -= position_qty * _fill_eod + fee_per_trade
                    _trade_fees, entry_fee_remaining = _allocate_trade_fees(
                        entry_fee_remaining=entry_fee_remaining,
                        exit_fee=fee_per_trade,
                        qty_exiting=position_qty,
                        position_qty_before_exit=position_before_exit,
                    )
                    trades.append(_make_trade(
                        symbol=symbol, entry_px=entry_px, exit_px=_fill_eod, qty=position_qty,
                        entry_date=entry_date, exit_date=ts, exit_reason="eod_force_exit",
                        fees=_trade_fees, side=position_side,
                    ))
                    position_qty = 0.0
                    position_side = None
                    entry_px = 0.0
                    trail_anchor_px = 0.0
                    entry_atr = 0.0
                    partial_done = False
                    entry_date = ""
                    entry_fee_remaining = 0.0
                    active_stop_pct = 0.0
                    active_tp_pct = 0.0
                    initial_stop_pct = 0.0
                    trail_stop_pct = 0.0
                    breakeven_locked = False
                    bars_held = 0
                    exit_hold_count = 0
                    exited_this_bar = True

        if exited_this_bar:
            equity_curve.append({"date": ts, "equity": round(cash, 2)})
            continue

        if signal_cache is not None and i < len(signal_cache) and signal_cache[i] is not None:
            cached = signal_cache[i]
            cached_score = int(cached["score"])
            if cached["gate_blocked"] or cached["filter_blocked"]:
                _derived_signal = "hold"
            else:
                _derived_signal = _signal_for_threshold(cached_score, threshold_value)
            sig = {**cached, "signal": _derived_signal, "score": cached_score}
        else:
            sig = _historical_signal(i, bar, threshold_value)
        signal = str(sig.get("signal") or "hold")

        if position_side == "long" and position_qty >= 2 and not partial_done and active_stop_pct > 0:
            # Partial profit at 2R (2×SL distance from entry) — proper reward/risk target.
            partial_target = entry_px * (1 + 2.0 * active_stop_pct)
            if price >= partial_target:
                position_before_exit = position_qty
                partial_qty = float(max(1.0, round(position_qty * 0.5, 0)))
                if partial_qty < position_qty:
                    fill_partial = _apply_slippage(price, "sell", slippage_bps, bar=bar, qty=partial_qty)
                    cash += partial_qty * fill_partial - fee_per_trade
                    trade_fees, entry_fee_remaining = _allocate_trade_fees(
                        entry_fee_remaining=entry_fee_remaining,
                        exit_fee=fee_per_trade,
                        qty_exiting=partial_qty,
                        position_qty_before_exit=position_before_exit,
                    )
                    trades.append(
                        _make_trade(
                            symbol=symbol,
                            entry_px=entry_px,
                            exit_px=fill_partial,
                            qty=partial_qty,
                            entry_date=entry_date,
                            exit_date=ts,
                            exit_reason="partial_profit",
                            fees=trade_fees,
                            side="long",
                        )
                    )
                    position_qty -= partial_qty
                    partial_done = True
                    # Widen trailing stop after partial — let remaining position ride the trend.
                    active_stop_pct = trail_stop_pct

        elif position_side == "short" and position_qty >= 2 and not partial_done and active_stop_pct > 0:
            # Symmetric partial profit for shorts at 2R below entry (price fell 2× stop distance).
            partial_target = entry_px * (1 - 2.0 * active_stop_pct)
            if price <= partial_target:
                position_before_exit = position_qty
                partial_qty = float(max(1.0, round(position_qty * 0.5, 0)))
                if partial_qty < position_qty:
                    fill_partial = _apply_slippage(price, "buy", slippage_bps, bar=bar, qty=partial_qty)
                    cash -= partial_qty * fill_partial + fee_per_trade  # cover: buy back short
                    trade_fees, entry_fee_remaining = _allocate_trade_fees(
                        entry_fee_remaining=entry_fee_remaining,
                        exit_fee=fee_per_trade,
                        qty_exiting=partial_qty,
                        position_qty_before_exit=position_before_exit,
                    )
                    trades.append(
                        _make_trade(
                            symbol=symbol,
                            entry_px=entry_px,
                            exit_px=fill_partial,
                            qty=partial_qty,
                            entry_date=entry_date,
                            exit_date=ts,
                            exit_reason="partial_profit",
                            fees=trade_fees,
                            side="short",
                        )
                    )
                    position_qty -= partial_qty
                    partial_done = True
                    active_stop_pct = trail_stop_pct

        if position_side == "long" and signal == "sell":
            agent_result = _surrogate_agent_decision(sig, threshold_value, for_exit=True)
            if agent_result["approved"]:
                position_before_exit = position_qty
                fill_exit_px = _apply_slippage(price, "sell", slippage_bps, bar=bar, qty=position_qty)
                cash += position_qty * fill_exit_px - fee_per_trade
                trade_fees, entry_fee_remaining = _allocate_trade_fees(
                    entry_fee_remaining=entry_fee_remaining,
                    exit_fee=fee_per_trade,
                    qty_exiting=position_qty,
                    position_qty_before_exit=position_before_exit,
                )
                trades.append(
                    _make_trade(
                        symbol=symbol,
                        entry_px=entry_px,
                        exit_px=fill_exit_px,
                        qty=position_qty,
                        entry_date=entry_date,
                        exit_date=ts,
                        exit_reason="signal_exit",
                        fees=trade_fees,
                        side="long",
                    )
                )
                position_qty = 0.0
                position_side = None
                entry_px = 0.0
                trail_anchor_px = 0.0
                entry_atr = 0.0
                partial_done = False
                entry_date = ""
                entry_fee_remaining = 0.0
                active_stop_pct = 0.0
                active_tp_pct = 0.0
                initial_stop_pct = 0.0
                trail_stop_pct = 0.0
                breakeven_locked = False
                bars_held = 0
                exit_hold_count = 0

        elif position_side == "short" and signal == "buy":
            agent_result = _surrogate_agent_decision(sig, threshold_value, for_exit=True)
            if agent_result["approved"]:
                position_before_exit = position_qty
                fill_exit_px = _apply_slippage(price, "buy", slippage_bps, bar=bar, qty=position_qty)
                cash -= position_qty * fill_exit_px + fee_per_trade
                trade_fees, entry_fee_remaining = _allocate_trade_fees(
                    entry_fee_remaining=entry_fee_remaining,
                    exit_fee=fee_per_trade,
                    qty_exiting=position_qty,
                    position_qty_before_exit=position_before_exit,
                )
                trades.append(
                    _make_trade(
                        symbol=symbol,
                        entry_px=entry_px,
                        exit_px=fill_exit_px,
                        qty=position_qty,
                        entry_date=entry_date,
                        exit_date=ts,
                        exit_reason="signal_exit",
                        fees=trade_fees,
                        side="short",
                    )
                )
                position_qty = 0.0
                position_side = None
                entry_px = 0.0
                trail_anchor_px = 0.0
                entry_atr = 0.0
                partial_done = False
                entry_date = ""
                entry_fee_remaining = 0.0
                active_stop_pct = 0.0
                active_tp_pct = 0.0
                initial_stop_pct = 0.0
                trail_stop_pct = 0.0
                breakeven_locked = False
                bars_held = 0
                exit_hold_count = 0

        if position_side is None and stop_cooldown == 0 and signal in ("buy", "sell"):
            wants_short = signal == "sell"
            if wants_short and not config.ALLOW_SHORT:
                signal = "hold"
            # Shorts require very strong confirmation on intraday TFs (noisy signals).
            # Daily shorts are reliable (1-3 per year); intraday shorts need extreme scores.
            if wants_short and signal == "sell":
                _bar_mt = int(sig.get("market_trend") or 0)
                _bar_score = int(sig.get("score") or 0)
                _is_intraday_tf = timeframe not in ("1Day",)
                if _is_intraday_tf:
                    # Intraday shorts disabled: 15Min/5Min indicators too noisy for short-side.
                    # Daily short signals are reliable; intraday is long-only tactical.
                    _short_ok = False
                else:
                    # Daily: require SPY bearish AND strong score — dual confirmation.
                    # This limits shorts to confirmed bear regimes with real momentum.
                    _short_ok = _bar_mt == -1 and _bar_score <= -(threshold_value + 1)
                if not _short_ok:
                    signal = "hold"
            if signal in ("buy", "sell") and config.ENABLE_REGIME_SWITCHING:
                # Regime threshold offset: bear/vol raise bar for entries
                _rp_pre = strategy.regime_params(
                    regime=str(sig.get("regime") or "range"),
                    market_trend=int(sig.get("market_trend") or 0),
                    realized_vol=float(sig.get("regime_realized_vol") or 0.0),
                )
                _regime_thresh_offset = int(_rp_pre.get("threshold_offset", 0))
                if _regime_thresh_offset > 0:
                    _regime_score = int(sig.get("score") or 0)
                    _effective_thresh = threshold_value + _regime_thresh_offset
                    if not (_regime_score >= _effective_thresh or _regime_score <= -_effective_thresh):
                        signal = "hold"
            if signal in ("buy", "sell"):
                agent_result = _surrogate_agent_decision(sig, threshold_value)
                if agent_result["approved"]:
                    account = _account_snapshot(cash, _mark_equity(price))
                    positions = _current_positions(price)
                    ok, _, base_qty = _backtest_pre_trade_checks(
                        symbol=symbol,
                        side=signal,
                        price=price,
                        account=account,
                        positions=positions,
                        now=ts_value,
                        last_order_at=last_order_at,
                        close_history=close_history,
                        atr=sig.get("atr"),
                        realized_vol=None,  # vol-targeting undersizes; use ATR+MAX_POSITION_PCT cap
                        risk_manager=risk_manager,
                    )
                    if ok:
                        # ── Regime-adaptive profile (before cash deduction) ──
                        _rp = strategy.regime_params(
                            regime=str(sig.get("regime") or "range"),
                            market_trend=int(sig.get("market_trend") or 0),
                            realized_vol=float(sig.get("regime_realized_vol") or 0.0),
                        ) if config.ENABLE_REGIME_SWITCHING else {}
                        _sl_factor   = float(_rp.get("sl_mult_factor", 1.0))
                        _size_factor = float(_rp.get("size_factor", 1.0))
                        # ────────────────────────────────────────────────────
                        qty = float(max(1.0, round(base_qty * agent_result["size_multiplier"] * _size_factor, 0)))
                        entry_side = "sell" if wants_short else "buy"
                        fill_entry_px = _apply_slippage(price, entry_side, slippage_bps, bar=bar, qty=qty)
                        required_cash = qty * fill_entry_px + fee_per_trade
                        if wants_short:
                            cash += qty * fill_entry_px - fee_per_trade
                        else:
                            if required_cash > cash:
                                qty = float(max(0.0, np.floor((cash - fee_per_trade) / max(fill_entry_px, 1e-9))))
                                if qty < 1:
                                    qty = 0.0
                            if qty > 0:
                                fill_entry_px = _apply_slippage(price, entry_side, slippage_bps, bar=bar, qty=qty)
                                cash -= qty * fill_entry_px + fee_per_trade
                        if qty > 0:
                            position_qty = qty
                            position_side = "short" if wants_short else "long"
                            entry_px = fill_entry_px
                            trail_anchor_px = fill_entry_px
                            entry_atr = float(sig.get("atr") or 0.0)
                            partial_done = False
                            entry_date = ts
                            entry_fee_remaining = float(fee_per_trade)
                            _atr_val = entry_atr if entry_atr > 0 else fill_entry_px * 0.01
                            _computed_sl = (_atr_val * sl_atr_mult * _sl_factor) / max(fill_entry_px, 1e-9)
                            _computed_tp = (_atr_val * tp_atr_mult) / max(fill_entry_px, 1e-9)
                            # Use ATR-based SL in backtest — agent override bypasses optimizer grid.
                            # Ensure minimum of 0.3% to avoid noise-stop on illiquid bars.
                            initial_stop_pct = max(0.003, _computed_sl)
                            active_stop_pct = initial_stop_pct
                            # Adaptive trailing stop: strong signals (score≥5) use 2× initial SL
                            # Optimized Apr 2026: 2× (strong) / 1× (weak) gave best Sharpe×Return
                            # across META/GOOGL/AMZN/MSFT/QQQ/AAPL on 90d backtest.
                            # Original: 6× (strong) / 3× (weak)
                            _sig_score = abs(int(sig.get("score") or 0))
                            trail_stop_pct = initial_stop_pct * (2.0 if _sig_score >= 5 else 1.0)
                            active_tp_pct = _computed_tp
                            breakeven_locked = False
                            bars_held = 0
                            last_order_at[symbol.upper()] = ts_value
                            exit_hold_count = 0

        if position_side == "long" and position_qty > 0:
            trail_anchor_px = max(trail_anchor_px, price)
        elif position_side == "short" and position_qty > 0:
            trail_anchor_px = min(trail_anchor_px, price)

        equity_curve.append({"date": ts, "equity": round(_mark_equity(price), 2)})

    final_price = float(df["c"].iloc[-1])
    final_bar = df.iloc[-1]
    final_ts = df["t"].iloc[-1].strftime("%Y-%m-%d %H:%M")
    final_equity = _mark_equity(final_price)
    if position_side and position_qty > 0:
        position_before_exit = position_qty
        exit_side = "sell" if position_side == "long" else "buy"
        fill_exit_px = _apply_slippage(final_price, exit_side, slippage_bps, bar=final_bar, qty=position_qty)
        if position_side == "long":
            cash += position_qty * fill_exit_px - fee_per_trade
        else:
            cash -= position_qty * fill_exit_px + fee_per_trade
        trade_fees, entry_fee_remaining = _allocate_trade_fees(
            entry_fee_remaining=entry_fee_remaining,
            exit_fee=fee_per_trade,
            qty_exiting=position_qty,
            position_qty_before_exit=position_before_exit,
        )
        trades.append(
            _make_trade(
                symbol=symbol,
                entry_px=entry_px,
                exit_px=fill_exit_px,
                qty=position_qty,
                entry_date=entry_date,
                exit_date=final_ts,
                exit_reason="end_of_test",
                fees=trade_fees,
                side=position_side,
            )
        )
        final_equity = cash
        entry_fee_remaining = 0.0

    final_equity_point = {"date": final_ts, "equity": round(final_equity, 2)}
    if equity_curve and equity_curve[-1]["date"] == final_ts:
        equity_curve[-1] = final_equity_point
    else:
        equity_curve.append(final_equity_point)

    return trades, equity_curve, final_equity


def _spy_benchmark(timeframe: str, days: int, initial_cash: float) -> list[dict] | None:
    try:
        spy_bars = broker.get_bars("SPY", timeframe=timeframe, lookback_days=days)
        if not spy_bars:
            return None
        spy_df = pd.DataFrame(spy_bars)
        spy_close = spy_df["c"].astype(float)
        spy_start = float(spy_close.iloc[0])
        spy_ts = pd.to_datetime(spy_df["t"])
        return [
            {"date": spy_ts.iloc[j].strftime("%Y-%m-%d %H:%M"), "equity": round(initial_cash * float(spy_close.iloc[j]) / spy_start, 2)}
            for j in range(len(spy_df))
        ]
    except Exception:
        return None


def _build_spy_trend(timeframe: str, days: int) -> dict[str, int]:
    """
    Fetch daily SPY bars and return a date → market_trend dict.

    The trend for each date is based on the previous completed daily bar, so
    the current session never sees same-day SPY closes. This avoids lookahead
    on both daily and intraday backtests.
    """
    try:
        del timeframe  # Trend is intentionally derived from completed daily bars.
        spy_bars = broker.get_bars("SPY", timeframe="1Day", lookback_days=max(250, days + 30))
        if not spy_bars:
            return {}
        spy_df = pd.DataFrame(spy_bars)
        spy_df["c"] = spy_df["c"].astype(float)
        spy_df["t"] = pd.to_datetime(spy_df["t"])
        ema50 = spy_df["c"].ewm(span=50, adjust=False).mean()
        ema200 = spy_df["c"].ewm(span=200, adjust=False).mean()
        # Drawdown from 20-day rolling high — catches sharp corrections faster than EMA.
        rolling_high = spy_df["c"].rolling(20, min_periods=1).max()
        drawdown = (spy_df["c"] - rolling_high) / rolling_high  # negative = below peak
        # Bear: price below 50-EMA OR significant drawdown (>5% from 20d high)
        raw_trend = np.where((spy_df["c"] >= ema50) & (spy_df["c"] >= ema200) & (drawdown >= -0.05), 1, -1)
        date_strings = spy_df["t"].dt.strftime("%Y-%m-%d")
        trend: dict[str, int] = {}
        for idx in range(1, len(spy_df)):
            trend[date_strings.iloc[idx]] = int(raw_trend[idx - 1])
        return trend
    except Exception:
        return {}


def _parameter_grid() -> list[tuple[int, float, float]]:
    thresholds = [2, 3, 4, 5]
    # ATR multipliers now matter: agent stop override removed, optimizer sweeps real SL values.
    # Range 1–8×ATR covers tight noise-stop (1×) through wide trend-riding (8×).
    sl_mults = [1.0, 1.5, 2.0, 3.0, 4.0, 6.0, 8.0]
    # TP disabled (0.0) — 2R partial profit + trailing stop handle profit taking
    return [(t, sl, 0.0) for t, sl in itertools.product(thresholds, sl_mults)]


def _candidate_sort_key(result: dict) -> tuple[float, float, float, int]:
    return (
        float(result["sharpe"]),
        float(result["total_return_pct"]),
        -float(result["max_drawdown_pct"]),
        int(result["trades"]),
    )


def _evaluate_parameters(
    df: pd.DataFrame,
    symbol: str,
    timeframe: str,
    initial_cash: float,
    threshold: int,
    sl_atr_mult: float,
    tp_atr_mult: float,
    market_trend_by_date: dict[str, int] | None = None,
    filter_context: dict[str, object] | None = None,
    event_context: dict[str, object] | None = None,
    warmup_override: int | None = None,
    signal_cache: list[dict | None] | None = None,
) -> dict:
    market_event_context = None
    disabled_components = None
    if filter_context:
        market_event_context = filter_context.get("market_event_context")
        disabled_components = filter_context.get("disabled_components")
    trades, equity_curve, final_equity = _simulate(
        df=df,
        symbol=symbol,
        timeframe=timeframe,
        initial_cash=initial_cash,
        threshold=threshold,
        sl_atr_mult=sl_atr_mult,
        tp_atr_mult=tp_atr_mult,
        slippage_bps=config.BACKTEST_SLIPPAGE_BPS,
        fee_per_trade=config.BACKTEST_FEE_PER_TRADE,
        warmup_override=warmup_override,
        market_trend_by_date=market_trend_by_date,
        filter_context=filter_context,
        event_context=event_context,
        market_event_context=market_event_context,
        disabled_components=disabled_components,
        signal_cache=signal_cache,
    )
    stats = _compute_stats(trades, initial_cash, final_equity, equity_curve, timeframe=timeframe)
    return {
        "threshold": threshold,
        "sl_atr_mult": sl_atr_mult,
        "tp_atr_mult": tp_atr_mult,
        "trades": len(trades),
        "equity_curve": equity_curve,
        "final_equity": final_equity,
        "trade_records": trades,
        **stats,
    }


def _select_training_parameters(
    train_df: pd.DataFrame,
    symbol: str,
    timeframe: str,
    initial_cash: float,
    market_trend_by_date: dict[str, int] | None = None,
    filter_context: dict[str, object] | None = None,
    event_context: dict[str, object] | None = None,
) -> dict | None:
    min_trades = _min_trades_for_timeframe(timeframe, len(train_df))
    candidates: list[dict] = []
    for threshold, sl, tp in _parameter_grid():
        candidate = _evaluate_parameters(
            df=train_df,
            symbol=symbol,
            timeframe=timeframe,
            initial_cash=initial_cash,
            threshold=threshold,
            sl_atr_mult=sl,
            tp_atr_mult=tp,
            market_trend_by_date=market_trend_by_date,
            filter_context=filter_context,
            event_context=event_context,
        )
        if candidate["trades"] >= min_trades:
            candidates.append(candidate)

    if not candidates:
        for threshold, sl, tp in _parameter_grid():
            candidates.append(
                _evaluate_parameters(
                    df=train_df,
                    symbol=symbol,
                    timeframe=timeframe,
                    initial_cash=initial_cash,
                    threshold=threshold,
                    sl_atr_mult=sl,
                    tp_atr_mult=tp,
                    market_trend_by_date=market_trend_by_date,
                    filter_context=filter_context,
                    event_context=event_context,
                )
            )

    if not candidates:
        return None

    candidates.sort(key=_candidate_sort_key, reverse=True)
    return candidates[0]


def run(
    symbol: str,
    timeframe: str = "1Day",
    initial_cash: float = 100_000,
    lookback_days: int | None = None,
    bars: list[dict] | None = None,
) -> dict:
    days = lookback_days or _BT_LOOKBACK.get(timeframe, 365)
    bar_rows = bars if bars is not None else broker.get_bars(symbol, timeframe=timeframe, lookback_days=days)

    n = len(bar_rows)
    if n < 10:
        return {
            "error": (
                f"Only {n} bars returned for {symbol} ({timeframe}, {days}d lookback). "
                "Try a longer lookback or a higher timeframe (e.g. 1Day)."
            )
        }

    df = _prepare_df(bar_rows)

    # Pre-build SPY trend dict for market regime gate (skip SPY itself)
    spy_trend = _build_spy_trend(timeframe, days) if symbol != "SPY" else {}
    filter_context = _build_filter_context(symbol, timeframe, days, df, market_trend_by_date=spy_trend)
    event_context = _build_event_context(symbol, df)
    filter_context["market_event_context"] = _build_market_event_context(df)

    warmup = min(20, len(df) // 4)
    signal_cache = _precompute_bar_signals(
        df=df,
        symbol=symbol,
        timeframe=timeframe,
        warmup=warmup,
        market_trend_by_date=spy_trend,
        filter_context=filter_context,
        event_context=event_context,
        market_event_context=filter_context.get("market_event_context"),
        disabled_components=filter_context.get("disabled_components"),
    )

    result = _evaluate_parameters(
        df=df,
        symbol=symbol,
        timeframe=timeframe,
        initial_cash=initial_cash,
        threshold=strategy._resolve_signal_threshold(timeframe, None),
        sl_atr_mult=config.SL_ATR_MULT,
        tp_atr_mult=config.TP_ATR_MULT,
        market_trend_by_date=spy_trend,
        filter_context=filter_context,
        event_context=event_context,
        signal_cache=signal_cache,
    )
    benchmark = _spy_benchmark(timeframe, days, initial_cash)

    return {
        "symbol": symbol,
        "timeframe": timeframe,
        "initial_cash": initial_cash,
        "final_equity": round(result["final_equity"], 2),
        "total_trades": result["trades"],
        "trades": result["trade_records"],
        "equity_curve": result["equity_curve"],
        "benchmark": benchmark,
        "slippage_bps": config.BACKTEST_SLIPPAGE_BPS,
        "fee_per_trade": config.BACKTEST_FEE_PER_TRADE,
        "data_source": "provided_bars" if bars is not None else "broker_live_lookback",
        "point_in_time_safe": bars is not None,
        **{
            k: v
            for k, v in result.items()
            if k not in {"equity_curve", "final_equity", "trade_records", "threshold", "sl_atr_mult", "tp_atr_mult", "trades"}
        },
    }


def walk_forward(
    symbol: str,
    timeframe: str = "1Day",
    lookback_days: int = 730,
    n_splits: int = 5,
    initial_cash: float = 100_000,
) -> dict:
    bars = broker.get_bars(symbol, timeframe=timeframe, lookback_days=lookback_days)
    n = len(bars)
    if n < 60:
        return {"error": f"Only {n} bars - need at least 60 for walk-forward. Try 1Day with longer lookback."}

    df = _prepare_df(bars)

    spy_trend = _build_spy_trend(timeframe, lookback_days) if symbol != "SPY" else {}
    filter_context = _build_filter_context(symbol, timeframe, lookback_days, df, market_trend_by_date=spy_trend)
    event_context = _build_event_context(symbol, df)
    filter_context["market_event_context"] = _build_market_event_context(df)

    fold_size = n // n_splits
    folds = []
    for i in range(n_splits):
        start = i * fold_size
        end = start + fold_size if i < n_splits - 1 else n
        fold_df = df.iloc[start:end].reset_index(drop=True)
        split = int(len(fold_df) * 0.7)
        # Pass full fold (training + OOS) so indicators have enough history.
        # warmup_override=split means the training portion is used only for indicator
        # warm-up; trades are only generated during the OOS (out-of-sample) window.
        if len(fold_df) - split < 5:
            continue

        train_df = fold_df.iloc[:split].reset_index(drop=True)
        best_params = _select_training_parameters(
            train_df=train_df,
            symbol=symbol,
            timeframe=timeframe,
            initial_cash=initial_cash,
            market_trend_by_date=spy_trend,
            filter_context=filter_context,
            event_context=event_context,
        )
        if not best_params:
            continue

        oos_result = _evaluate_parameters(
            df=fold_df,
            symbol=symbol,
            timeframe=timeframe,
            initial_cash=initial_cash,
            threshold=best_params["threshold"],
            sl_atr_mult=best_params["sl_atr_mult"],
            tp_atr_mult=best_params["tp_atr_mult"],
            market_trend_by_date=spy_trend,
            filter_context=filter_context,
            event_context=event_context,
            warmup_override=split,
        )
        folds.append(
            {
                "fold": i + 1,
                "oos_start": fold_df["t"].iloc[split].strftime("%Y-%m-%d"),
                "oos_end": fold_df["t"].iloc[-1].strftime("%Y-%m-%d"),
                "train_threshold": best_params["threshold"],
                "train_sl_mult": f"{best_params['sl_atr_mult']:.1f}×ATR",
                "train_tp_mult": f"{best_params['tp_atr_mult']:.1f}×ATR",
                "train_sharpe": best_params["sharpe"],
                "trades": oos_result["trades"],
                "total_return_pct": oos_result["total_return_pct"],
                "win_rate_pct": oos_result["win_rate_pct"],
                "avg_win": oos_result["avg_win"],
                "avg_loss": oos_result["avg_loss"],
                "profit_factor": oos_result["profit_factor"],
                "sharpe": oos_result["sharpe"],
                "max_drawdown_pct": oos_result["max_drawdown_pct"],
            }
        )

    if not folds:
        return {"error": "No valid folds produced - try a longer lookback."}

    avg_return = round(float(np.mean([f["total_return_pct"] for f in folds])), 2)
    avg_sharpe = round(float(np.mean([f["sharpe"] for f in folds])), 3)
    avg_win = round(float(np.mean([f["win_rate_pct"] for f in folds])), 1)
    consistent = sum(1 for f in folds if f["total_return_pct"] > 0)

    return {
        "symbol": symbol,
        "timeframe": timeframe,
        "n_folds": len(folds),
        "avg_return_pct": avg_return,
        "avg_sharpe": avg_sharpe,
        "avg_win_rate": avg_win,
        "profitable_folds": f"{consistent}/{len(folds)}",
        "folds": folds,
    }


def walk_forward_expanding(
    symbol: str,
    timeframe: str = "1Day",
    lookback_days: int = 730,
    min_train_pct: float = 0.4,
    n_splits: int = 5,
    initial_cash: float = 100_000,
) -> dict:
    """
    Expanding-window walk-forward validation.

    Unlike fixed-fold walk-forward (equal-size chunks), each successive fold
    uses all available history as training data — the training window grows.
    This more closely mirrors how a live strategy is deployed over time.

    Layout:
      Fold 1: train=[0..min_train_end]   OOS=[min_train_end..oos_end_1]
      Fold 2: train=[0..oos_end_1]       OOS=[oos_end_1..oos_end_2]
      ...
    """
    bars = broker.get_bars(symbol, timeframe=timeframe, lookback_days=lookback_days)
    n = len(bars)
    if n < 60:
        return {"error": f"Only {n} bars — need at least 60 for expanding walk-forward."}

    df = _prepare_df(bars)

    spy_trend = _build_spy_trend(timeframe, lookback_days) if symbol != "SPY" else {}
    filter_context = _build_filter_context(symbol, timeframe, lookback_days, df, market_trend_by_date=spy_trend)
    event_context = _build_event_context(symbol, df)
    filter_context["market_event_context"] = _build_market_event_context(df)

    min_train = max(20, int(n * min_train_pct))
    remaining = n - min_train
    oos_per_fold = max(5, remaining // n_splits)

    folds = []
    train_end = min_train

    for i in range(n_splits):
        test_end = min(train_end + oos_per_fold, n)
        if test_end - train_end < 5:
            break

        fold_df = df.iloc[:test_end].reset_index(drop=True)
        train_df = fold_df.iloc[:train_end].reset_index(drop=True)
        best_params = _select_training_parameters(
            train_df=train_df,
            symbol=symbol,
            timeframe=timeframe,
            initial_cash=initial_cash,
            market_trend_by_date=spy_trend,
            filter_context=filter_context,
            event_context=event_context,
        )
        if not best_params:
            break

        oos_result = _evaluate_parameters(
            df=fold_df,
            symbol=symbol,
            timeframe=timeframe,
            initial_cash=initial_cash,
            threshold=best_params["threshold"],
            sl_atr_mult=best_params["sl_atr_mult"],
            tp_atr_mult=best_params["tp_atr_mult"],
            market_trend_by_date=spy_trend,
            filter_context=filter_context,
            event_context=event_context,
            warmup_override=train_end,
        )
        folds.append({
            "fold": i + 1,
            "train_bars": train_end,
            "oos_bars": test_end - train_end,
            "oos_start": fold_df["t"].iloc[train_end].strftime("%Y-%m-%d"),
            "oos_end": fold_df["t"].iloc[-1].strftime("%Y-%m-%d"),
            "train_threshold": best_params["threshold"],
            "train_sl_mult": f"{best_params['sl_atr_mult']:.1f}×ATR",
            "train_tp_mult": f"{best_params['tp_atr_mult']:.1f}×ATR",
            "train_sharpe": best_params["sharpe"],
            "trades": oos_result["trades"],
            "total_return_pct": oos_result["total_return_pct"],
            "win_rate_pct": oos_result["win_rate_pct"],
            "avg_win": oos_result["avg_win"],
            "avg_loss": oos_result["avg_loss"],
            "profit_factor": oos_result["profit_factor"],
            "sharpe": oos_result["sharpe"],
            "max_drawdown_pct": oos_result["max_drawdown_pct"],
        })
        train_end = test_end  # expanding: next fold trains on everything so far

    if not folds:
        return {"error": "No valid folds — try longer lookback."}

    avg_return = round(float(np.mean([f["total_return_pct"] for f in folds])), 2)
    avg_sharpe = round(float(np.mean([f["sharpe"] for f in folds])), 3)
    avg_win = round(float(np.mean([f["win_rate_pct"] for f in folds])), 1)
    consistent = sum(1 for f in folds if f["total_return_pct"] > 0)

    return {
        "symbol": symbol,
        "timeframe": timeframe,
        "method": "expanding",
        "n_folds": len(folds),
        "avg_return_pct": avg_return,
        "avg_sharpe": avg_sharpe,
        "avg_win_rate": avg_win,
        "profitable_folds": f"{consistent}/{len(folds)}",
        "folds": folds,
    }


def optimize(
    symbol: str,
    timeframe: str = "1Day",
    lookback_days: int = 365,
    initial_cash: float = 100_000,
) -> dict:
    """
    Grid search over SIGNAL_THRESHOLD, STOP_LOSS_PCT, TAKE_PROFIT_PCT.
    Uses the same realistic simulation logic as run().
    """
    bars = broker.get_bars(symbol, timeframe=timeframe, lookback_days=lookback_days)
    n = len(bars)
    if n < 30:
        return {"error": f"Only {n} bars - need at least 30 for optimization."}

    df = _prepare_df(bars)

    spy_trend = _build_spy_trend(timeframe, lookback_days) if symbol != "SPY" else {}
    filter_context = _build_filter_context(symbol, timeframe, lookback_days, df, market_trend_by_date=spy_trend)
    event_context = _build_event_context(symbol, df)
    filter_context["market_event_context"] = _build_market_event_context(df)
    split = max(30, int(len(df) * 0.7))
    if len(df) - split < 5:
        return {"error": "Need more data for train/validation optimisation split."}
    train_df = df.iloc[:split].reset_index(drop=True)
    # Scale minimum with data size: fixed TF floors are designed for long lookbacks.
    # For short lookbacks (e.g. 5d 5Min), proportional floor avoids false "no results".
    _tf_floor = _MIN_TRADES_BY_TIMEFRAME.get(timeframe, 3)
    _proportional = max(3, int(len(train_df) * 0.005))
    min_train_trades = min(_tf_floor, _proportional)
    min_validation_trades = max(1, min_train_trades // 2)

    # Precompute signals once — reused across all 100 parameter combos (200× speedup)
    warmup = min(20, len(df) // 4)
    market_event_context = filter_context.get("market_event_context")
    disabled_components = filter_context.get("disabled_components")
    signal_cache = _precompute_bar_signals(
        df=df,
        symbol=symbol,
        timeframe=timeframe,
        warmup=warmup,
        market_trend_by_date=spy_trend,
        filter_context=filter_context,
        event_context=event_context,
        market_event_context=market_event_context,
        disabled_components=disabled_components,
    )

    results = []
    for threshold, sl, tp in _parameter_grid():
        train_result = _evaluate_parameters(
            df=train_df,
            symbol=symbol,
            timeframe=timeframe,
            initial_cash=initial_cash,
            threshold=threshold,
            sl_atr_mult=sl,
            tp_atr_mult=tp,
            market_trend_by_date=spy_trend,
            filter_context=filter_context,
            event_context=event_context,
            signal_cache=signal_cache,
        )
        if train_result["trades"] < min_train_trades:
            continue

        validation_result = _evaluate_parameters(
            df=df,
            symbol=symbol,
            timeframe=timeframe,
            initial_cash=initial_cash,
            threshold=threshold,
            sl_atr_mult=sl,
            tp_atr_mult=tp,
            market_trend_by_date=spy_trend,
            filter_context=filter_context,
            event_context=event_context,
            warmup_override=split,
            signal_cache=signal_cache,
        )
        if validation_result["trades"] < min_validation_trades:
            continue

        results.append(
            {
                "threshold": threshold,
                "sl_mult": f"{sl:.1f}×ATR",
                "tp_mult": "trailing" if tp == 0.0 else f"{tp:.1f}×ATR",
                "train_trades": train_result["trades"],
                "train_return": train_result["total_return_pct"],
                "train_sharpe": train_result["sharpe"],
                "trades": validation_result["trades"],
                "return": validation_result["total_return_pct"],
                "sharpe": validation_result["sharpe"],
                "win_rate": validation_result["win_rate_pct"],
                "max_dd": validation_result["max_drawdown_pct"],
            }
        )

    if not results:
        return {"error": "No parameter sets met the minimum trade thresholds."}

    results.sort(key=lambda r: (r["sharpe"], r["return"], -r["max_dd"], r["trades"]), reverse=True)
    best = results[0] if results else {}
    return {
        "symbol": symbol,
        "best": best,
        "selection": "train_validation",
        "train_bars": split,
        "validation_bars": len(df) - split,
        "results": results[:20],
    }


def _daily_close_frame(df: pd.DataFrame) -> pd.DataFrame:
    daily = _resample_df(df, "1Day") if len(df) and df["t"].diff().dt.total_seconds().dropna().median() < 86400 else df.copy()
    if daily.empty:
        return pd.DataFrame(columns=["t", "c"])
    out = daily[["t", "c"]].copy()
    out["t"] = pd.to_datetime(out["t"])
    out["c"] = out["c"].astype(float)
    return out.sort_values("t").reset_index(drop=True)


def _build_relative_strength_leaders(
    symbol_dfs: dict[str, pd.DataFrame],
    timeframe: str,
    lookback_days: int,
) -> dict[str, set[str]]:
    del timeframe
    tracked_symbols = [symbol for symbol in symbol_dfs if symbol.upper() != "SPY"]
    if len(tracked_symbols) <= 1:
        return {}

    spy_df = symbol_dfs.get("SPY")
    if spy_df is None or spy_df.empty:
        try:
            spy_df = _prepare_df(broker.get_bars("SPY", timeframe="1Day", lookback_days=max(30, lookback_days)))
        except Exception:
            return {}

    daily_by_symbol = {symbol: _daily_close_frame(df) for symbol, df in symbol_dfs.items() if not df.empty}
    spy_daily = _daily_close_frame(spy_df)
    all_dates = sorted({ts.date() for df in daily_by_symbol.values() for ts in pd.to_datetime(df["t"])})
    leaders_by_date: dict[str, set[str]] = {}

    for day in all_dates:
        spy_hist = spy_daily[spy_daily["t"].dt.date < day].tail(20)
        if len(spy_hist) < 20:
            continue
        spy_ret = float(spy_hist["c"].iloc[-1] / spy_hist["c"].iloc[0] - 1.0)
        ranked: list[tuple[str, float]] = []
        for symbol in tracked_symbols:
            daily_df = daily_by_symbol.get(symbol)
            if daily_df is None or daily_df.empty:
                continue
            hist = daily_df[daily_df["t"].dt.date < day].tail(20)
            if len(hist) < 20:
                ranked.append((symbol, 0.0))
                continue
            sym_ret = float(hist["c"].iloc[-1] / hist["c"].iloc[0] - 1.0)
            ranked.append((symbol, sym_ret - spy_ret))
        if not ranked:
            continue
        ranked.sort(key=lambda item: item[1], reverse=True)
        keep = max(2, int(len(ranked) * 0.6)) if len(ranked) >= 2 else 1
        leaders_by_date[day.isoformat()] = {symbol for symbol, _ in ranked[:keep]}
    return leaders_by_date


def run_portfolio(
    symbols: list[str],
    timeframe: str = "1Day",
    initial_cash: float = 100_000,
    lookback_days: int | None = None,
    bars_by_symbol: dict[str, list[dict]] | None = None,
    daily_watchlist_by_date: dict[str, list[str]] | None = None,
) -> dict:
    days = lookback_days or _BT_LOOKBACK.get(timeframe, 365)
    unique_symbols = list(dict.fromkeys(symbol.upper() for symbol in symbols))
    if not unique_symbols:
        return {"error": "No symbols supplied."}

    symbol_dfs: dict[str, pd.DataFrame] = {}
    for symbol in unique_symbols:
        bars = (bars_by_symbol or {}).get(symbol)
        if bars is None:
            bars = broker.get_bars(symbol, timeframe=timeframe, lookback_days=days)
        if not bars:
            continue
        symbol_dfs[symbol] = _prepare_df(bars)
    if not symbol_dfs:
        return {"error": "No bars available for portfolio backtest."}

    union_df = pd.concat([df.assign(symbol=symbol) for symbol, df in symbol_dfs.items()], ignore_index=True).sort_values("t")
    market_event_context = _build_market_event_context(union_df)
    spy_trend = _build_spy_trend(timeframe, days)
    leader_map = {
        date_str: {symbol.upper() for symbol in members}
        for date_str, members in (daily_watchlist_by_date or {}).items()
    }
    if not leader_map:
        leader_map = _build_relative_strength_leaders(symbol_dfs, timeframe, days)

    filter_contexts: dict[str, dict] = {}
    event_contexts: dict[str, dict] = {}
    states: dict[str, dict] = {}
    close_history: dict[str, list[float]] = {symbol: [] for symbol in symbol_dfs}
    last_price: dict[str, float] = {
        symbol: float(df["c"].iloc[0]) for symbol, df in symbol_dfs.items() if not df.empty
    }
    event_queue: list[tuple[pd.Timestamp, str, int]] = []

    for symbol, df in symbol_dfs.items():
        warmup = min(20, len(df) // 4)
        for idx in range(warmup, len(df)):
            event_queue.append((pd.Timestamp(df["t"].iloc[idx]), symbol, idx))
        event_context = _build_event_context(symbol, df)
        dates = sorted(set(df["t"].dt.strftime("%Y-%m-%d")))
        filter_context = _build_filter_context(symbol, timeframe, days, df, market_trend_by_date=spy_trend)
        filter_context["daily_blacklist"] = _build_daily_blacklist_map(event_context, dates)
        filter_context["macro_day"] = _build_macro_day_map(market_event_context, dates)
        filter_context["market_event_context"] = market_event_context
        filter_contexts[symbol] = filter_context
        event_contexts[symbol] = event_context
        states[symbol] = {
            "qty": 0.0,
            "side": None,
            "entry_px": 0.0,
            "trail_anchor_px": 0.0,
            "entry_atr": 0.0,
            "partial_done": False,
            "entry_date": "",
            "entry_fee_remaining": 0.0,
            "active_stop_pct": 0.0,    # set at entry from ATR
            "active_tp_pct": 0.0,      # set at entry from ATR
            "breakeven_locked": False,  # floored at entry price once +1×ATR gained
            "stop_cooldown": 0,
            "exit_hold_count": 0,
        }

    event_queue.sort(key=lambda item: (item[0], item[1]))
    cash = float(initial_cash)
    risk_manager = risk.RiskManager()
    last_order_at: dict[str, pd.Timestamp] = {}
    trades: list[dict] = []
    equity_curve: list[dict] = []

    def _portfolio_positions() -> list[dict]:
        rows: list[dict] = []
        for symbol, state in states.items():
            if not state["side"] or state["qty"] <= 0:
                continue
            rows.append(
                _position_snapshot(
                    symbol,
                    state["side"],
                    state["qty"],
                    last_price.get(symbol, state["entry_px"]),
                    state["entry_px"],
                )
            )
        return rows

    def _portfolio_equity() -> float:
        equity = cash
        for symbol, state in states.items():
            if state["side"] and state["qty"] > 0:
                equity += _mark_to_market_value(state["side"], state["qty"], last_price.get(symbol, state["entry_px"]))
        return float(equity)

    def _historical_signal(symbol: str, window: pd.DataFrame, bar_row: pd.Series, threshold_value: int) -> dict:
        filter_context = filter_contexts[symbol]
        event_context = event_contexts[symbol]
        bar_ts = pd.Timestamp(bar_row["t"])
        bar_date = bar_ts.strftime("%Y-%m-%d")
        mt = spy_trend.get(bar_date, 0)
        symbol_news = _historical_news_before(event_context, bar_ts, time_key="news_times", news_key="news")
        earnings_news = _historical_news_before(event_context, bar_ts, time_key="earnings_news_times", news_key="earnings_news")
        if not symbol_news:
            symbol_news = list(earnings_news)
        market_news = _historical_news_before(market_event_context, bar_ts, time_key="news_times", news_key="news")
        earnings_soon = events.is_earnings_period_from_news(earnings_news, as_of=bar_row["t"]) if earnings_news else False
        sig = strategy.compute_signals(
            window.to_dict("records"),
            market_trend=mt,
            earnings_soon=earnings_soon,
            threshold=threshold_value,
            timeframe=timeframe,
        )
        event_result = events.get_historical_event_score(
            symbol,
            symbol_news,
            as_of=bar_row["t"],
            run_earnings=bool(earnings_news),
            run_geo=True,
            run_macro=True,
            market_news=market_news,
        )
        if event_result["event_score"] != 0:
            sig = strategy.apply_event_score(sig, event_result, threshold=threshold_value)
        sig["sentiment_trend"] = events.sentiment_trend_from_news(symbol_news, as_of=bar_row["t"], max_age_days=7.0)
        sig["macro_event_day"] = bool(filter_context.get("macro_day", {}).get(bar_date))
        sig["peer_consensus"] = True
        sig["signal"] = _apply_historical_signal_filters(
            sig.get("signal") or _signal_for_threshold(int(sig.get("score") or 0), threshold_value),
            window,
            bar_row,
            timeframe,
            filter_context=filter_context,
        )
        return sig

    for ts_value, symbol, idx in event_queue:
        df = symbol_dfs[symbol]
        state = states[symbol]
        window = df.iloc[:idx]
        bar = df.iloc[idx]
        price = float(bar["c"])
        last_price[symbol] = price
        close_history[symbol] = window["c"].astype(float).tolist()

        ts = ts_value.strftime("%Y-%m-%d %H:%M")
        bar_date = ts[:10]
        threshold_value = strategy._resolve_signal_threshold(timeframe, None) + (
            1 if filter_contexts[symbol].get("macro_day", {}).get(bar_date) else 0
        )
        account = _account_snapshot(cash, _portfolio_equity())
        risk_manager.update_daily_loss_guard(account, now=ts_value.to_pydatetime())
        risk_manager.evaluate_drawdown(account)

        if state["stop_cooldown"] > 0:
            state["stop_cooldown"] -= 1

        exited_this_bar = False
        if state["side"] and state["qty"] > 0:
            # Breakeven lock-in: once +1×SL_distance gained, floor stop at entry price
            _be_trigger_s = state["active_stop_pct"] * state["entry_px"]
            if _be_trigger_s > 0 and not state["breakeven_locked"]:
                if (state["side"] == "long" and price >= state["entry_px"] + _be_trigger_s) or \
                   (state["side"] == "short" and price <= state["entry_px"] - _be_trigger_s):
                    state["breakeven_locked"] = True
            if state["breakeven_locked"]:
                if state["side"] == "long" and state["trail_anchor_px"] > state["entry_px"]:
                    state["active_stop_pct"] = min(state["active_stop_pct"], max(0.0, 1.0 - state["entry_px"] / state["trail_anchor_px"]))
                elif state["side"] == "short" and 0 < state["trail_anchor_px"] < state["entry_px"]:
                    state["active_stop_pct"] = min(state["active_stop_pct"], max(0.0, state["entry_px"] / state["trail_anchor_px"] - 1.0))

            exit_on_bar = _check_bar_exit(
                state["entry_px"],
                state["trail_anchor_px"],
                bar,
                state["active_stop_pct"],
                state["active_tp_pct"],
                side=state["side"],
            )
            if exit_on_bar is not None:
                if (
                    exit_on_bar[1] == "trailing_stop"
                    and config.EXIT_REVIEW_ENABLED
                    and config.USE_AGENT
                    and state["exit_hold_count"] < config.MAX_EXIT_HOLDS
                ):
                    review_sig = _historical_signal(symbol, window, bar, threshold_value)
                    score = int(review_sig.get("score") or 0)
                    hold_review = (
                        (state["side"] == "long" and score >= threshold_value + 1)
                        or (state["side"] == "short" and score <= -(threshold_value + 1))
                    )
                    hold_review = hold_review and float(review_sig.get("regime_confidence") or 0.0) >= 0.5
                    if hold_review:
                        state["exit_hold_count"] += 1
                        exit_on_bar = None
                if exit_on_bar is not None:
                    raw_exit_px, reason = exit_on_bar
                    fill_exit_px = _resolve_exit_fill(
                        raw_exit_px,
                        reason,
                        bar,
                        state["side"],
                        config.BACKTEST_SLIPPAGE_BPS,
                        state["qty"],
                    )
                    if state["side"] == "long":
                        cash += state["qty"] * fill_exit_px - config.BACKTEST_FEE_PER_TRADE
                    else:
                        cash -= state["qty"] * fill_exit_px + config.BACKTEST_FEE_PER_TRADE
                    trade_fees, state["entry_fee_remaining"] = _allocate_trade_fees(
                        entry_fee_remaining=state["entry_fee_remaining"],
                        exit_fee=config.BACKTEST_FEE_PER_TRADE,
                        qty_exiting=state["qty"],
                        position_qty_before_exit=state["qty"],
                    )
                    trades.append(
                        _make_trade(
                            symbol=symbol,
                            entry_px=state["entry_px"],
                            exit_px=fill_exit_px,
                            qty=state["qty"],
                            entry_date=state["entry_date"],
                            exit_date=ts,
                            exit_reason=reason,
                            fees=trade_fees,
                            side=state["side"],
                        )
                    )
                    state.update(
                        {
                            "qty": 0.0,
                            "side": None,
                            "entry_px": 0.0,
                            "trail_anchor_px": 0.0,
                            "entry_atr": 0.0,
                            "partial_done": False,
                            "entry_date": "",
                            "entry_fee_remaining": 0.0,
                            "active_stop_pct": 0.0,
                            "active_tp_pct": 0.0,
                            "breakeven_locked": False,
                            "exit_hold_count": 0,
                        }
                    )
                    if "stop" in reason:
                        state["stop_cooldown"] = 3
                    exited_this_bar = True

        if exited_this_bar:
            equity_curve.append({"date": ts, "equity": round(_portfolio_equity(), 2)})
            continue

        sig = _historical_signal(symbol, window, bar, threshold_value)
        signal = str(sig.get("signal") or "hold")

        if state["side"] == "long" and state["qty"] >= 2 and not state["partial_done"] and state["active_stop_pct"] > 0:
            partial_target = state["entry_px"] * (1 + 2.0 * state["active_stop_pct"])
            if price >= partial_target:
                partial_qty = float(max(1.0, round(state["qty"] * 0.5, 0)))
                if partial_qty < state["qty"]:
                    fill_partial = _apply_slippage(price, "sell", config.BACKTEST_SLIPPAGE_BPS, bar=bar, qty=partial_qty)
                    cash += partial_qty * fill_partial - config.BACKTEST_FEE_PER_TRADE
                    trade_fees, state["entry_fee_remaining"] = _allocate_trade_fees(
                        entry_fee_remaining=state["entry_fee_remaining"],
                        exit_fee=config.BACKTEST_FEE_PER_TRADE,
                        qty_exiting=partial_qty,
                        position_qty_before_exit=state["qty"],
                    )
                    trades.append(
                        _make_trade(
                            symbol=symbol,
                            entry_px=state["entry_px"],
                            exit_px=fill_partial,
                            qty=partial_qty,
                            entry_date=state["entry_date"],
                            exit_date=ts,
                            exit_reason="partial_profit",
                            fees=trade_fees,
                            side="long",
                        )
                    )
                    state["qty"] -= partial_qty
                    state["partial_done"] = True

        if state["side"] == "long" and signal == "sell":
            agent_result = _surrogate_agent_decision(sig, threshold_value, for_exit=True)
            if agent_result["approved"]:
                fill_exit_px = _apply_slippage(price, "sell", config.BACKTEST_SLIPPAGE_BPS, bar=bar, qty=state["qty"])
                cash += state["qty"] * fill_exit_px - config.BACKTEST_FEE_PER_TRADE
                trade_fees, state["entry_fee_remaining"] = _allocate_trade_fees(
                    entry_fee_remaining=state["entry_fee_remaining"],
                    exit_fee=config.BACKTEST_FEE_PER_TRADE,
                    qty_exiting=state["qty"],
                    position_qty_before_exit=state["qty"],
                )
                trades.append(
                    _make_trade(
                        symbol=symbol,
                        entry_px=state["entry_px"],
                        exit_px=fill_exit_px,
                        qty=state["qty"],
                        entry_date=state["entry_date"],
                        exit_date=ts,
                        exit_reason="signal_exit",
                        fees=trade_fees,
                        side="long",
                    )
                )
                state.update(
                    {
                        "qty": 0.0,
                        "side": None,
                        "entry_px": 0.0,
                        "trail_anchor_px": 0.0,
                        "entry_atr": 0.0,
                        "partial_done": False,
                        "entry_date": "",
                        "entry_fee_remaining": 0.0,
                        "active_stop_pct": 0.0,
                        "active_tp_pct": 0.0,
                        "breakeven_locked": False,
                        "exit_hold_count": 0,
                    }
                )

        elif state["side"] == "short" and signal == "buy":
            agent_result = _surrogate_agent_decision(sig, threshold_value, for_exit=True)
            if agent_result["approved"]:
                fill_exit_px = _apply_slippage(price, "buy", config.BACKTEST_SLIPPAGE_BPS, bar=bar, qty=state["qty"])
                cash -= state["qty"] * fill_exit_px + config.BACKTEST_FEE_PER_TRADE
                trade_fees, state["entry_fee_remaining"] = _allocate_trade_fees(
                    entry_fee_remaining=state["entry_fee_remaining"],
                    exit_fee=config.BACKTEST_FEE_PER_TRADE,
                    qty_exiting=state["qty"],
                    position_qty_before_exit=state["qty"],
                )
                trades.append(
                    _make_trade(
                        symbol=symbol,
                        entry_px=state["entry_px"],
                        exit_px=fill_exit_px,
                        qty=state["qty"],
                        entry_date=state["entry_date"],
                        exit_date=ts,
                        exit_reason="signal_exit",
                        fees=trade_fees,
                        side="short",
                    )
                )
                state.update(
                    {
                        "qty": 0.0,
                        "side": None,
                        "entry_px": 0.0,
                        "trail_anchor_px": 0.0,
                        "entry_atr": 0.0,
                        "partial_done": False,
                        "entry_date": "",
                        "entry_fee_remaining": 0.0,
                        "active_stop_pct": 0.0,
                        "active_tp_pct": 0.0,
                        "breakeven_locked": False,
                        "exit_hold_count": 0,
                    }
                )

        eligible_symbols = leader_map.get(bar_date)
        can_enter_symbol = eligible_symbols is None or symbol in eligible_symbols
        if state["side"] is None and state["stop_cooldown"] == 0 and can_enter_symbol and signal in ("buy", "sell"):
            wants_short = signal == "sell"
            if not wants_short or config.ALLOW_SHORT:
                agent_result = _surrogate_agent_decision(sig, threshold_value)
                if agent_result["approved"]:
                    account = _account_snapshot(cash, _portfolio_equity())
                    positions = _portfolio_positions()
                    ok, _, base_qty = _backtest_pre_trade_checks(
                        symbol=symbol,
                        side=signal,
                        price=price,
                        account=account,
                        positions=positions,
                        now=ts_value,
                        last_order_at=last_order_at,
                        close_history=close_history,
                        atr=sig.get("atr"),
                        realized_vol=None,  # vol-targeting undersizes; use ATR+MAX_POSITION_PCT cap
                        risk_manager=risk_manager,
                    )
                    if ok:
                        qty = float(max(1.0, round(base_qty * agent_result["size_multiplier"], 0)))
                        entry_side = "sell" if wants_short else "buy"
                        fill_entry_px = _apply_slippage(price, entry_side, config.BACKTEST_SLIPPAGE_BPS, bar=bar, qty=qty)
                        required_cash = qty * fill_entry_px + config.BACKTEST_FEE_PER_TRADE
                        if wants_short:
                            cash += qty * fill_entry_px - config.BACKTEST_FEE_PER_TRADE
                        else:
                            if required_cash > cash:
                                qty = float(max(0.0, np.floor((cash - config.BACKTEST_FEE_PER_TRADE) / max(fill_entry_px, 1e-9))))
                                if qty < 1:
                                    qty = 0.0
                            if qty > 0:
                                fill_entry_px = _apply_slippage(price, entry_side, config.BACKTEST_SLIPPAGE_BPS, bar=bar, qty=qty)
                                cash -= qty * fill_entry_px + config.BACKTEST_FEE_PER_TRADE
                        if qty > 0:
                            _entry_atr = float(sig.get("atr") or fill_entry_px * 0.01)
                            _computed_sl = (_entry_atr * config.SL_ATR_MULT) / max(fill_entry_px, 1e-9)
                            _computed_tp = (_entry_atr * config.TP_ATR_MULT) / max(fill_entry_px, 1e-9)
                            state.update(
                                {
                                    "qty": qty,
                                    "side": "short" if wants_short else "long",
                                    "entry_px": fill_entry_px,
                                    "trail_anchor_px": fill_entry_px,
                                    "entry_atr": _entry_atr,
                                    "partial_done": False,
                                    "entry_date": ts,
                                    "entry_fee_remaining": float(config.BACKTEST_FEE_PER_TRADE),
                                    "active_stop_pct": max(0.003, _computed_sl),
                                    "active_tp_pct": _computed_tp,
                                    "breakeven_locked": False,
                                    "exit_hold_count": 0,
                                }
                            )
                            last_order_at[symbol] = ts_value

        if state["side"] == "long" and state["qty"] > 0:
            state["trail_anchor_px"] = max(state["trail_anchor_px"], price)
        elif state["side"] == "short" and state["qty"] > 0:
            state["trail_anchor_px"] = min(state["trail_anchor_px"], price)

        equity_curve.append({"date": ts, "equity": round(_portfolio_equity(), 2)})

    if not event_queue:
        return {"error": "No eligible bars available for portfolio simulation."}

    final_ts = event_queue[-1][0].strftime("%Y-%m-%d %H:%M")
    for symbol, state in states.items():
        if not state["side"] or state["qty"] <= 0:
            continue
        fill_exit_px = _apply_slippage(
            last_price.get(symbol, state["entry_px"]),
            "sell" if state["side"] == "long" else "buy",
            config.BACKTEST_SLIPPAGE_BPS,
            qty=state["qty"],
        )
        if state["side"] == "long":
            cash += state["qty"] * fill_exit_px - config.BACKTEST_FEE_PER_TRADE
        else:
            cash -= state["qty"] * fill_exit_px + config.BACKTEST_FEE_PER_TRADE
        trade_fees, state["entry_fee_remaining"] = _allocate_trade_fees(
            entry_fee_remaining=state["entry_fee_remaining"],
            exit_fee=config.BACKTEST_FEE_PER_TRADE,
            qty_exiting=state["qty"],
            position_qty_before_exit=state["qty"],
        )
        trades.append(
            _make_trade(
                symbol=symbol,
                entry_px=state["entry_px"],
                exit_px=fill_exit_px,
                qty=state["qty"],
                entry_date=state["entry_date"],
                exit_date=final_ts,
                exit_reason="end_of_test",
                fees=trade_fees,
                side=state["side"],
            )
        )
        state["qty"] = 0.0
        state["side"] = None

    final_equity = cash
    final_point = {"date": final_ts, "equity": round(final_equity, 2)}
    if equity_curve and equity_curve[-1]["date"] == final_ts:
        equity_curve[-1] = final_point
    else:
        equity_curve.append(final_point)

    stats = _compute_stats(trades, initial_cash, final_equity, equity_curve, timeframe=timeframe)
    return {
        "symbols": unique_symbols,
        "timeframe": timeframe,
        "initial_cash": initial_cash,
        "final_equity": round(final_equity, 2),
        "total_trades": len(trades),
        "trades": trades,
        "equity_curve": equity_curve,
        "benchmark": _spy_benchmark(timeframe, days, initial_cash),
        "selection_map": {date_str: sorted(list(members)) for date_str, members in leader_map.items()},
        "data_source": "provided_bars" if bars_by_symbol is not None else "broker_live_lookback",
        "point_in_time_safe": bars_by_symbol is not None or daily_watchlist_by_date is not None,
        **stats,
    }


def ablation_report(
    symbol: str,
    timeframe: str = "1Day",
    lookback_days: int | None = None,
    initial_cash: float = 100_000,
    components: list[str] | None = None,
) -> dict:
    days = lookback_days or _BT_LOOKBACK.get(timeframe, 365)
    bars = broker.get_bars(symbol, timeframe=timeframe, lookback_days=days)
    if len(bars) < 30:
        return {"error": f"Only {len(bars)} bars - need at least 30 for ablation."}

    df = _prepare_df(bars)
    spy_trend = _build_spy_trend(timeframe, days) if symbol != "SPY" else {}
    base_filter = _build_filter_context(symbol, timeframe, days, df, market_trend_by_date=spy_trend)
    event_context = _build_event_context(symbol, df)
    base_filter["market_event_context"] = _build_market_event_context(df)

    base = _evaluate_parameters(
        df=df,
        symbol=symbol,
        timeframe=timeframe,
        initial_cash=initial_cash,
        threshold=strategy._resolve_signal_threshold(timeframe, None),
        sl_atr_mult=config.SL_ATR_MULT,
        tp_atr_mult=config.TP_ATR_MULT,
        market_trend_by_date=spy_trend,
        filter_context=base_filter,
        event_context=event_context,
    )

    component_list = components or ["rsi", "macd", "ema", "bb", "volume", "momentum", "breakout", "supertrend", "vwap"]
    ablations = []
    for component in component_list:
        filter_context = dict(base_filter)
        filter_context["disabled_components"] = {component}
        result = _evaluate_parameters(
            df=df,
            symbol=symbol,
            timeframe=timeframe,
            initial_cash=initial_cash,
            threshold=strategy._resolve_signal_threshold(timeframe, None),
            sl_atr_mult=config.SL_ATR_MULT,
            tp_atr_mult=config.TP_ATR_MULT,
            market_trend_by_date=spy_trend,
            filter_context=filter_context,
            event_context=event_context,
        )
        ablations.append(
            {
                "component": component,
                "return_pct": result["total_return_pct"],
                "return_delta_pct": round(result["total_return_pct"] - base["total_return_pct"], 2),
                "sharpe": result["sharpe"],
                "sharpe_delta": round(result["sharpe"] - base["sharpe"], 3),
                "trades": result["trades"],
                "trade_delta": int(result["trades"] - base["trades"]),
            }
        )

    ablations.sort(key=lambda item: (item["return_delta_pct"], item["sharpe_delta"]))
    return {
        "symbol": symbol,
        "timeframe": timeframe,
        "base": {
            "return_pct": base["total_return_pct"],
            "sharpe": base["sharpe"],
            "trades": base["trades"],
        },
        "ablations": ablations,
    }
