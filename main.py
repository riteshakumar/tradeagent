"""
Main trading loop.
Run: python main.py
"""
from __future__ import annotations

import logging
import time
from datetime import datetime, timezone, date

import agent
import alerts
import broker
import config
import events
import risk
import screener
import settings_store
import shadow_book
import strategy
import trade_journal
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

_curated_blacklist: set[str] = set()   # tickers with bad news today
_curate_date: date | None = None       # date curation last ran
_position_stops: dict[str, float] = {} # symbol → per-position stop pct override
_exit_holds: dict[str, int] = {}       # symbol → consecutive exit-review holds
_last_rebalance_date: date | None = None


def _get_clock():
    from alpaca.trading.client import TradingClient

    client = TradingClient(config.ALPACA_API_KEY, config.ALPACA_SECRET_KEY, paper=config.PAPER_TRADING)
    return client.get_clock()


def _get_market_trend() -> int:
    """
    Return +1 if SPY is above its 200-day EMA (bull market), -1 if below.
    Always uses daily bars regardless of strategy timeframe so EMA200 is meaningful.
    Returns 0 (neutral) on any error so trading is never inadvertently blocked.
    Respects 'market_trend_override' from settings_store: 1=bull, -1=bear, 0=auto.
    """
    override = settings_store.get("market_trend_override", 0)
    if override in (1, -1):
        log.info("Market trend OVERRIDDEN via settings: %s", "BULL" if override == 1 else "BEAR")
        return int(override)
    try:
        spy_bars = broker.get_bars("SPY", timeframe="1Day", lookback_days=250)
        if not spy_bars or len(spy_bars) < 30:
            return 0
        import pandas as _pd
        closes = _pd.Series([float(b["c"]) for b in spy_bars])
        ema200 = closes.ewm(span=200, adjust=False).mean()
        return 1 if float(closes.iloc[-1]) >= float(ema200.iloc[-1]) else -1
    except Exception as exc:
        log.warning("SPY market trend check failed: %s", exc)
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
        log.warning("RS ranking failed — using original order: %s", exc)
        return watchlist


_HIGHER_TF: dict[str, str] = {
    "1Min": "1Day", "5Min": "1Day", "15Min": "1Day",
    "1Hour": "1Day", "1Day": "1Hour",
}

_PEER_OVERRIDE: dict[str, list[str]] = {
    "AAPL": ["MSFT", "GOOGL"], "MSFT": ["AAPL", "GOOGL"], "GOOGL": ["META", "MSFT"],
    "NVDA": ["AMD", "AVGO"],   "AMD":  ["NVDA", "INTC"],  "META": ["GOOGL", "SNAP"],
    "TSLA": ["GM", "RIVN"],    "JPM":  ["BAC", "GS"],     "BAC":  ["JPM", "WFC"],
    "XOM":  ["CVX", "COP"],    "AMZN": ["MSFT", "GOOGL"],
}


def _get_peers(symbol: str) -> list[str]:
    if symbol.upper() in _PEER_OVERRIDE:
        return _PEER_OVERRIDE[symbol.upper()]
    try:
        from screener import SECTOR_STOCKS
        sym = symbol.upper()
        for stocks in SECTOR_STOCKS.values():
            if sym in stocks:
                return [s for s in stocks if s != sym][:2]
    except Exception:
        pass
    return []


def _curate_watchlist(watchlist: list[str]) -> None:
    """
    On the first tick of each trading day, keyword-scan all watchlist tickers
    for negative news. Tickers with clearly negative sentiment are blacklisted
    for the rest of the day. Fast — no LLM calls.
    """
    global _curated_blacklist, _curate_date
    today = date.today()
    if _curate_date == today or not config.PREMARKET_CURATION_ENABLED:
        return

    _curated_blacklist = set()
    _curate_date = today
    log.info("=== Daily curation scan (%d symbols) ===", len(watchlist))
    for sym in watchlist:
        try:
            trend = events.sentiment_trend(sym)
            if trend < 0:
                _curated_blacklist.add(sym)
                log.warning("Curation: %s BLACKLISTED (negative sentiment)", sym)
            else:
                log.debug("Curation: %s ok (sentiment=%+d)", sym, trend)
        except Exception as exc:
            log.debug("Curation error for %s: %s", sym, exc)
    log.info("Curation done — blacklisted: %s", list(_curated_blacklist) or "none")


