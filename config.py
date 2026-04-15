import os
from dotenv import load_dotenv

load_dotenv()

# Alpaca paper trading (get free keys at alpaca.markets)
ALPACA_API_KEY = os.getenv("ALPACA_API_KEY", "your_alpaca_key")
ALPACA_SECRET_KEY = os.getenv("ALPACA_SECRET_KEY", "your_alpaca_secret")
PAPER_TRADING = os.getenv("PAPER_TRADING", "true").lower() == "true"

# Anthropic
ANTHROPIC_API_KEY = os.getenv("ANTHROPIC_API_KEY", "your_anthropic_key")

# OpenAI
OPENAI_API_KEY = os.getenv("OPENAI_API_KEY", "your_openai_key")

# Agent config: "claude" | "openai" | "none"
AGENT_PROVIDER = os.getenv("AGENT_PROVIDER", "none")  # which LLM to use
USE_AGENT = os.getenv("USE_AGENT", "true").lower() == "true" and AGENT_PROVIDER != "none"

# Trading params
WATCHLIST = ["AAPL", "MSFT", "NVDA", "TSLA"]
MAX_POSITION_PCT = 0.10   # max 10% of portfolio per position
MAX_DRAWDOWN_PCT = 0.05   # halt if portfolio drops 5% from peak
LOOP_INTERVAL_SEC = 300   # run every 5 minutes
SIGNAL_THRESHOLD = int(os.getenv("SIGNAL_THRESHOLD", "2"))  # min score to trigger BUY/SELL
# Bar timeframe: "1Min" | "5Min" | "15Min" | "1Hour" | "1Day"
BAR_TIMEFRAME = os.getenv("BAR_TIMEFRAME", "1Min")
