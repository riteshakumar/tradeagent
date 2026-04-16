"""
Backtester with:
  - SPY benchmark comparison
  - Walk-forward validation
  - Parameter grid search optimization
  - Realistic trade modeling (SL/TP, slippage, per-trade fees)
"""
from __future__ import annotations

import itertools

import numpy as np
import pandas as pd

import broker
import config
import strategy

_BT_LOOKBACK = {
    "1Min": 5,
    "5Min": 20,
    "15Min": 60,
    "1Hour": 180,
    "1Day": 730,
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


def _compute_stats(trades: list[dict], initial_cash: float, final_equity: float, equity_curve: list[dict]) -> dict:
    winning = [t for t in trades if t["pnl"] > 0]
    losing = [t for t in trades if t["pnl"] <= 0]
    total_loss = sum(t["pnl"] for t in losing)

    win_rate = (len(winning) / len(trades) * 100) if trades else 0
    avg_win = float(np.mean([t["pnl"] for t in winning])) if winning else 0.0
    avg_loss = float(np.mean([t["pnl"] for t in losing])) if losing else 0.0
    profit_factor = abs(sum(t["pnl"] for t in winning) / total_loss) if total_loss != 0 else float("inf")

    eq_vals = [e["equity"] for e in equity_curve]
    if len(eq_vals) > 1:
        rets = np.diff(eq_vals) / np.array(eq_vals[:-1])
        sharpe = float(np.mean(rets) / np.std(rets) * np.sqrt(252)) if np.std(rets) > 0 else 0.0
    else:
        sharpe = 0.0
    eq_series = pd.Series(eq_vals)
    max_dd = float(((eq_series.cummax() - eq_series) / eq_series.cummax()).max() * 100) if len(eq_series) else 0.0

    return {
        "total_return_pct": round((final_equity - initial_cash) / initial_cash * 100, 2),
        "win_rate_pct": round(win_rate, 2),
        "avg_win": round(avg_win, 2),
        "avg_loss": round(avg_loss, 2),
        "profit_factor": round(profit_factor, 2) if profit_factor != float("inf") else "∞",
        "sharpe": round(sharpe, 3),
        "max_drawdown_pct": round(max_dd, 2),
    }


def _signal_for_threshold(score: int, threshold: int) -> str:
    if score >= threshold:
        return "buy"
    if score <= -threshold:
        return "sell"
    return "hold"


def _simulate(
    df: pd.DataFrame,
    symbol: str,
    initial_cash: float,
    threshold: int,
    stop_loss_pct: float,
    take_profit_pct: float,
    slippage_bps: float,
    fee_per_trade: float,
    warmup_override: int | None = None,
    market_trend_by_date: dict[str, int] | None = None,
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

        # Tick down cooldown counter
        if stop_cooldown > 0:
            stop_cooldown -= 1

        # Update trailing peak whenever we hold a position
        if position_qty > 0:
            if price > peak_px:
                peak_px = price

        # Intrabar risk exits (trailing stop trails from peak_px)
        if position_qty > 0:
            exit_on_bar = _check_bar_exit(entry_px, peak_px, bar, stop_loss_pct, take_profit_pct)
            if exit_on_bar is not None:
                raw_exit_px, reason = exit_on_bar
                fill_exit_px = _apply_slippage(raw_exit_px, "sell", slippage_bps)
                cash += position_qty * fill_exit_px - fee_per_trade
                trades.append(
                    _make_trade(
                        symbol=symbol,
                        entry_px=entry_px,
                        exit_px=fill_exit_px,
                        qty=position_qty,
                        entry_date=entry_date,
                        exit_date=ts,
                        exit_reason=reason,
                        fees=2 * fee_per_trade,
                    )
                )
                position_qty = 0
                entry_px = 0.0
                peak_px = 0.0
                entry_atr = 0.0
                partial_done = False
                entry_date = ""
                if "stop" in reason:
                    stop_cooldown = _STOP_COOLDOWN_BARS

        # Market trend gate: look up SPY status for this bar's date
        mt = 0
        if market_trend_by_date:
            mt = market_trend_by_date.get(bar_date, 0)

        sig = strategy.compute_signals(window.to_dict("records"), market_trend=mt)
        signal = _signal_for_threshold(sig["score"], threshold)
        if mt == -1 and signal == "buy":
            signal = "hold"

        # ------------------------------------------------------------------
        # Partial scale-out: sell 50% when price reaches entry + 1.5×ATR.
        # Locks in profit on half the position; trails the rest with stop.
        # ------------------------------------------------------------------
        if position_qty >= 2 and not partial_done and entry_atr > 0:
            partial_target = entry_px + 1.5 * entry_atr
            if price >= partial_target:
                partial_qty = position_qty // 2
                fill_partial = _apply_slippage(price, "sell", slippage_bps)
                cash += partial_qty * fill_partial - fee_per_trade
                trades.append(
                    _make_trade(
                        symbol=symbol,
                        entry_px=entry_px,
                        exit_px=fill_partial,
                        qty=partial_qty,
                        entry_date=entry_date,
                        exit_date=ts,
                        exit_reason="partial_profit",
                        fees=2 * fee_per_trade,
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

        elif signal == "sell" and position_qty > 0:
            fill_exit_px = _apply_slippage(price, "sell", slippage_bps)
            cash += position_qty * fill_exit_px - fee_per_trade
            trades.append(
                _make_trade(
                    symbol=symbol,
                    entry_px=entry_px,
                    exit_px=fill_exit_px,
                    qty=position_qty,
                    entry_date=entry_date,
                    exit_date=ts,
                    exit_reason="signal_exit",
                    fees=2 * fee_per_trade,
                )
            )
            position_qty = 0
            entry_px = 0.0
            peak_px = 0.0
            entry_atr = 0.0
            partial_done = False
            entry_date = ""

        equity_curve.append({"date": ts, "equity": round(cash + position_qty * price, 2)})

    final_price = float(df["c"].iloc[-1])
    final_ts = df["t"].iloc[-1].strftime("%Y-%m-%d %H:%M")
    final_equity = cash + position_qty * final_price
    if position_qty > 0:
        fill_exit_px = _apply_slippage(final_price, "sell", slippage_bps)
        cash += position_qty * fill_exit_px - fee_per_trade
        trades.append(
            _make_trade(
                symbol=symbol,
                entry_px=entry_px,
                exit_px=fill_exit_px,
                qty=position_qty,
                entry_date=entry_date,
                exit_date=final_ts,
                exit_reason="end_of_test",
                fees=2 * fee_per_trade,
            )
        )
        final_equity = cash

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
    Fetch SPY bars and return a date → market_trend dict.
    +1 = SPY close above its 200-day EMA (bull market)
    -1 = SPY close below its 200-day EMA (bear market)
    Keys are "YYYY-MM-DD" strings for easy lookup by bar date.
    Falls back to empty dict (neutral) if SPY data unavailable.
    """
    try:
        spy_bars = broker.get_bars("SPY", timeframe=timeframe, lookback_days=days)
        if not spy_bars:
            return {}
        spy_df = pd.DataFrame(spy_bars)
        spy_df["c"] = spy_df["c"].astype(float)
        spy_df["t"] = pd.to_datetime(spy_df["t"])
        ema200 = spy_df["c"].ewm(span=200, adjust=False).mean()
        trend: dict[str, int] = {}
        for idx in range(len(spy_df)):
            date_str = spy_df["t"].iloc[idx].strftime("%Y-%m-%d")
            trend[date_str] = 1 if spy_df["c"].iloc[idx] >= ema200.iloc[idx] else -1
        return trend
    except Exception:
        return {}


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

    df = pd.DataFrame(bars)
    df["c"] = df["c"].astype(float)
    df["h"] = df["h"].astype(float)
    df["l"] = df["l"].astype(float)
    df["t"] = pd.to_datetime(df["t"])

    # Pre-build SPY trend dict for market regime gate (skip SPY itself)
    spy_trend = _build_spy_trend(timeframe, days) if symbol != "SPY" else {}

    trades, equity_curve, final_equity = _simulate(
        df=df,
        symbol=symbol,
        initial_cash=initial_cash,
        threshold=config.SIGNAL_THRESHOLD,
        stop_loss_pct=config.STOP_LOSS_PCT,
        take_profit_pct=config.TAKE_PROFIT_PCT,
        slippage_bps=config.BACKTEST_SLIPPAGE_BPS,
        fee_per_trade=config.BACKTEST_FEE_PER_TRADE,
        market_trend_by_date=spy_trend,
    )
    stats = _compute_stats(trades, initial_cash, final_equity, equity_curve)
    benchmark = _spy_benchmark(timeframe, days, initial_cash)

    return {
        "symbol": symbol,
        "timeframe": timeframe,
        "initial_cash": initial_cash,
        "final_equity": round(final_equity, 2),
        "total_trades": len(trades),
        "trades": trades,
        "equity_curve": equity_curve,
        "benchmark": benchmark,
        "slippage_bps": config.BACKTEST_SLIPPAGE_BPS,
        "fee_per_trade": config.BACKTEST_FEE_PER_TRADE,
        **stats,
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

    df = pd.DataFrame(bars)
    df["c"] = df["c"].astype(float)
    df["h"] = df["h"].astype(float)
    df["l"] = df["l"].astype(float)
    df["t"] = pd.to_datetime(df["t"])

    spy_trend = _build_spy_trend(timeframe, lookback_days) if symbol != "SPY" else {}

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

        trades, equity_curve, final_equity = _simulate(
            df=fold_df,
            symbol=symbol,
            initial_cash=initial_cash,
            threshold=config.SIGNAL_THRESHOLD,
            stop_loss_pct=config.STOP_LOSS_PCT,
            take_profit_pct=config.TAKE_PROFIT_PCT,
            slippage_bps=config.BACKTEST_SLIPPAGE_BPS,
            fee_per_trade=config.BACKTEST_FEE_PER_TRADE,
            warmup_override=split,
            market_trend_by_date=spy_trend,
        )
        stats = _compute_stats(trades, initial_cash, final_equity, equity_curve)
        folds.append(
            {
                "fold": i + 1,
                "oos_start": fold_df["t"].iloc[split].strftime("%Y-%m-%d"),
                "oos_end": fold_df["t"].iloc[-1].strftime("%Y-%m-%d"),
                "trades": len(trades),
                **stats,
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

    df = pd.DataFrame(bars)
    df["c"] = df["c"].astype(float)
    df["h"] = df["h"].astype(float)
    df["l"] = df["l"].astype(float)
    df["t"] = pd.to_datetime(df["t"])

    spy_trend = _build_spy_trend(timeframe, lookback_days) if symbol != "SPY" else {}

    thresholds = [2, 3, 4, 5]
    sl_values = [0.02, 0.05, 0.08]
    tp_values = [0.05, 0.10, 0.15, 0.20]

    results = []
    for threshold, sl, tp in itertools.product(thresholds, sl_values, tp_values):
        trades, equity_curve, final_equity = _simulate(
            df=df,
            symbol=symbol,
            initial_cash=initial_cash,
            threshold=threshold,
            stop_loss_pct=sl,
            take_profit_pct=tp,
            slippage_bps=config.BACKTEST_SLIPPAGE_BPS,
            fee_per_trade=config.BACKTEST_FEE_PER_TRADE,
            market_trend_by_date=spy_trend,
        )
        stats = _compute_stats(trades, initial_cash, final_equity, equity_curve)
        results.append(
            {
                "threshold": threshold,
                "sl_pct": f"{sl * 100:.0f}%",
                "tp_pct": f"{tp * 100:.0f}%",
                "trades": len(trades),
                "return": stats["total_return_pct"],
                "sharpe": stats["sharpe"],
                "win_rate": stats["win_rate_pct"],
                "max_dd": stats["max_drawdown_pct"],
            }
        )

    results.sort(key=lambda r: (r["sharpe"], r["return"]), reverse=True)
    best = results[0] if results else {}
    return {"symbol": symbol, "best": best, "results": results[:20]}