def _check_higher_tf(symbol: str, current_signal: str, market_trend: int) -> tuple[bool, str]:
    """Return (ok, reason). Blocks counter-trend entries vs the higher timeframe."""
    if not config.MULTI_TIMEFRAME_ENABLED:
        return True, "multi-tf disabled"
    higher_tf = _HIGHER_TF.get(config.BAR_TIMEFRAME)
    if not higher_tf or higher_tf == config.BAR_TIMEFRAME:
        return True, "single timeframe mode"
    try:
        bars = broker.get_bars(symbol, timeframe=higher_tf, lookback_days=90)
        if not bars or len(bars) < 30:
            return True, f"insufficient {higher_tf} data"
        htf_sig = strategy.compute_signals(bars, market_trend=market_trend, timeframe=higher_tf)
        htf = htf_sig["signal"]
        if current_signal == "buy" and htf == "sell":
            return False, f"counter-trend: {higher_tf} is SELL (score {htf_sig['score']})"
        if current_signal == "sell" and htf == "buy":
            return False, f"counter-trend: {higher_tf} is BUY (score {htf_sig['score']})"
        return True, f"{higher_tf} confluence: {htf.upper()}"
    except Exception as exc:
        log.warning("Higher-TF check failed for %s — proceeding without filter: %s", symbol, exc)
        return True, "higher-tf check unavailable"


def _check_peers(symbol: str, market_trend: int) -> tuple[bool, str]:
    """Return (ok, reason). Blocks entry when ALL sector peers are in SELL."""
    if not config.PEER_CHECK_ENABLED:
        return True, "peer check disabled"
    peers = _get_peers(symbol)
    if not peers:
        return True, "no peers configured"
    sell_count = 0
    for peer in peers:
        try:
            bars = broker.get_bars(peer, timeframe="1Day", lookback_days=30)
            if bars and len(bars) >= 5:
                sig = strategy.compute_signals(bars, market_trend=market_trend, timeframe="1Day")
                if sig["signal"] == "sell":
                    sell_count += 1
        except Exception:
            pass
    if sell_count >= len(peers):
        return False, f"sector peers ({', '.join(peers)}) all in SELL — possible sector selloff"
    return True, f"peers ok ({sell_count}/{len(peers)} selling)"


