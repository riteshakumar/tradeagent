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


def _get_clock():
    from alpaca.trading.client import TradingClient

    client = TradingClient(config.ALPACA_API_KEY, config.ALPACA_SECRET_KEY, paper=config.PAPER_TRADING)
    return client.get_clock()


def is_market_open() -> bool:
    return _get_clock().is_open


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
    pnl_pct = float(position["unrealized_pnl_pct"])
    side = position.get("side", "long")

    if config.STOP_LOSS_PCT > 0 and pnl_pct <= -config.STOP_LOSS_PCT:
        log.warning("%s: STOP LOSS hit (%.2f%%) - closing %s", symbol, pnl_pct * 100, side)
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

    qty = risk.compute_qty(sig["price"], account, atr=sig.get("atr"))
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


def _process_symbol(symbol: str, watchlist: list[str]) -> None:
    account = broker.get_account()
    positions = _current_positions()
    pos = next((p for p in positions if p["symbol"] == symbol), None)
    if pos and _check_sl_tp(pos):
        return

    bars = broker.get_bars(symbol, timeframe=config.BAR_TIMEFRAME)
    sig = strategy.compute_signals(bars)
    sig = _maybe_run_events(symbol, sig)
    if config.SHADOW_MODE and sig.get("price"):
        shadow_book.update_mark(symbol, sig["price"])

    log.info(
        "%s: regime=%s signal=%s score=%s reason=%s",
        symbol,
        sig.get("regime", "n/a"),
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
    if config.SHADOW_MODE:
        log.info("[SHADOW MODE] Hypothetical orders only. Outcomes recorded to shadow_book.json")
    elif config.DRY_RUN:
        log.info("[DRY RUN] No orders will be placed.")

    for symbol in watchlist:
        try:
            _process_symbol(symbol, watchlist)
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
