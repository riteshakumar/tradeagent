"""
Router — pick the right agent based on AGENT_PROVIDER config.
Caches LLM results per (symbol, signal, score) to avoid redundant API calls.
"""
import logging
import config
import agent_cache

log = logging.getLogger(__name__)


def evaluate_signal(symbol: str, signal: dict, use_cache: bool = True) -> tuple[bool, str]:
    if not config.USE_AGENT:
        approved = signal["score"] >= config.SIGNAL_THRESHOLD
        return approved, f"agent disabled — auto-{'approved' if approved else 'rejected'} based on score"

    # Check cache first
    if use_cache:
        cached = agent_cache.get(symbol, signal)
        if cached is not None:
            log.info(f"{symbol}: agent result from cache")
            return cached

    if config.AGENT_PROVIDER == "openai":
        import agent_openai
        approved, reason = agent_openai.evaluate_signal(symbol, signal)
    else:
        import agent_claude
        approved, reason = agent_claude.evaluate_signal(symbol, signal)

    agent_cache.set(symbol, signal, approved, reason)
    return approved, reason
