"""
OpenAI agent layer — mirrors agent.py but uses OpenAI function calling.
"""
import json
import openai
import broker
import config

client = openai.OpenAI(api_key=config.OPENAI_API_KEY)

TOOLS = [
    {
        "type": "function",
        "function": {
            "name": "get_account",
            "description": "Get current account equity, cash, and buying power.",
            "parameters": {"type": "object", "properties": {}, "required": []},
        },
    },
    {
        "type": "function",
        "function": {
            "name": "get_positions",
            "description": "List all open positions with P&L.",
            "parameters": {"type": "object", "properties": {}, "required": []},
        },
    },
    {
        "type": "function",
        "function": {
            "name": "approve_trade",
            "description": "Approve or reject the proposed trade signal.",
            "parameters": {
                "type": "object",
                "properties": {
                    "decision": {"type": "string", "enum": ["approve", "reject"]},
                    "reason": {"type": "string"},
                },
                "required": ["decision", "reason"],
            },
        },
    },
]


def _run_tool(name: str, arguments: str) -> str:
    inputs = json.loads(arguments)
    if name == "get_account":
        return json.dumps(broker.get_account())
    if name == "get_positions":
        return json.dumps(broker.get_positions())
    if name == "approve_trade":
        return json.dumps(inputs)
    return json.dumps({"error": "unknown tool"})


def evaluate_signal(symbol: str, signal: dict) -> tuple[bool, str]:
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

    messages = [
        {"role": "system", "content": system},
        {"role": "user", "content": user},
    ]

    for _ in range(6):
        response = client.chat.completions.create(
            model="gpt-4o",
            tools=TOOLS,
            messages=messages,
        )

        msg = response.choices[0].message
        messages.append(msg)

        if not msg.tool_calls:
            return False, "agent did not call approve_trade"

        final_decision = None
        tool_results = []

        for tc in msg.tool_calls:
            result = _run_tool(tc.function.name, tc.function.arguments)
            tool_results.append({
                "role": "tool",
                "tool_call_id": tc.id,
                "content": result,
            })
            if tc.function.name == "approve_trade":
                final_decision = json.loads(tc.function.arguments)

        messages.extend(tool_results)

        if final_decision is not None:
            approved = final_decision["decision"] == "approve"
            return approved, final_decision["reason"]

    return False, "agent loop exhausted without decision"
