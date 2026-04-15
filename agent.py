"""
Router — pick the right agent based on AGENT_PROVIDER config.
All callers import this module only.
"""
import config


def evaluate_signal(symbol: str, signal: dict) -> tuple[bool, str]:
    if not config.USE_AGENT:
        approved = signal["score"] >= 3
        return approved, f"agent disabled — auto-{'approved' if approved else 'rejected'} based on score"

    if config.AGENT_PROVIDER == "openai":
        import agent_openai
        return agent_openai.evaluate_signal(symbol, signal)

    import agent_claude
    return agent_claude.evaluate_signal(symbol, signal)
