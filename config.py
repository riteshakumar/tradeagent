import json
import os

from dotenv import load_dotenv

load_dotenv()


def _env_bool(name: str, default: bool) -> bool:
    raw = os.getenv(name)
    if raw is None:
        return default
    return raw.strip().lower() in {"1", "true", "yes", "on"}


def _env_float(name: str, default: float, minimum: float | None = None, maximum: float | None = None) -> float:
    raw = os.getenv(name)
    try:
        value = float(raw) if raw is not None else float(default)
    except ValueError:
        value = float(default)
    if minimum is not None:
        value = max(minimum, value)
    if maximum is not None:
        value = min(maximum, value)
    return value


def _env_int(name: str, default: int, minimum: int | None = None, maximum: int | None = None) -> int:
    raw = os.getenv(name)
    try:
        value = int(raw) if raw is not None else int(default)
    except ValueError:
        value = int(default)
    if minimum is not None:
        value = max(minimum, value)
    if maximum is not None:
        value = min(maximum, value)
    return value


def _env_list(name: str, default: list[str]) -> list[str]:
    raw = os.getenv(name, "")
    values = [s.strip().upper() for s in raw.split(",") if s.strip()]
    return values or default


def _load_symbol_sector_map() -> dict[str, str]:
    raw = os.getenv("SYMBOL_SECTORS", "")
    if not raw.strip():
        return {}
    try:
        payload = json.loads(raw)
        if not isinstance(payload, dict):
            return {}
        return {str(k).upper(): str(v).lower() for k, v in payload.items() if str(k).strip() and str(v).strip()}
    except json.JSONDecodeError:
        return {}


def _looks_like_placeholder(value: str) -> bool:
    if not value:
        return True
    lower = value.strip().lower()
    return lower.startswith("your_") or lower.endswith("_here")


# Alpaca (required for account/data access)
ALPACA_API_KEY = os.getenv("ALPACA_API_KEY", "").strip()
ALPACA_SECRET_KEY = os.getenv("ALPACA_SECRET_KEY", "").strip()
PAPER_TRADING = _env_bool("PAPER_TRADING", True)
CONFIRM_LIVE_TRADING = _env_bool("CONFIRM_LIVE_TRADING", False)

# LLM keys + model controls
ANTHROPIC_API_KEY = os.getenv("ANTHROPIC_API_KEY", "").strip()
OPENAI_API_KEY = os.getenv("OPENAI_API_KEY", "").strip()
OPENAI_MODEL = os.getenv("OPENAI_MODEL", "gpt-4o").strip() or "gpt-4o"
ANTHROPIC_MODEL = os.getenv("ANTHROPIC_MODEL", "claude-sonnet-4-6").strip() or "claude-sonnet-4-6"

# Agent config: "claude" | "openai" | "none"
AGENT_PROVIDER = os.getenv("AGENT_PROVIDER", "none").strip().lower() or "none"
if AGENT_PROVIDER not in {"claude", "openai", "none"}:
    AGENT_PROVIDER = "none"
USE_AGENT = _env_bool("USE_AGENT", True) and AGENT_PROVIDER != "none"

# Alerts
ALERT_EMAIL_TO = os.getenv("ALERT_EMAIL_TO", "").strip()
ALERT_SMTP_HOST = os.getenv("ALERT_SMTP_HOST", "smtp.gmail.com").strip() or "smtp.gmail.com"
ALERT_SMTP_PORT = _env_int("ALERT_SMTP_PORT", 465, minimum=1, maximum=65535)
ALERT_SMTP_USER = os.getenv("ALERT_SMTP_USER", "").strip()
ALERT_SMTP_PASS = os.getenv("ALERT_SMTP_PASS", "").strip()
ALERT_SLACK_WEBHOOK = os.getenv("ALERT_SLACK_WEBHOOK", "").strip()
ALERT_TELEGRAM_TOKEN = os.getenv("ALERT_TELEGRAM_TOKEN", "").strip()
ALERT_TELEGRAM_CHAT_ID = os.getenv("ALERT_TELEGRAM_CHAT_ID", "").strip()

# Stop loss / Take profit (0 = disabled)
STOP_LOSS_PCT = _env_float("STOP_LOSS_PCT", 0.05, minimum=0.0, maximum=0.99)
TAKE_PROFIT_PCT = _env_float("TAKE_PROFIT_PCT", 0.10, minimum=0.0, maximum=10.0)

