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
import risk
import strategy

_BT_LOOKBACK = {
    "1Min": 5,
    "5Min": 20,
    "15Min": 60,
    "1Hour": 180,
    "1Day": 730,
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
    "1Day": "1Hour",
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


def _apply_slippage(price: float, side: str, slippage_bps: float) -> float:
    slip = slippage_bps / 10_000.0
    if side == "buy":
        return price * (1 + slip)
    return price * (1 - slip)


def _check_bar_exit(
    entry_price: float,
    peak_price: float,
    bar: pd.Series,
    stop_loss_pct: float,
    take_profit_pct: float,
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
) -> dict:
    pnl = (exit_px - entry_px) * qty - fees
    notional = qty * entry_px
    return {
        "symbol": symbol,
        "entry": round(entry_px, 2),
        "exit": round(exit_px, 2),
        "qty": qty,
        "pnl": round(pnl, 2),
        "pnl_pct": round((pnl / notional) * 100, 2) if notional > 0 else 0.0,
        "entry_date": entry_date,
        "exit_date": exit_date,
        "exit_reason": exit_reason,
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
    return max(_MIN_TRADES_BY_TIMEFRAME.get(timeframe, 3), max(1, int(n_bars * 0.01)))


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
                        broker.get_bars(symbol, timeframe=higher_tf, lookback_days=max(lookback_days, 90))
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
                    broker.get_bars(peer, timeframe="1Day", lookback_days=max(lookback_days, 30))
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
    if signal == "sell" and higher_tf_signal == "buy":
        return "hold"

    if signal == "buy" and filter_context:
        peer_timelines = filter_context.get("peer_daily_signals", [])
        peer_signals = [_lookup_timeline_before(timeline, ts) for timeline in peer_timelines]
        known_peer_signals = [peer_signal for peer_signal in peer_signals if peer_signal is not None]
        if known_peer_signals and len(known_peer_signals) == len(peer_timelines) and all(
            peer_signal == "sell" for peer_signal in known_peer_signals
        ):
            return "hold"

    return signal


def _simulate(
    df: pd.DataFrame,
    symbol: str,
    timeframe: str,
    initial_cash: float,
    threshold: int,
    stop_loss_pct: float,
    take_profit_pct: float,
    slippage_bps: float,
    fee_per_trade: float,
    warmup_override: int | None = None,
    market_trend_by_date: dict[str, int] | None = None,
    filter_context: dict[str, object] | None = None,
) -> tuple[list[dict], list[dict], float]:
    """
    Simulate trades on df.

    market_trend_by_date: dict mapping "YYYY-MM-DD" → +1 (SPY bullish) or -1 (SPY bearish).
    When SPY is bearish, buy signals are suppressed via strategy.compute_signals(market_trend=-1).
    """
    warmup = warmup_override if warmup_override is not None else min(20, len(df) // 4)
    cash = float(initial_cash)
    position_qty = 0
    entry_px = 0.0
    peak_px = 0.0       # Trailing stop: highest close since entry
    entry_atr = 0.0     # ATR at entry time — used for partial scale-out target
    partial_done = False  # True once the first 50% scale-out has been taken
    entry_date = ""
    entry_fee_remaining = 0.0
    stop_cooldown = 0   # bars remaining before new entry allowed after a stop-loss
    _STOP_COOLDOWN_BARS = 3
    trades: list[dict] = []
    equity_curve: list[dict] = []

    for i in range(warmup, len(df)):
        window = df.iloc[:i]
        bar = df.iloc[i]
        price = float(bar["c"])
        ts = bar["t"].strftime("%Y-%m-%d %H:%M")
        bar_date = ts[:10]  # "YYYY-MM-DD"
        exited_this_bar = False

        # Tick down cooldown counter
        if stop_cooldown > 0:
            stop_cooldown -= 1

        # Intrabar risk exits use the trailing peak from completed bars only.
        # We update peak_px after this bar is processed so the current close
        # cannot tighten the stop before the same bar's high/low are evaluated.
        if position_qty > 0:
            exit_on_bar = _check_bar_exit(entry_px, peak_px, bar, stop_loss_pct, take_profit_pct)
            if exit_on_bar is not None:
                position_before_exit = position_qty
                raw_exit_px, reason = exit_on_bar
                fill_exit_px = _apply_slippage(raw_exit_px, "sell", slippage_bps)
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
                        exit_reason=reason,
                        fees=trade_fees,
                    )
                )
                position_qty = 0
                entry_px = 0.0
                peak_px = 0.0
                entry_atr = 0.0
                partial_done = False
                entry_date = ""
                entry_fee_remaining = 0.0
                if "stop" in reason:
                    stop_cooldown = _STOP_COOLDOWN_BARS
                exited_this_bar = True

        # Market trend gate: look up SPY status for this bar's date
        mt = 0
        if market_trend_by_date:
            mt = market_trend_by_date.get(bar_date, 0)

        if exited_this_bar:
            equity_curve.append({"date": ts, "equity": round(cash, 2)})
            continue

        sig = strategy.compute_signals(
            window.to_dict("records"),
            market_trend=mt,
            threshold=threshold,
            timeframe=timeframe,
        )
        signal = sig.get("signal") or _signal_for_threshold(int(sig.get("score") or 0), threshold)
        signal = _apply_historical_signal_filters(signal, window, bar, timeframe, filter_context=filter_context)

        # ------------------------------------------------------------------
        # Partial scale-out: sell 50% when price reaches entry + 1.5×ATR.
        # Locks in profit on half the position; trails the rest with stop.
        # ------------------------------------------------------------------
        if position_qty >= 2 and not partial_done and entry_atr > 0:
            partial_target = entry_px + 1.5 * entry_atr
            if price >= partial_target:
                position_before_exit = position_qty
                partial_qty = position_qty // 2
                fill_partial = _apply_slippage(price, "sell", slippage_bps)
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
                    )
                )
                position_qty -= partial_qty
                partial_done = True

        if signal == "buy" and position_qty == 0 and cash > price and stop_cooldown == 0:
            qty = max(1, int((cash * config.MAX_POSITION_PCT) / price))
            fill_entry_px = _apply_slippage(price, "buy", slippage_bps)
            required_cash = qty * fill_entry_px + fee_per_trade
            if cash >= required_cash:
                cash -= required_cash
                position_qty = qty
                entry_px = fill_entry_px
                peak_px = fill_entry_px
                entry_atr = float(sig.get("atr") or 0.0)
                partial_done = False
                entry_date = ts
                entry_fee_remaining = float(fee_per_trade)

        elif signal == "sell" and position_qty > 0:
            position_before_exit = position_qty
            fill_exit_px = _apply_slippage(price, "sell", slippage_bps)
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
                )
            )
            position_qty = 0
            entry_px = 0.0
            peak_px = 0.0
            entry_atr = 0.0
            partial_done = False
            entry_date = ""
            entry_fee_remaining = 0.0

        if position_qty > 0:
            peak_px = max(peak_px, price)

        equity_curve.append({"date": ts, "equity": round(cash + position_qty * price, 2)})

    final_price = float(df["c"].iloc[-1])
    final_ts = df["t"].iloc[-1].strftime("%Y-%m-%d %H:%M")
    final_equity = cash + position_qty * final_price
    if position_qty > 0:
        position_before_exit = position_qty
        fill_exit_px = _apply_slippage(final_price, "sell", slippage_bps)
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
                exit_date=final_ts,
                exit_reason="end_of_test",
                fees=trade_fees,
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
        spy_bars = broker.get_bars("SPY", timeframe="1Day", lookback_days=max(250, days + 250))
        if not spy_bars:
            return {}
        spy_df = pd.DataFrame(spy_bars)
        spy_df["c"] = spy_df["c"].astype(float)
        spy_df["t"] = pd.to_datetime(spy_df["t"])
        ema200 = spy_df["c"].ewm(span=200, adjust=False).mean()
        raw_trend = np.where(spy_df["c"] >= ema200, 1, -1)
        date_strings = spy_df["t"].dt.strftime("%Y-%m-%d")
        trend: dict[str, int] = {}
        for idx in range(1, len(spy_df)):
            trend[date_strings.iloc[idx]] = int(raw_trend[idx - 1])
        return trend
    except Exception:
        return {}