def _enrich_signal(symbol: str, sig: dict) -> dict:
    """Add sentiment_trend, peer_consensus, macro_event_day to the signal dict."""
    try:
        sig["sentiment_trend"] = events.sentiment_trend(symbol)
    except Exception:
        sig["sentiment_trend"] = 0
    sig["peer_consensus"] = True   # default; will be set after peer check
    try:
        sig["macro_event_day"] = events.is_high_impact_macro_day()
    except Exception:
        sig["macro_event_day"] = False
    return sig


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
    if "enable_regime_switching" in saved:
        config.ENABLE_REGIME_SWITCHING = bool(saved["enable_regime_switching"])

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
    stop_pct = _position_stops.get(symbol, config.STOP_LOSS_PCT)
    trailing_stop_hit = stop_pct > 0 and current_price <= peak * (1 - stop_pct)
    # pnl_pct still used for take-profit (measured from entry)
    pnl_pct = (current_price - avg_entry) / avg_entry if avg_entry > 0 else 0.0

    # Exit review: if agent is enabled and holds remain, ask agent before closing
    if trailing_stop_hit and config.EXIT_REVIEW_ENABLED and config.USE_AGENT:
        holds = _exit_holds.get(symbol, 0)
        if holds < config.MAX_EXIT_HOLDS:
            try:
                bars = broker.get_bars(symbol, timeframe="1Day", lookback_days=10)
                review_sig = strategy.compute_signals(bars, timeframe=config.BAR_TIMEFRAME) if bars else {}
                review_sig = _enrich_signal(symbol, review_sig)
                review_sig["signal"] = "sell"   # context: we're reviewing an exit
                result = agent.evaluate_signal(symbol, review_sig, use_cache=False)
                if result["approved"]:
                    # Agent says hold the position a bit longer
                    _exit_holds[symbol] = holds + 1
                    log.info(
                        "%s: exit-review HOLD (%d/%d) — %s",
                        symbol, holds + 1, config.MAX_EXIT_HOLDS, result["reason"],
                    )
                    return False   # skip stop this tick
                else:
                    _exit_holds[symbol] = 0
            except Exception as exc:
                log.warning("%s: exit review error — %s", symbol, exc)
        else:
            _exit_holds[symbol] = 0   # max holds exhausted, proceed with stop

    # Partial scale-out: sell half at EXIT_REVIEW_TRIGGER_PCT × TP target
    # e.g. TP=15%, trigger=0.5 → sell 50% at +7.5%, let rest run to full TP
    partial_trigger = config.TAKE_PROFIT_PCT * config.EXIT_REVIEW_TRIGGER_PCT
    if (
        not _partial_done.get(symbol, False)
        and config.TAKE_PROFIT_PCT > 0
        and partial_trigger > 0
        and pnl_pct >= partial_trigger
        and side == "long"
        and not config.SHADOW_MODE
        and not config.DRY_RUN
    ):
        qty = float(position.get("qty", 0))
        partial_qty = max(1.0, round(qty * 0.5, 0))
        if partial_qty < qty:
            log.info(
                "%s: PARTIAL SCALE-OUT %.0f%% of TP hit (pnl=%.1f%%) — selling %s of %s shares",
                symbol, config.EXIT_REVIEW_TRIGGER_PCT * 100, pnl_pct * 100, partial_qty, qty,
            )
            try:
                broker.place_market_order(symbol, partial_qty, "sell")
                _partial_done[symbol] = True
                pnl_dollars = (current_price - avg_entry) * partial_qty
                trade_journal.log_outcome(symbol, avg_entry, current_price, pnl_dollars, "partial_scale_out")
                alerts.order_alert(symbol, "partial_sell", partial_qty, current_price, "")
            except Exception as exc:
                log.warning("%s: partial scale-out failed — %s", symbol, exc)

    if trailing_stop_hit:
        log.warning(
            "%s: TRAILING STOP hit (price=%.2f peak=%.2f trail=%.2f%%) - closing %s",
            symbol, current_price, peak, stop_pct * 100, side,
        )
        _peak_prices.pop(symbol, None)
        _partial_done.pop(symbol, None)
        _position_stops.pop(symbol, None)
        if config.SHADOW_MODE:
            trade = shadow_book.close_position(symbol, float(position["current_price"]), reason="stop_loss")
            if trade:
                log.info("SHADOW close %s via stop loss: pnl=$%.2f", symbol, trade["pnl"])
                trade_journal.log_outcome(symbol, avg_entry, current_price, trade["pnl"], "stop_loss")
            return trade is not None
        if config.DRY_RUN:
            log.info("[DRY RUN] Would close %s at stop loss", symbol)
            return True
        result = broker.close_position(symbol)
        pnl_dollars = (current_price - avg_entry) * float(position.get("qty", 0))
        trade_journal.log_outcome(symbol, avg_entry, current_price, pnl_dollars, "stop_loss")
        alerts.order_alert(symbol, "close", position["qty"], position["current_price"], result.get("order_id", ""))
        return True

    if config.TAKE_PROFIT_PCT > 0 and pnl_pct >= config.TAKE_PROFIT_PCT:
        log.info("%s: TAKE PROFIT hit (%.2f%%) - closing %s", symbol, pnl_pct * 100, side)
        _peak_prices.pop(symbol, None)
        _partial_done.pop(symbol, None)
        _position_stops.pop(symbol, None)
        if config.SHADOW_MODE:
            trade = shadow_book.close_position(symbol, float(position["current_price"]), reason="take_profit")
            if trade:
                log.info("SHADOW close %s via take profit: pnl=$%.2f", symbol, trade["pnl"])
                trade_journal.log_outcome(symbol, avg_entry, current_price, trade["pnl"], "take_profit")
            return trade is not None
        if config.DRY_RUN:
            log.info("[DRY RUN] Would close %s at take profit", symbol)
            return True
        result = broker.close_position(symbol)
        pnl_dollars = (current_price - avg_entry) * float(position.get("qty", 0))
        trade_journal.log_outcome(symbol, avg_entry, current_price, pnl_dollars, "take_profit")
        alerts.order_alert(symbol, "close", position["qty"], position["current_price"], result.get("order_id", ""))
        return True

    return False