# Trading params
WATCHLIST = _env_list("WATCHLIST", ["AAPL", "MSFT", "NVDA", "TSLA"])
MAX_POSITION_PCT = _env_float("MAX_POSITION_PCT", 0.10, minimum=0.0, maximum=1.0)
RISK_PER_TRADE_PCT = _env_float("RISK_PER_TRADE_PCT", 0.01, minimum=0.0, maximum=1.0)
MAX_DRAWDOWN_PCT = _env_float("MAX_DRAWDOWN_PCT", 0.10, minimum=0.0, maximum=1.0)
LOOP_INTERVAL_SEC = _env_int("LOOP_INTERVAL_SEC", 300, minimum=5)
SIGNAL_THRESHOLD = _env_int("SIGNAL_THRESHOLD", 3, minimum=1, maximum=10)

# Bar timeframe: "1Min" | "5Min" | "15Min" | "1Hour" | "1Day"
BAR_TIMEFRAME = os.getenv("BAR_TIMEFRAME", "5Min").strip() or "5Min"

# Screener / order filters
MIN_STOCK_PRICE = _env_float("MIN_STOCK_PRICE", 5.0, minimum=0.0)
MIN_STOCK_VOLUME = _env_int("MIN_STOCK_VOLUME", 500_000, minimum=0)
ORDER_COOLDOWN_SEC = _env_int("ORDER_COOLDOWN_SEC", 300, minimum=0)

# Order execution toggles
DRY_RUN = _env_bool("DRY_RUN", False)
SHADOW_MODE = _env_bool("SHADOW_MODE", False)

# Agent LLM cache TTL
AGENT_CACHE_TTL_SEC = _env_int("AGENT_CACHE_TTL_SEC", 300, minimum=0)

# Short selling
ALLOW_SHORT = _env_bool("ALLOW_SHORT", False)

# Portfolio risk caps
MAX_SECTOR_EXPOSURE_PCT = _env_float("MAX_SECTOR_EXPOSURE_PCT", 0.35, minimum=0.0, maximum=1.0)
ENABLE_CORRELATION_CAP = _env_bool("ENABLE_CORRELATION_CAP", True)
MAX_CORRELATION = _env_float("MAX_CORRELATION", 0.85, minimum=0.0, maximum=1.0)
MAX_CORRELATED_POSITIONS = _env_int("MAX_CORRELATED_POSITIONS", 2, minimum=1, maximum=50)
CORRELATION_LOOKBACK_DAYS = _env_int("CORRELATION_LOOKBACK_DAYS", 90, minimum=20, maximum=365)
DAILY_LOSS_STOP_PCT = _env_float("DAILY_LOSS_STOP_PCT", 0.03, minimum=0.0, maximum=1.0)
SYMBOL_SECTORS = _load_symbol_sector_map()

# Regime weighting
ENABLE_REGIME_SWITCHING = _env_bool("ENABLE_REGIME_SWITCHING", True)
HIGH_VOL_THRESHOLD = _env_float("HIGH_VOL_THRESHOLD", 0.025, minimum=0.001, maximum=1.0)
TREND_STRENGTH_THRESHOLD = _env_float("TREND_STRENGTH_THRESHOLD", 0.012, minimum=0.001, maximum=1.0)

# Backtest realism knobs
BACKTEST_SLIPPAGE_BPS = _env_float("BACKTEST_SLIPPAGE_BPS", 2.0, minimum=0.0, maximum=500.0)
BACKTEST_FEE_PER_TRADE = _env_float("BACKTEST_FEE_PER_TRADE", 0.0, minimum=0.0, maximum=10_000.0)


def is_order_execution_enabled() -> bool:
    return not (DRY_RUN or SHADOW_MODE)


def validate_runtime() -> None:
    if _looks_like_placeholder(ALPACA_API_KEY) or _looks_like_placeholder(ALPACA_SECRET_KEY):
        raise RuntimeError("Missing valid Alpaca credentials. Set ALPACA_API_KEY and ALPACA_SECRET_KEY in .env.")

    if USE_AGENT and AGENT_PROVIDER == "openai" and _looks_like_placeholder(OPENAI_API_KEY):
        raise RuntimeError("AGENT_PROVIDER=openai requires a valid OPENAI_API_KEY.")

    if USE_AGENT and AGENT_PROVIDER == "claude" and _looks_like_placeholder(ANTHROPIC_API_KEY):
        raise RuntimeError("AGENT_PROVIDER=claude requires a valid ANTHROPIC_API_KEY.")

    if not PAPER_TRADING and is_order_execution_enabled() and not CONFIRM_LIVE_TRADING:
        raise RuntimeError(
            "Live trading is enabled. Set CONFIRM_LIVE_TRADING=true to confirm intentional live order execution."
        )
