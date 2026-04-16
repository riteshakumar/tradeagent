"""
Main trading loop.
Run: python main.py
"""
from __future__ import annotations

import logging
import time
from datetime import datetime, timezone

import agent
import alerts
import broker
import config
import events
import risk
import settings_store
import shadow_book
import strategy
import watchlist_store

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    handlers=[logging.StreamHandler(), logging.FileHandler("trade.log")],
)
log = logging.getLogger(__name__)

# In-memory trailing stop state: symbol → highest price seen since entry
_peak_prices: dict[str, float] = {}

# In-memory partial scale-out tracking: symbol → True once 50% already sold
_partial_done: dict[str, bool] = {}


def _get_clock():
    from alpaca.trading.client import TradingClient

    client = TradingClient(config.ALPACA_API_KEY, config.ALPACA_SECRET_KEY, paper=config.PAPER_TRADING)
    return client.get_clock()


def _get_market_trend() -> int:
    """
    Return +1 if SPY is above its 200-day EMA (bull market), -1 if below.
    Returns 0 (neutral) on any error so trading is never inadvertently blocked.
    """
    try:
        spy_bars = broker.get_bars("SPY", timeframe=config.BAR_TIMEFRAME)
        if not spy_bars or len(spy_bars) < 30:
            return 0
        import pandas as _pd
        closes = _pd.Series([float(b["c"]) for b in spy_bars])
        ema200 = closes.ewm(span=200, adjust=False).mean()
        return 1 if float(closes.iloc[-1]) >= float(ema200.iloc[-1]) else -1
    except Exception as exc:
        log.debug("SPY market trend check failed: %s", exc)
        return 0


def is_market_open() -> bool:
    return _get_clock().is_open


def _rank_by_relative_strength(watchlist: list[str]) -> list[str]:
    """
    Rank watchlist symbols by 20-day return relative to SPY.
    Returns top 60% (min 2) by relative strength — strongest performers first.
    Falls back to original order on any error.
    """
    try:
        spy_bars = broker.get_bars("SPY", timeframe="1Day", lookback_days=30)
        if not spy_bars or len(spy_bars) < 2:
            return watchlist
        spy_ret = float(spy_bars[-1]["c"]) / float(spy_bars[0]["c"]) - 1

        ranked: list[tuple[str, float]] = []
        for sym in watchlist:
            try:
                bars = broker.get_bars(sym, timeframe="1Day", lookback_days=30)
                if not bars or len(bars) < 2:
                    ranked.append((sym, 0.0))
                    continue
                sym_ret = float(bars[-1]["c"]) / float(bars[0]["c"]) - 1
                ranked.append((sym, sym_ret - spy_ret))
            except Exception:
                ranked.append((sym, 0.0))

        ranked.sort(key=lambda x: x[1], reverse=True)
        n = max(2, int(len(ranked) * 0.6))
        selected = [sym for sym, _ in ranked[:n]]
        log.info("RS ranking (top %d/%d): %s", n, len(ranked),
                 [(s, f"{rs:+.1%}") for s, rs in ranked[:n]])
        return selected
    except Exception as exc:
        log.debug("RS ranking failed: %s", exc)
        return watchlist


def _smart_sleep() -> None:
    """Sleep until near market open instead of polling frequently when closed."""
    try:
        clock = _get_clock()
        if clock.is_open:
            time.sleep(config.LOOP_INTERVAL_SEC)
            return
        now = datetime.now(timezone.utc)
        next_open = clock.next_open.replace(tzinfo=timezone.utc)
        secs = max(60, (next_open - now).total_seconds() - 60)
        log.info("Market closed. Sleeping %.1fh until %s.", secs / 3600.0, next_open.strftime("%Y-%m-%d %H:%M UTC"))
        time.sleep(secs)
    except Exception:
        time.sleep(config.LOOP_INTERVAL_SEC)