def _place_buy(symbol: str, sig: dict, account: dict, positions: list[dict], watchlist: list[str]) -> bool:
    ok, reason = risk.pre_trade_checks(symbol, sig["price"], account, positions, watchlist=watchlist, atr=sig.get("atr"))
    if not ok:
        log.info("%s: pre-trade check failed - %s", symbol, reason)
        return False

    result = agent.evaluate_signal(symbol, sig)
    approved = result["approved"]
    reason   = result["reason"]
    log.info(
        "%s: agent=%s size=x%.1f stop=%s (%s)",
        symbol,
        "APPROVE" if approved else "REJECT",
        result["size_multiplier"],
        f"{result['suggested_stop_pct']*100:.1f}%" if result["suggested_stop_pct"] else "default",
        reason,
    )
    if not approved:
        trade_journal.log_decision(
            symbol, sig["signal"], False, reason,
            score=sig.get("score", 0), sentiment=sig.get("sentiment_trend", 0),
            macro_day=sig.get("macro_event_day", False),
        )
        return False

    # Vol-targeting: pass realized_vol from signal for volatility-adjusted sizing
    qty = risk.compute_qty(
        sig["price"], account,
        atr=sig.get("atr"),
        realized_vol=sig.get("regime_realized_vol"),
        symbol=symbol,
    )
    # Apply agent-suggested size multiplier; crypto keeps fractional precision
    if broker.is_crypto(symbol):
        qty = max(0.000001, round(qty * result["size_multiplier"], 6))
    else:
        qty = max(1.0, round(qty * result["size_multiplier"], 0))

    # Apply agent-suggested dynamic stop for this position
    if result["suggested_stop_pct"] and config.AGENT_DYNAMIC_STOPS:
        _position_stops[symbol] = result["suggested_stop_pct"]
        log.info("%s: dynamic stop set to %.1f%%", symbol, result["suggested_stop_pct"] * 100)

    if config.SHADOW_MODE:
        shadow_book.record_intent(symbol, "buy", qty, sig["price"], sig["reason"], sig["score"])
        shadow_book.open_position(symbol, "long", qty, sig["price"], sig["reason"], sig["score"])
        risk.record_order(symbol)
        log.info("SHADOW BUY recorded: %s qty=%s @ $%.2f", symbol, qty, sig["price"])
        return True

    if config.DRY_RUN:
        log.info("[DRY RUN] Would BUY %s x %s @ $%.2f score=%s", qty, symbol, sig["price"], sig["score"])
        return True

    # Re-fetch account at submission time — agent call may take several seconds,
    # buying power could have changed.
    fresh_account = broker.get_account()
    if not risk.check_buying_power(sig["price"], qty, fresh_account):
        # Attempt reduced qty using fresh buying power
        qty = max(1.0, round(float(fresh_account["buying_power"]) * 0.95 / sig["price"], 0))
        if not risk.check_buying_power(sig["price"], qty, fresh_account):
            log.warning("%s: insufficient buying power at submission — skipping", symbol)
            return False

    if config.ENABLE_ORDER_SLICING and qty > config.ORDER_SLICE_MAX_QTY:
        orders = broker.place_sliced_order(symbol, qty, "buy")
        order = orders[0]
        log.info("BUY sliced into %d orders for %s", len(orders), symbol)
    else:
        order = broker.place_market_order(symbol, qty, "buy")
    risk.record_order(symbol)
    trade_journal.log_decision(
        symbol, sig["signal"], True, reason,
        size_multiplier=result["size_multiplier"],
        score=sig.get("score", 0), sentiment=sig.get("sentiment_trend", 0),
        macro_day=sig.get("macro_event_day", False),
    )
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

    result = agent.evaluate_signal(symbol, sig)
    approved = result["approved"]
    reason   = result["reason"]
    log.info(
        "%s: agent=%s size=x%.1f stop=%s (%s)",
        symbol,
        "APPROVE" if approved else "REJECT",
        result["size_multiplier"],
        f"{result['suggested_stop_pct']*100:.1f}%" if result["suggested_stop_pct"] else "default",
        reason,
    )
    if not approved:
        trade_journal.log_decision(
            symbol, sig["signal"], False, reason,
            score=sig.get("score", 0), sentiment=sig.get("sentiment_trend", 0),
            macro_day=sig.get("macro_event_day", False),
        )
        return False

    qty = risk.compute_qty(sig["price"], account, atr=sig.get("atr"), symbol=symbol)
    if broker.is_crypto(symbol):
        qty = max(0.000001, round(qty * result["size_multiplier"], 6))
    else:
        qty = max(1.0, round(qty * result["size_multiplier"], 0))
    if result["suggested_stop_pct"] and config.AGENT_DYNAMIC_STOPS:
        _position_stops[symbol] = result["suggested_stop_pct"]
        log.info("%s: dynamic stop set to %.1f%%", symbol, result["suggested_stop_pct"] * 100)

    if config.SHADOW_MODE:
        shadow_book.record_intent(symbol, "short", qty, sig["price"], sig["reason"], sig["score"])
        shadow_book.open_position(symbol, "short", qty, sig["price"], sig["reason"], sig["score"])
        risk.record_order(symbol)
        log.info("SHADOW SHORT recorded: %s qty=%s @ $%.2f", symbol, qty, sig["price"])
        return True

    if config.DRY_RUN:
        log.info("[DRY RUN] Would SHORT %s x %s @ $%.2f score=%s", qty, symbol, sig["price"], sig["score"])
        return True

    # Re-fetch account at submission time — agent call may take several seconds.
    fresh_account = broker.get_account()
    if not risk.check_buying_power(sig["price"], qty, fresh_account):
        qty = max(1.0, round(float(fresh_account["buying_power"]) * 0.95 / sig["price"], 0))
        if not risk.check_buying_power(sig["price"], qty, fresh_account):
            log.warning("%s: insufficient buying power at short submission — skipping", symbol)
            return False

    if config.ENABLE_ORDER_SLICING and qty > config.ORDER_SLICE_MAX_QTY:
        orders = broker.place_sliced_order(symbol, qty, "sell")
        order = orders[0]
        log.info("SHORT sliced into %d orders for %s", len(orders), symbol)
    else:
        order = broker.place_market_order(symbol, qty, "sell")
    risk.record_order(symbol)
    trade_journal.log_decision(
        symbol, sig["signal"], True, reason,
        size_multiplier=result["size_multiplier"],
        score=sig.get("score", 0), sentiment=sig.get("sentiment_trend", 0),
        macro_day=sig.get("macro_event_day", False),
    )
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

    _cl_result = agent.evaluate_signal(symbol, sig)
    approved = _cl_result["approved"]
    reason   = _cl_result["reason"]
    log.info("%s: agent=%s (%s)", symbol, "APPROVE" if approved else "REJECT", reason)
    if not approved:
        return False

    if config.SHADOW_MODE:
        trade = shadow_book.close_position(symbol, sig["price"], reason="sell_signal")
        if trade:
            log.info("SHADOW LONG closed %s: pnl=$%.2f", symbol, trade["pnl"])
            trade_journal.log_outcome(symbol, float(pos["avg_entry"]), sig["price"], trade["pnl"], "sell_signal")
            return True
        return False

    if config.DRY_RUN:
        log.info("[DRY RUN] Would CLOSE LONG %s", symbol)
        return True

    _peak_prices.pop(symbol, None)
    _partial_done.pop(symbol, None)
    _position_stops.pop(symbol, None)
    result = broker.close_position(symbol)
    pnl_dollars = (sig["price"] - float(pos["avg_entry"])) * float(pos["qty"])
    trade_journal.log_outcome(symbol, float(pos["avg_entry"]), sig["price"], pnl_dollars, "sell_signal")
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

    _cs_result = agent.evaluate_signal(symbol, sig)
    approved = _cs_result["approved"]
    reason   = _cs_result["reason"]
    log.info("%s: agent=%s (%s)", symbol, "APPROVE" if approved else "REJECT", reason)
    if not approved:
        return False

    if config.SHADOW_MODE:
        trade = shadow_book.close_position(symbol, sig["price"], reason="cover_signal")
        if trade:
            log.info("SHADOW SHORT covered %s: pnl=$%.2f", symbol, trade["pnl"])
            trade_journal.log_outcome(symbol, float(pos["avg_entry"]), sig["price"], trade["pnl"], "cover_signal")
            return True
        return False

    if config.DRY_RUN:
        log.info("[DRY RUN] Would COVER SHORT %s", symbol)
        return True

    _position_stops.pop(symbol, None)
    result = broker.close_position(symbol)
    pnl_dollars = (float(pos["avg_entry"]) - sig["price"]) * float(pos["qty"])
    trade_journal.log_outcome(symbol, float(pos["avg_entry"]), sig["price"], pnl_dollars, "cover_signal")
    alerts.order_alert(symbol, "cover", pos["qty"], pos["current_price"], result.get("order_id", ""))
    log.info("Short covered: %s", result)
    return True