def _parameter_grid() -> list[tuple[int, float, float]]:
    thresholds = [2, 3, 4, 5]
    sl_values = [0.02, 0.05, 0.08]
    tp_values = [0.05, 0.10, 0.15, 0.20]
    return list(itertools.product(thresholds, sl_values, tp_values))


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
    stop_loss_pct: float,
    take_profit_pct: float,
    market_trend_by_date: dict[str, int] | None = None,
    filter_context: dict[str, object] | None = None,
    warmup_override: int | None = None,
) -> dict:
    trades, equity_curve, final_equity = _simulate(
        df=df,
        symbol=symbol,
        timeframe=timeframe,
        initial_cash=initial_cash,
        threshold=threshold,
        stop_loss_pct=stop_loss_pct,
        take_profit_pct=take_profit_pct,
        slippage_bps=config.BACKTEST_SLIPPAGE_BPS,
        fee_per_trade=config.BACKTEST_FEE_PER_TRADE,
        warmup_override=warmup_override,
        market_trend_by_date=market_trend_by_date,
        filter_context=filter_context,
    )
    stats = _compute_stats(trades, initial_cash, final_equity, equity_curve, timeframe=timeframe)
    return {
        "threshold": threshold,
        "stop_loss_pct": stop_loss_pct,
        "take_profit_pct": take_profit_pct,
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
            stop_loss_pct=sl,
            take_profit_pct=tp,
            market_trend_by_date=market_trend_by_date,
            filter_context=filter_context,
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
                    stop_loss_pct=sl,
                    take_profit_pct=tp,
                    market_trend_by_date=market_trend_by_date,
                    filter_context=filter_context,
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
) -> dict:
    days = lookback_days or _BT_LOOKBACK.get(timeframe, 365)
    bars = broker.get_bars(symbol, timeframe=timeframe, lookback_days=days)

    n = len(bars)
    if n < 10:
        return {
            "error": (
                f"Only {n} bars returned for {symbol} ({timeframe}, {days}d lookback). "
                "Try a longer lookback or a higher timeframe (e.g. 1Day)."
            )
        }

    df = _prepare_df(bars)

    # Pre-build SPY trend dict for market regime gate (skip SPY itself)
    spy_trend = _build_spy_trend(timeframe, days) if symbol != "SPY" else {}
    filter_context = _build_filter_context(symbol, timeframe, days, df, market_trend_by_date=spy_trend)

    result = _evaluate_parameters(
        df=df,
        symbol=symbol,
        timeframe=timeframe,
        initial_cash=initial_cash,
        threshold=strategy._resolve_signal_threshold(timeframe, None),
        stop_loss_pct=config.STOP_LOSS_PCT,
        take_profit_pct=config.TAKE_PROFIT_PCT,
        market_trend_by_date=spy_trend,
        filter_context=filter_context,
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
        **{
            k: v
            for k, v in result.items()
            if k not in {"equity_curve", "final_equity", "trade_records", "threshold", "stop_loss_pct", "take_profit_pct", "trades"}
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
        )
        if not best_params:
            continue

        oos_result = _evaluate_parameters(
            df=fold_df,
            symbol=symbol,
            timeframe=timeframe,
            initial_cash=initial_cash,
            threshold=best_params["threshold"],
            stop_loss_pct=best_params["stop_loss_pct"],
            take_profit_pct=best_params["take_profit_pct"],
            market_trend_by_date=spy_trend,
            filter_context=filter_context,
            warmup_override=split,
        )
        folds.append(
            {
                "fold": i + 1,
                "oos_start": fold_df["t"].iloc[split].strftime("%Y-%m-%d"),
                "oos_end": fold_df["t"].iloc[-1].strftime("%Y-%m-%d"),
                "train_threshold": best_params["threshold"],
                "train_sl_pct": f"{best_params['stop_loss_pct'] * 100:.0f}%",
                "train_tp_pct": f"{best_params['take_profit_pct'] * 100:.0f}%",
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
        )
        if not best_params:
            break

        oos_result = _evaluate_parameters(
            df=fold_df,
            symbol=symbol,
            timeframe=timeframe,
            initial_cash=initial_cash,
            threshold=best_params["threshold"],
            stop_loss_pct=best_params["stop_loss_pct"],
            take_profit_pct=best_params["take_profit_pct"],
            market_trend_by_date=spy_trend,
            filter_context=filter_context,
            warmup_override=train_end,
        )
        folds.append({
            "fold": i + 1,
            "train_bars": train_end,
            "oos_bars": test_end - train_end,
            "oos_start": fold_df["t"].iloc[train_end].strftime("%Y-%m-%d"),
            "oos_end": fold_df["t"].iloc[-1].strftime("%Y-%m-%d"),
            "train_threshold": best_params["threshold"],
            "train_sl_pct": f"{best_params['stop_loss_pct'] * 100:.0f}%",
            "train_tp_pct": f"{best_params['take_profit_pct'] * 100:.0f}%",
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
    split = max(30, int(len(df) * 0.7))
    if len(df) - split < 5:
        return {"error": "Need more data for train/validation optimisation split."}
    train_df = df.iloc[:split].reset_index(drop=True)
    min_train_trades = _min_trades_for_timeframe(timeframe, len(train_df))
    min_validation_trades = max(1, min_train_trades // 2)

    results = []
    for threshold, sl, tp in _parameter_grid():
        train_result = _evaluate_parameters(
            df=train_df,
            symbol=symbol,
            timeframe=timeframe,
            initial_cash=initial_cash,
            threshold=threshold,
            stop_loss_pct=sl,
            take_profit_pct=tp,
            market_trend_by_date=spy_trend,
            filter_context=filter_context,
        )
        if train_result["trades"] < min_train_trades:
            continue

        validation_result = _evaluate_parameters(
            df=df,
            symbol=symbol,
            timeframe=timeframe,
            initial_cash=initial_cash,
            threshold=threshold,
            stop_loss_pct=sl,
            take_profit_pct=tp,
            market_trend_by_date=spy_trend,
            filter_context=filter_context,
            warmup_override=split,
        )
        if validation_result["trades"] < min_validation_trades:
            continue

        results.append(
            {
                "threshold": threshold,
                "sl_pct": f"{sl * 100:.0f}%",
                "tp_pct": f"{tp * 100:.0f}%",
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
