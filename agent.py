"""
Agent router — picks OpenAI or Claude based on AGENT_PROVIDER config.
Returns a result dict: {approved, reason, size_multiplier, suggested_stop_pct}
"""
import logging
import config
import agent_cache

log = logging.getLogger(__name__)

_DEFAULT_RESULT = {
    "approved": False,
    "reason": "",
    "size_multiplier": 1.0,
    "suggested_stop_pct": None,
}


def evaluate_signal(symbol: str, signal: dict, use_cache: bool = True) -> dict:
    """
    Evaluate a trade signal.  Returns:
      {approved: bool, reason: str, size_multiplier: float, suggested_stop_pct: float|None}
    """
    if not config.USE_AGENT:
        approved = signal["score"] >= config.SIGNAL_THRESHOLD
        return {
            **_DEFAULT_RESULT,
            "approved": approved,
            "reason": f"agent disabled — auto-{'approved' if approved else 'rejected'} (score {signal['score']})",
            "size_multiplier": 1.0,
        }

    if use_cache:
        cached = agent_cache.get(symbol, signal)
        if cached is not None:
            log.info("%s: agent result from cache", symbol)
            return cached

    if config.AGENT_PROVIDER == "openai":
        import agent_openai
        result = agent_openai.evaluate_signal(symbol, signal)
    else:
        import agent_claude
        result = agent_claude.evaluate_signal(symbol, signal)

    # Clamp size_multiplier to configured bounds
    sm = float(result.get("size_multiplier", 1.0))
    sm = max(config.MIN_SIZE_MULTIPLIER, min(config.MAX_SIZE_MULTIPLIER, sm))
    result["size_multiplier"] = sm if config.AGENT_SIZE_MULTIPLIER else 1.0

    # Clamp suggested_stop_pct
    sp = result.get("suggested_stop_pct")
    if sp is not None and config.AGENT_DYNAMIC_STOPS:
        sp = max(0.02, min(0.20, float(sp)))
        result["suggested_stop_pct"] = sp
    else:
        result["suggested_stop_pct"] = None

    agent_cache.set(symbol, signal, result)
    return result