def _maybe_run_events(symbol: str, sig: dict) -> dict:
    """Auto-trigger earnings event analysis when relevant news appears."""
    if not config.USE_AGENT:
        return sig
    try:
        news = events.fetch_news(symbols=[symbol], keywords="earnings EPS guidance", limit=3)
        has_earnings = events.has_earnings_news(news)
        if has_earnings:
            log.info("%s: earnings news detected - running event analysis", symbol)
            event_result = events.get_event_score(
                symbol,
                run_earnings=True,
                run_geo=False,
                run_macro=False,
                news=news,
            )
            sig = strategy.apply_event_score(sig, event_result)
            log.info("%s: post-event score=%s signal=%s", symbol, sig["score"], sig["signal"])
    except Exception as exc:
        log.debug("%s: event check skipped - %s", symbol, exc)
    return sig


def _apply_signal_filters(symbol: str, sig: dict, bars: list[dict], market_trend: int) -> dict:
    """
    Apply entry filters to an active (buy/sell) signal.
    Returns sig with signal possibly downgraded to "hold".
    Mutates sig["peer_consensus"] as a side-effect.
    """
    sig = _enrich_signal(symbol, sig)

    # Time-of-day filter (buys only)
    tod_ok, tod_reason = risk.check_time_of_day()
    if not tod_ok and sig["signal"] == "buy":
        log.info("%s: buy blocked — %s", symbol, tod_reason)
        sig["signal"] = "hold"

    # Gap filter (buys only)
    gap_ok, gap_reason = risk.check_gap(bars)
    if not gap_ok and sig["signal"] == "buy":
        log.info("%s: buy blocked — %s", symbol, gap_reason)
        sig["signal"] = "hold"

    # Multi-timeframe confluence (buy + sell)
    if sig["signal"] in ("buy", "sell"):
        tf_ok, tf_reason = _check_higher_tf(symbol, sig["signal"], market_trend)
        if not tf_ok:
            log.info("%s: blocked — %s", symbol, tf_reason)
            sig["signal"] = "hold"

    # Peer consensus (buys only)
    if sig["signal"] == "buy":
        peer_ok, peer_reason = _check_peers(symbol, market_trend)
        sig["peer_consensus"] = peer_ok
        if not peer_ok:
            log.info("%s: buy blocked — %s", symbol, peer_reason)
            sig["signal"] = "hold"

    return sig


