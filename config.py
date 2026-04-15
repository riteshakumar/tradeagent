import os
from dotenv import load_dotenv

load_dotenv()

# Alpaca paper trading (get free keys at alpaca.markets)
ALPACA_API_KEY = os.getenv("ALPACA_API_KEY", "your_alpaca_key")
ALPACA_SECRET_KEY = os.getenv("ALPACA_SECRET_KEY", "your_alpaca_secret")
PAPER_TRADING = os.getenv("PAPER_TRADING", "true").lower() == "true"

# Anthropic
ANTHROPIC_API_KEY = os.getenv("ANTHROPIC_API_KEY", "your_anthropic_key")

# Trading params
WATCHLIST = ["AAPL", "MSFT", "NVDA", "TSLA"]
MAX_POSITION_PCT = 0.10   # max 10% of portfolio per position
MAX_DRAWDOWN_PCT = 0.05   # halt if portfolio drops 5% from peak
LOOP_INTERVAL_SEC = 300   # run every 5 minutes
