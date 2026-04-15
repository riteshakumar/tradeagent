"""
Claude agent layer — receives quant signals and makes final buy/sell/hold decisions.
Claude can call tools to inspect the portfolio before deciding.
"""
import json
import anthropic
import broker
import config

client = anthropic.Anthropic(api_key=config.ANTHROPIC_API_KEY)

TOOLS = [
    {
        "name": "get_account",
        "description": "Get current account equity, cash, and buying power.",
        "input_schema": {"type": "object", "properties": {}, "required": []},
    },
    {
        "name": "get_positions",
        "description": "List all open positions with P&L.",
        "input_schema": {"type": "object", "properties": {}, "required": []},
    },
    {
        "name": "approve_trade",
        "description": "Approve or reject the proposed trade signal.",
        "input_schema": {
            "type": "object",
            "properties": {
                "decision": {"type": "string", "enum": ["approve", "reject"]},
                "reason": {"type": "string"},
            },
            "required": ["decision", "reason"],
        },
    },
]


def _run_tool(name: str, inputs: dict) -> str:
    if name == "get_account":
        return json.dumps(broker.get_account())
    if name == "get_positions":
        return json.dumps(broker.get_positions())
    if name == "approve_trade":
        return json.dumps(inputs)  # pass-through; handled by caller
    return json.dumps({"error": "unknown tool"})


def evaluate_signal(symbol: str, signal: dict) -> tuple[bool, str]:
    """
    Ask Claude to approve or reject a quant signal.
    Returns (approved: bool, reason: str).
    """
    system = (
        "You are a risk-aware trading agent. "
        "You receive quantitative signals and decide whether to approve or reject trades. "
        "Reject if: the signal is weak, the portfolio is too concentrated, or buying power is low. "
        "Use your tools to check account state before deciding. "
        "Always call approve_trade as your final action."
    )

    user = (
        f"Quant signal for {symbol}:\n"
        f"  action : {signal['signal']}\n"
        f"  score  : {signal['score']}\n"
        f"  RSI    : {signal.get('rsi')}\n"
        f"  price  : ${signal.get('price')}\n"
        f"  reason : {signal['reason']}\n\n"
        "Should we execute this trade? Check the portfolio then call approve_trade."
    )

    messages = [{"role": "user", "content": user}]

    # Agentic loop — run until Claude calls approve_trade
    for _ in range(6):  # safety cap on iterations
        response = client.messages.create(
            model="claude-sonnet-4-6",
            max_tokens=512,
            system=system,
            tools=TOOLS,
            messages=messages,
        )

        messages.append({"role": "assistant", "content": response.content})

        if response.stop_reason == "end_turn":
            return False, "agent did not call approve_trade"

        tool_results = []
        final_decision = None

        for block in response.content:
            if block.type != "tool_use":
                continue
            result = _run_tool(block.name, block.input)
            tool_results.append({
                "type": "tool_result",
                "tool_use_id": block.id,
                "content": result,
            })
            if block.name == "approve_trade":
                final_decision = block.input

        messages.append({"role": "user", "content": tool_results})

        if final_decision is not None:
            approved = final_decision["decision"] == "approve"
            return approved, final_decision["reason"]

    return False, "agent loop exhausted without decision"