def _execute_signal(symbol: str, sig: dict, account: dict, positions: list[dict], watchlist: list[str]) -> None:
    """Route approved signal to the correct buy/sell/short execution path."""
    if sig["signal"] == "buy":
        changed = _close_short(symbol, sig, positions)
        if changed:
            account   = broker.get_account()
            positions = _current_positions()
        _place_buy(symbol, sig, account, positions, watchlist)

    elif sig["signal"] == "sell":
        changed = _close_long(symbol, sig, positions, watchlist)
        if changed:
            account   = broker.get_account()
            positions = _current_positions()
        _place_short(symbol, sig, account, positions, watchlist)


def _process_symbol(symbol: str, watchlist: list[str], market_trend: int = 0) -> None:
    account   = broker.get_account()
    positions = _current_positions()
    pos = next((p for p in positions if p["symbol"] == symbol), None)
    if pos and _check_sl_tp(pos):
        return
    curated_blacklisted = symbol in _curated_blacklist

    bars = broker.get_bars(symbol, timeframe=config.BAR_TIMEFRAME)
    earnings_soon = events.is_earnings_period(symbol) if config.USE_AGENT else False
    if earnings_soon:
        log.info("%s: earnings period detected - buy suppressed", symbol)

    is_crypto = broker.is_crypto(symbol)
    effective_trend = 0 if is_crypto else market_trend
    effective_threshold = (
        max(2, config.SIGNAL_THRESHOLD - 2) if is_crypto else config.SIGNAL_THRESHOLD
    )
    sig = strategy.compute_signals(
        bars,
        market_trend=effective_trend,
        earnings_soon=earnings_soon,
        timeframe=config.BAR_TIMEFRAME,
        threshold=effective_threshold,
    )
    sig = _maybe_run_events(symbol, sig)

    if curated_blacklisted and sig["signal"] == "buy":
        log.info("%s: buy suppressed (curated blacklist — negative news today)", symbol)
        sig["signal"] = "hold"
        sig["reason"] = f"{sig['reason']}; [buy suppressed: curated blacklist]" if sig["reason"] else "[buy suppressed: curated blacklist]"

    if sig["signal"] in ("buy", "sell"):
        sig = _apply_signal_filters(symbol, sig, bars, market_trend)

    if config.SHADOW_MODE and sig.get("price"):
        shadow_book.update_mark(symbol, sig["price"])

    log.info(
        "%s: regime=%s mkt=%s adx=%.1f sentiment=%+d signal=%s score=%s reason=%s",
        symbol,
        sig.get("regime", "n/a"),
        "bull" if market_trend == 1 else ("bear" if market_trend == -1 else "?"),
        sig.get("adx") or 0.0,
        sig.get("sentiment_trend", 0),
        sig["signal"],
        sig["score"],
        sig["reason"],
    )

    _execute_signal(symbol, sig, account, positions, watchlist)