def _load_runtime_overrides() -> None:
    """Allow dashboard-adjusted runtime settings to take effect in the loop."""
    saved = settings_store.load()
    if "sl_pct" in saved:
        config.STOP_LOSS_PCT = float(saved["sl_pct"])
    if "tp_pct" in saved:
        config.TAKE_PROFIT_PCT = float(saved["tp_pct"])
    if "dry_run" in saved:
        config.DRY_RUN = bool(saved["dry_run"])
    if "allow_short" in saved:
        config.ALLOW_SHORT = bool(saved["allow_short"])
    if "shadow_mode" in saved:
        config.SHADOW_MODE = bool(saved["shadow_mode"])

    if "daily_loss_stop_pct" in saved:
        config.DAILY_LOSS_STOP_PCT = max(0.0, min(1.0, float(saved["daily_loss_stop_pct"])))
    if "max_sector_exposure_pct" in saved:
        config.MAX_SECTOR_EXPOSURE_PCT = max(0.0, min(1.0, float(saved["max_sector_exposure_pct"])))
    if "enable_correlation_cap" in saved:
        config.ENABLE_CORRELATION_CAP = bool(saved["enable_correlation_cap"])
    if "max_correlation" in saved:
        config.MAX_CORRELATION = max(0.0, min(1.0, float(saved["max_correlation"])))
    if "max_correlated_positions" in saved:
        config.MAX_CORRELATED_POSITIONS = max(1, int(saved["max_correlated_positions"]))
    if "correlation_lookback_days" in saved:
        config.CORRELATION_LOOKBACK_DAYS = max(20, min(365, int(saved["correlation_lookback_days"])))

    if config.SHADOW_MODE:
        config.DRY_RUN = True


def _current_positions() -> list[dict]:
    if not config.SHADOW_MODE:
        return broker.get_positions()
    shadow = shadow_book.summary()["open_positions"]
    rows = []
    for p in shadow:
        qty = float(p["qty"])
        entry = float(p["entry_price"])
        current = float(p.get("last_price", entry))
        side = p.get("side", "long")
        pnl = (current - entry) * qty if side == "long" else (entry - current) * qty
        pnl_pct = (pnl / (entry * qty)) if entry > 0 and qty > 0 else 0.0
        rows.append(
            {
                "symbol": p["symbol"],
                "qty": qty,
                "side": side,
                "avg_entry": entry,
                "current_price": current,
                "market_value": abs(current * qty),
                "unrealized_pnl": pnl,
                "unrealized_pnl_pct": pnl_pct,
            }
        )
    return rows


def _check_sl_tp(position: dict) -> bool:
    symbol = position["symbol"]
    current_price = float(position["current_price"])
    avg_entry = float(position.get("avg_entry", current_price))
    side = position.get("side", "long")

    # Update trailing peak for this position
    if symbol not in _peak_prices:
        _peak_prices[symbol] = avg_entry
    if current_price > _peak_prices[symbol]:
        _peak_prices[symbol] = current_price
    peak = _peak_prices[symbol]

    # Trailing stop: trail from peak, not entry
    trailing_stop_hit = config.STOP_LOSS_PCT > 0 and current_price <= peak * (1 - config.STOP_LOSS_PCT)
    # pnl_pct still used for take-profit (measured from entry)
    pnl_pct = (current_price - avg_entry) / avg_entry if avg_entry > 0 else 0.0

    if trailing_stop_hit:
        log.warning(
            "%s: TRAILING STOP hit (price=%.2f peak=%.2f trail=%.2f%%) - closing %s",
            symbol, current_price, peak, config.STOP_LOSS_PCT * 100, side,
        )
        _peak_prices.pop(symbol, None)
        if config.SHADOW_MODE:
            trade = shadow_book.close_position(symbol, float(position["current_price"]), reason="stop_loss")
            if trade:
                log.info("SHADOW close %s via stop loss: pnl=$%.2f", symbol, trade["pnl"])
            return trade is not None
        if config.DRY_RUN:
            log.info("[DRY RUN] Would close %s at stop loss", symbol)
            return True
        result = broker.close_position(symbol)
        alerts.order_alert(symbol, "close", position["qty"], position["current_price"], result.get("order_id", ""))
        return True

    if config.TAKE_PROFIT_PCT > 0 and pnl_pct >= config.TAKE_PROFIT_PCT:
        log.info("%s: TAKE PROFIT hit (%.2f%%) - closing %s", symbol, pnl_pct * 100, side)
        _peak_prices.pop(symbol, None)
        if config.SHADOW_MODE:
            trade = shadow_book.close_position(symbol, float(position["current_price"]), reason="take_profit")
            if trade:
                log.info("SHADOW close %s via take profit: pnl=$%.2f", symbol, trade["pnl"])
            return trade is not None
        if config.DRY_RUN:
            log.info("[DRY RUN] Would close %s at take profit", symbol)
            return True
        result = broker.close_position(symbol)
        alerts.order_alert(symbol, "close", position["qty"], position["current_price"], result.get("order_id", ""))
        return True

    return False


