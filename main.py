"""
Main trading loop.
Run: python main.py
"""
import time
import logging
from datetime import datetime

import broker
import strategy
import risk
import agent
import config

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    handlers=[logging.StreamHandler(), logging.FileHandler("trade.log")],
)
log = logging.getLogger(__name__)


def is_market_open() -> bool:
    from alpaca.trading.client import TradingClient
    client = TradingClient(config.ALPACA_API_KEY, config.ALPACA_SECRET_KEY, paper=True)
    clock = client.get_clock()
    return clock.is_open


def run_once():
    log.info("=== Tick start ===")

    if not is_market_open():
        log.info("Market closed — skipping tick.")
        return

    account = broker.get_account()
    log.info(f"Account: equity=${account['equity']:,.2f}  cash=${account['cash']:,.2f}")

    # Kill switch: halt if drawdown breached
    if risk.check_drawdown(account):
        log.warning("MAX DRAWDOWN BREACHED — halting all trading this session.")
        return

    positions = broker.get_positions()
    log.info(f"Open positions: {[p['symbol'] for p in positions]}")

    for symbol in config.WATCHLIST:
        try:
            bars = broker.get_bars(symbol, days=60)
            sig = strategy.compute_signals(bars)
            log.info(f"{symbol}: signal={sig['signal']}  score={sig['score']}  reason={sig['reason']}")

            # --- BUY logic ---
            if sig["signal"] == "buy" and not risk.already_positioned(symbol, positions):
                approved, reason = agent.evaluate_signal(symbol, sig)
                log.info(f"{symbol}: agent={'APPROVE' if approved else 'REJECT'}  ({reason})")
                if approved:
                    qty = risk.compute_qty(symbol, sig["price"], account)
                    order = broker.place_market_order(symbol, qty, "buy")
                    log.info(f"BUY order placed: {order}")

            # --- SELL logic ---
            elif sig["signal"] == "sell" and risk.already_positioned(symbol, positions):
                approved, reason = agent.evaluate_signal(symbol, sig)
                log.info(f"{symbol}: agent={'APPROVE' if approved else 'REJECT'}  ({reason})")
                if approved:
                    result = broker.close_position(symbol)
                    log.info(f"Position closed: {result}")

        except Exception as e:
            log.error(f"{symbol}: error during tick — {e}", exc_info=True)

    log.info("=== Tick end ===\n")


def main():
    log.info("TradeAgent starting up.")
    log.info(f"Watchlist: {config.WATCHLIST}")
    log.info(f"Loop interval: {config.LOOP_INTERVAL_SEC}s")

    while True:
        try:
            run_once()
        except Exception as e:
            log.error(f"Unhandled error in main loop: {e}", exc_info=True)
        time.sleep(config.LOOP_INTERVAL_SEC)


if __name__ == "__main__":
    main()