def get_active_watchlist() -> list[str]:
    """
    Return the live trading watchlist.
    When WATCHLIST_SOURCE != "static", symbols are fetched dynamically each tick
    (most_active, gainers, trending, sector, etf) and merged with any manually
    stored symbols so user-pinned tickers are always included.
    """
    stored = watchlist_store.load()
    source = config.WATCHLIST_SOURCE
    if source == "static":
        return list(dict.fromkeys(config.WATCHLIST + stored))
    try:
        dynamic = screener.build_watchlist(
            source,
            top_n=config.WATCHLIST_TOP_N,
            sectors=config.WATCHLIST_SECTORS or None,
        )
    except Exception as exc:
        log.warning("Dynamic watchlist fetch failed (%s), falling back to static: %s", source, exc)
        dynamic = config.WATCHLIST
    return list(dict.fromkeys(dynamic + stored))


def _maybe_rebalance(account: dict, positions: list[dict]) -> None:
    """
    Equal-weight rebalance: trim any position whose portfolio weight exceeds
    the equal-weight target by more than REBALANCE_DRIFT_THRESHOLD.
    Runs at most once per REBALANCE_INTERVAL_DAYS.
    Only fires in live/shadow mode (skipped in DRY_RUN).
    """
    global _last_rebalance_date
    if config.REBALANCE_INTERVAL_DAYS <= 0:
        return

    today = datetime.now(timezone.utc).date()
    if _last_rebalance_date is not None:
        days_since = (today - _last_rebalance_date).days
        if days_since < config.REBALANCE_INTERVAL_DAYS:
            return

    if not positions:
        return

    portfolio_value = float(account["portfolio_value"])
    if portfolio_value <= 0:
        return

    n = len(positions)
    equal_weight = 1.0 / n
    trimmed: list[str] = []

    for pos in positions:
        symbol = pos["symbol"]
        notional = float(pos.get("market_value", 0))
        weight = notional / portfolio_value
        drift = weight - equal_weight
        if drift > config.REBALANCE_DRIFT_THRESHOLD:
            # Trim excess — sell the over-weight fraction
            excess_notional = drift * portfolio_value
            price = float(pos.get("current_price", 0))
            if price <= 0:
                continue
            trim_qty = max(1.0, round(excess_notional / price, 0))
            current_qty = float(pos.get("qty", 0))
            trim_qty = min(trim_qty, current_qty - 1)  # keep at least 1 share
            if trim_qty < 1:
                continue
            log.info(
                "REBALANCE trim %s: weight=%.1f%% target=%.1f%% drift=%.1f%% → sell %.0f shares",
                symbol, weight * 100, equal_weight * 100, drift * 100, trim_qty,
            )
            if config.DRY_RUN:
                log.info("[DRY RUN] Would trim %s x%.0f", symbol, trim_qty)
            elif config.SHADOW_MODE:
                log.info("[SHADOW] Rebalance trim %s x%.0f", symbol, trim_qty)
            else:
                try:
                    order = broker.place_market_order(symbol, trim_qty, "sell")
                    risk.record_order(symbol)
                    log.info("Rebalance sell order: %s", order)
                    trimmed.append(symbol)
                except Exception as exc:
                    log.error("Rebalance sell failed for %s: %s", symbol, exc)

    _last_rebalance_date = today
    if trimmed:
        alerts.send(
            "Portfolio Rebalanced",
            f"Trimmed over-weight positions: {', '.join(trimmed)}",
        )
    else:
        log.info("Rebalance check: no positions exceeded drift threshold (%.0f%%)", config.REBALANCE_DRIFT_THRESHOLD * 100)


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

    _maybe_rebalance(account, positions)

    watchlist = get_active_watchlist()
    watchlist = _rank_by_relative_strength(watchlist)  # trade only top RS symbols
    if config.SHADOW_MODE:
        log.info("[SHADOW MODE] Hypothetical orders only. Outcomes recorded to shadow_book.json")
    elif config.DRY_RUN:
        log.info("[DRY RUN] No orders will be placed.")

    # Daily curation — keyword-scan for bad-news tickers at day start
    _curate_watchlist(watchlist)

    # Macro suppression — reduce entries on high-impact economic event days
    macro_day = events.is_high_impact_macro_day()
    if macro_day:
        log.warning("HIGH IMPACT MACRO DAY detected — only high-conviction signals will trade")

    # Fetch SPY market trend once per tick — shared across all symbols
    market_trend = _get_market_trend()
    log.info("Market trend (SPY vs EMA200): %s", "BULL" if market_trend == 1 else ("BEAR" if market_trend == -1 else "UNKNOWN"))

    # ── Dynamic market phase detection ─────────────────────────────────────────
    # Classify regime → adjust SIGNAL_THRESHOLD + ALLOW_SHORT live each tick.
    _phase_override = settings_store.get("market_phase_override", "auto")
    if _phase_override in ("bull", "bear", "volatile", "sideways"):
        _market_phase = _phase_override
        log.info("Market phase OVERRIDDEN via settings: %s", _market_phase.upper())
    else:
        _market_phase = "bull"
        try:
            _spy_bars = broker.get_bars("SPY", timeframe="1Day", lookback_days=30)
            if _spy_bars and len(_spy_bars) >= 10:
                _spy_closes = [float(b["c"]) for b in _spy_bars]
                _market_phase = strategy.detect_market_phase(_spy_closes, lookback=20)
        except Exception as _exc:
            log.warning("Market phase detection failed: %s", _exc)

    _phase_label = _market_phase.upper()
    log.info("Market phase: %s", _phase_label)

    # Phase-specific overrides (stored as originals, restored after tick)
    _orig_threshold  = config.SIGNAL_THRESHOLD
    _orig_allow_short = config.ALLOW_SHORT
    _orig_sl_atr_mult = config.SL_ATR_MULT
    _orig_max_pos     = config.MAX_POSITION_PCT

    if _market_phase == "bear":
        # Bear: raise bar, cut size, allow daily shorts, tighter SL
        config.SIGNAL_THRESHOLD  = _orig_threshold + 1
        config.ALLOW_SHORT       = True
        config.SL_ATR_MULT       = max(1.0, _orig_sl_atr_mult * 0.75)
        config.MAX_POSITION_PCT  = _orig_max_pos * 0.6
        log.warning("BEAR phase: threshold+1, size×0.6, SL×0.75, shorts enabled")
    elif _market_phase == "volatile":
        # Volatile: widen SL to absorb noise, cut size, raise bar, no shorts
        config.SIGNAL_THRESHOLD  = _orig_threshold + 1
        config.ALLOW_SHORT       = False
        config.SL_ATR_MULT       = _orig_sl_atr_mult * 1.5
        config.MAX_POSITION_PCT  = _orig_max_pos * 0.5
        log.warning("VOLATILE phase: threshold+1, size×0.5, SL×1.5, no shorts")
    elif _market_phase == "sideways":
        # Sideways: normal params, slightly smaller size
        config.MAX_POSITION_PCT  = _orig_max_pos * 0.8
        log.info("SIDEWAYS phase: size×0.8, standard threshold")
    else:
        # Bull: full params as configured
        log.info("BULL phase: full params active")

    if macro_day:
        config.SIGNAL_THRESHOLD = max(config.SIGNAL_THRESHOLD, _orig_threshold + 1)
    # ───────────────────────────────────────────────────────────────────────────

    try:
        for symbol in watchlist:
            try:
                _process_symbol(symbol, watchlist, market_trend=market_trend)
            except Exception as exc:
                log.error("%s: error during tick - %s", symbol, exc, exc_info=True)
    finally:
        config.SIGNAL_THRESHOLD  = _orig_threshold
        config.ALLOW_SHORT       = _orig_allow_short
        config.SL_ATR_MULT       = _orig_sl_atr_mult
        config.MAX_POSITION_PCT  = _orig_max_pos

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