def _place_buy(symbol: str, sig: dict, account: dict, positions: list[dict], watchlist: list[str]) -> bool:
    ok, reason = risk.pre_trade_checks(symbol, sig["price"], account, positions, watchlist=watchlist, atr=sig.get("atr"))
    if not ok:
        log.info("%s: pre-trade check failed - %s", symbol, reason)
        return False

    approved, reason = agent.evaluate_signal(symbol, sig)
    log.info("%s: agent=%s (%s)", symbol, "APPROVE" if approved else "REJECT", reason)
    if not approved:
        return False

    # Vol-targeting: pass realized_vol from signal for volatility-adjusted sizing
    qty = risk.compute_qty(
        sig["price"], account,
        atr=sig.get("atr"),
        realized_vol=sig.get("regime_realized_vol"),
    )
    if config.SHADOW_MODE:
        shadow_book.record_intent(symbol, "buy", qty, sig["price"], sig["reason"], sig["score"])
        shadow_book.open_position(symbol, "long", qty, sig["price"], sig["reason"], sig["score"])
        risk.record_order(symbol)
        log.info("SHADOW BUY recorded: %s qty=%s @ $%.2f", symbol, qty, sig["price"])
        return True

    if config.DRY_RUN:
        log.info("[DRY RUN] Would BUY %s x %s @ $%.2f score=%s", qty, symbol, sig["price"], sig["score"])
        return True

    order = broker.place_market_order(symbol, qty, "buy")
    risk.record_order(symbol)
    alerts.order_alert(symbol, "buy", qty, sig["price"], order.get("id", ""))
    alerts.signal_alert(symbol, "buy", sig["score"], sig["price"], sig["reason"])
    log.info("BUY order placed: %s", order)
    return True


def _place_short(symbol: str, sig: dict, account: dict, positions: list[dict], watchlist: list[str]) -> bool:
    if not config.ALLOW_SHORT:
        return False
    if any(p["symbol"] == symbol and p.get("side") == "short" for p in positions):
        return False

    ok, reason = risk.pre_trade_checks(symbol, sig["price"], account, positions, watchlist=watchlist, atr=sig.get("atr"))
    if not ok:
        log.info("%s: short pre-trade check failed - %s", symbol, reason)
        return False

    approved, reason = agent.evaluate_signal(symbol, sig)
    log.info("%s: agent=%s (%s)", symbol, "APPROVE" if approved else "REJECT", reason)
    if not approved:
        return False

    qty = risk.compute_qty(sig["price"], account, atr=sig.get("atr"))
    if config.SHADOW_MODE:
        shadow_book.record_intent(symbol, "short", qty, sig["price"], sig["reason"], sig["score"])
        shadow_book.open_position(symbol, "short", qty, sig["price"], sig["reason"], sig["score"])
        risk.record_order(symbol)
        log.info("SHADOW SHORT recorded: %s qty=%s @ $%.2f", symbol, qty, sig["price"])
        return True

    if config.DRY_RUN:
        log.info("[DRY RUN] Would SHORT %s x %s @ $%.2f score=%s", qty, symbol, sig["price"], sig["score"])
        return True

    order = broker.place_market_order(symbol, qty, "sell")
    risk.record_order(symbol)
    alerts.order_alert(symbol, "short", qty, sig["price"], order.get("id", ""))
    alerts.signal_alert(symbol, "sell", sig["score"], sig["price"], sig["reason"])
    log.info("SHORT order placed: %s", order)
    return True


def _close_long(symbol: str, sig: dict, positions: list[dict], watchlist: list[str]) -> bool:
    pos = next((p for p in positions if p["symbol"] == symbol), None)
    if not pos:
        return False
    if pos.get("side") == "short":
        return False
    if watchlist and not risk.is_watchlist_allowed(symbol, watchlist):
        return False

    approved, reason = agent.evaluate_signal(symbol, sig)
    log.info("%s: agent=%s (%s)", symbol, "APPROVE" if approved else "REJECT", reason)
    if not approved:
        return False

    if config.SHADOW_MODE:
        trade = shadow_book.close_position(symbol, sig["price"], reason="sell_signal")
        if trade:
            log.info("SHADOW LONG closed %s: pnl=$%.2f", symbol, trade["pnl"])
            return True
        return False

    if config.DRY_RUN:
        log.info("[DRY RUN] Would CLOSE LONG %s", symbol)
        return True

    _peak_prices.pop(symbol, None)
    result = broker.close_position(symbol)
    alerts.order_alert(symbol, "sell", pos["qty"], pos["current_price"], result.get("order_id", ""))
    alerts.signal_alert(symbol, "sell", sig["score"], sig["price"], sig["reason"])
    log.info("Long position closed: %s", result)
    return True


def _close_short(symbol: str, sig: dict, positions: list[dict]) -> bool:
    if not config.ALLOW_SHORT:
        return False
    pos = next((p for p in positions if p["symbol"] == symbol and p.get("side") == "short"), None)
    if not pos:
        return False

    approved, reason = agent.evaluate_signal(symbol, sig)
    log.info("%s: agent=%s (%s)", symbol, "APPROVE" if approved else "REJECT", reason)
    if not approved:
        return False

    if config.SHADOW_MODE:
        trade = shadow_book.close_position(symbol, sig["price"], reason="cover_signal")
        if trade:
            log.info("SHADOW SHORT covered %s: pnl=$%.2f", symbol, trade["pnl"])
            return True
        return False

    if config.DRY_RUN:
        log.info("[DRY RUN] Would COVER SHORT %s", symbol)
        return True

    result = broker.close_position(symbol)
    alerts.order_alert(symbol, "cover", pos["qty"], pos["current_price"], result.get("order_id", ""))
    log.info("Short covered: %s", result)
    return True


def _maybe_run_events(symbol: str, sig: dict) -> dict:
    """Auto-trigger earnings event analysis when relevant news appears."""
    if not config.USE_AGENT:
        return sig
    try:
        news = events.fetch_news(symbols=[symbol], keywords="earnings EPS guidance", limit=3)
        has_earnings = any(
            any(kw in n["headline"].lower() for kw in ("earnings", "eps", "guidance", "beat", "miss"))
            for n in news
            if n["headline"] and "[news fetch error" not in n["headline"]
        )
        if has_earnings:
            log.info("%s: earnings news detected - running event analysis", symbol)
            event_result = events.get_event_score(symbol, run_earnings=True, run_geo=False, run_macro=False)
            sig = strategy.apply_event_score(sig, event_result)
            log.info("%s: post-event score=%s signal=%s", symbol, sig["score"], sig["signal"])
    except Exception as exc:
        log.debug("%s: event check skipped - %s", symbol, exc)
    return sig


def _process_symbol(symbol: str, watchlist: list[str], market_trend: int = 0) -> None:
    account = broker.get_account()
    positions = _current_positions()
    pos = next((p for p in positions if p["symbol"] == symbol), None)
    if pos and _check_sl_tp(pos):
        return

    bars = broker.get_bars(symbol, timeframe=config.BAR_TIMEFRAME)
    earnings_soon = events.is_earnings_period(symbol) if config.USE_AGENT else False
    if earnings_soon:
        log.info("%s: earnings period detected - buy suppressed", symbol)
    sig = strategy.compute_signals(bars, market_trend=market_trend, earnings_soon=earnings_soon)
    sig = _maybe_run_events(symbol, sig)
    if config.SHADOW_MODE and sig.get("price"):
        shadow_book.update_mark(symbol, sig["price"])

    log.info(
        "%s: regime=%s mkt_trend=%s adx=%.1f signal=%s score=%s reason=%s",
        symbol,
        sig.get("regime", "n/a"),
        "bull" if market_trend == 1 else ("bear" if market_trend == -1 else "?"),
        sig.get("adx") or 0.0,
        sig["signal"],
        sig["score"],
        sig["reason"],
    )

    if sig["signal"] == "buy":
        changed = _close_short(symbol, sig, positions)
        if changed:
            account = broker.get_account()
            positions = _current_positions()
        _place_buy(symbol, sig, account, positions, watchlist)

    elif sig["signal"] == "sell":
        changed = _close_long(symbol, sig, positions, watchlist)
        if changed:
            account = broker.get_account()
            positions = _current_positions()
        _place_short(symbol, sig, account, positions, watchlist)


def get_active_watchlist() -> list[str]:
    stored = watchlist_store.load()
    return list(dict.fromkeys(config.WATCHLIST + stored))


def run_once() -> None:
    log.info("=== Tick start ===")
    _load_runtime_overrides()

    if not is_market_open():
        log.info("Market closed - skipping tick.")
        return

    account = broker.get_account()
    daily = risk.update_daily_loss_guard(account)
    drawdown = risk.evaluate_drawdown(account)
    if drawdown["just_triggered"]:
        alerts.drawdown_alert(drawdown["drawdown_pct"] * 100, account["equity"])
    if daily["halted"]:
        log.warning("DAILY LOSS STOP active (%.2f%%)", daily["daily_loss_pct"] * 100)
    if drawdown["halted"]:
        log.warning("MAX DRAWDOWN HALT active (%.2f%%)", drawdown["drawdown_pct"] * 100)

    positions = _current_positions()
    log.info("Account: equity=$%.2f cash=$%.2f", account["equity"], account["cash"])
    log.info("Open positions: %s", [f"{p['symbol']}:{p.get('side','long')}" for p in positions])

    watchlist = get_active_watchlist()
    watchlist = _rank_by_relative_strength(watchlist)  # trade only top RS symbols
    if config.SHADOW_MODE:
        log.info("[SHADOW MODE] Hypothetical orders only. Outcomes recorded to shadow_book.json")
    elif config.DRY_RUN:
        log.info("[DRY RUN] No orders will be placed.")

    # Fetch SPY market trend once per tick — shared across all symbols
    market_trend = _get_market_trend()
    log.info("Market trend (SPY vs EMA200): %s", "BULL" if market_trend == 1 else ("BEAR" if market_trend == -1 else "UNKNOWN"))

    for symbol in watchlist:
        try:
            _process_symbol(symbol, watchlist, market_trend=market_trend)
        except Exception as exc:
            log.error("%s: error during tick - %s", symbol, exc, exc_info=True)

    log.info("=== Tick end ===\n")


def main() -> None:
    config.validate_runtime()
    log.info("TradeAgent starting up.")
    log.info("Watchlist: %s", get_active_watchlist())
    log.info("Timeframe: %s | Loop: %ss", config.BAR_TIMEFRAME, config.LOOP_INTERVAL_SEC)
    log.info("SL: %.0f%% TP: %.0f%%", config.STOP_LOSS_PCT * 100, config.TAKE_PROFIT_PCT * 100)
    log.info(
        "Risk/trade: %.1f%% | Dry-run: %s | Shadow: %s | Short: %s",
        config.RISK_PER_TRADE_PCT * 100,
        config.DRY_RUN,
        config.SHADOW_MODE,
        config.ALLOW_SHORT,
    )

    while True:
        try:
            run_once()
        except Exception as exc:
            log.error("Unhandled error in main loop: %s", exc, exc_info=True)
        _smart_sleep()


if __name__ == "__main__":
    main()
