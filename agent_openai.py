"""
OpenAI agent — evaluates trade signals with full quant context + live news.

The agent receives:
  • Complete quant signal breakdown (all indicators, regime, ADX, VWAP, etc.)
  • Live news headlines fetched from Alpaca news API
  • Market trend context (SPY)
  • Account / portfolio state via tool calls

Decision logic:
  Approve  — quant score ≥ threshold AND news doesn't reveal a contradicting catalyst
  Reject   — genuine negative news catalyst OR account/buying-power issue
"""
import html
import json
import logging

import openai

import broker
import config

log = logging.getLogger(__name__)
client = openai.OpenAI(api_key=config.OPENAI_API_KEY)

TOOLS = [
    {
        "type": "function",
        "function": {
            "name": "get_account",
            "description": "Return current account equity, cash, buying power, and portfolio value.",
            "parameters": {"type": "object", "properties": {}, "required": []},
        },
    },
    {
        "type": "function",
        "function": {
            "name": "get_positions",
            "description": "Return all open positions with entry price, qty, unrealised P&L.",
            "parameters": {"type": "object", "properties": {}, "required": []},
        },
    },
    {
        "type": "function",
        "function": {
            "name": "get_news",
            "description": "Fetch the latest news headlines for a ticker symbol.",
            "parameters": {
                "type": "object",
                "properties": {
                    "symbol": {"type": "string", "description": "Ticker symbol, e.g. AAPL"},
                    "limit":  {"type": "integer", "description": "Number of headlines (default 8)"},
                },
                "required": ["symbol"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "approve_trade",
            "description": "Submit final approval or rejection for the proposed trade.",
            "parameters": {
                "type": "object",
                "properties": {
                    "decision":           {"type": "string", "enum": ["approve", "reject"]},
                    "reason":             {"type": "string", "description": "One-sentence explanation."},
                    "size_multiplier":    {"type": "number", "description": "Position size multiplier 0.5–1.5. Use 1.5 when news strongly confirms, 0.5 when marginal, 1.0 default."},
                    "suggested_stop_pct": {"type": "number", "description": "Optional trailing stop % (e.g. 0.06 = 6%). Omit to use system default."},
                },
                "required": ["decision", "reason"],
            },
        },
    },
]


def _run_tool(name: str, arguments: str) -> str:
    try:
        inputs = json.loads(arguments)
    except Exception:
        inputs = {}

    if name == "get_account":
        return json.dumps(broker.get_account())

    if name == "get_positions":
        return json.dumps(broker.get_positions())

    if name == "get_news":
        try:
            import events
            sym = inputs.get("symbol", "")
            limit = int(inputs.get("limit", 8))
            news = events.fetch_news(symbols=[sym], limit=limit)
            headlines = [
                {"time": n.get("created", "")[:16], "headline": html.escape(n["headline"]), "source": n.get("source", "")}
                for n in news if n.get("headline")
            ]
            return json.dumps({"symbol": sym, "headlines": headlines})
        except Exception as exc:
            return json.dumps({"error": str(exc)})

    if name == "approve_trade":
        return json.dumps(inputs)

    return json.dumps({"error": "unknown tool"})


def _build_signal_summary(symbol: str, signal: dict) -> str:
    """Build a rich, structured context block from the full signal dict."""
    regime = str(signal.get("regime", "unknown")).replace("_", " ")
    adx    = signal.get("adx")
    rsi    = signal.get("rsi")
    price  = signal.get("price")
    score  = signal.get("score", 0)
    action = signal.get("signal", "hold").upper()
    reason = signal.get("reason", "")
    atr    = signal.get("atr")
    vol    = signal.get("regime_realized_vol")

    market_trend_val = signal.get("market_trend", 0)
    market_trend = "BULL" if market_trend_val == 1 else ("BEAR" if market_trend_val == -1 else "NEUTRAL")
    earnings_soon = signal.get("earnings_soon", False)

    # Individual component scores if present
    components = []
    for key, label in [
        ("ema_score",        "EMA crossover"),
        ("macd_score",       "MACD"),
        ("rsi_score",        "RSI"),
        ("bb_score",         "Bollinger Bands"),
        ("supertrend_score", "Supertrend"),
        ("vwap_score",       "VWAP"),
        ("breakout_score",   "Breakout"),
        ("momentum_score",   "Momentum"),
        ("adx_score",        "ADX trend"),
    ]:
        v = signal.get(key)
        if v is not None and v != 0:
            components.append(f"    {label}: {'+' if v > 0 else ''}{v}")

    comp_block = "\n".join(components) if components else "    (component breakdown not available)"

    lines = [
        f"═══ QUANT SIGNAL — {symbol} ═══",
        f"  Action    : {action}",
        f"  Score     : {score}  (threshold ≥ {config.SIGNAL_THRESHOLD})",
        f"  Price     : ${price:,.2f}" if price else "  Price     : —",
        f"  Regime    : {regime}  |  ADX: {adx:.1f}" if adx else f"  Regime    : {regime}",
        f"  RSI       : {rsi:.1f}" if rsi else "  RSI       : —",
        f"  ATR       : {atr:.3f}" if atr else "",
        f"  Daily vol : {vol*100:.2f}%" if vol else "",
        "",
        "  Indicator breakdown:",
        comp_block,
        "",
        f"  Quant reason: {reason}",
        "",
        "═══ MARKET CONTEXT ═══",
        f"  SPY trend     : {market_trend}",
        f"  Earnings risk : {'YES — avoid new entry' if earnings_soon else 'No'}",
        f"  Sentiment trend: {'POSITIVE (+1)' if signal.get('sentiment_trend',0)>0 else ('NEGATIVE (-1)' if signal.get('sentiment_trend',0)<0 else 'NEUTRAL')}",
        f"  Macro event day: {'YES — reduce aggression' if signal.get('macro_event_day') else 'No'}",
        f"  Peer consensus : {'BEARISH — sector peers selling' if not signal.get('peer_consensus', True) else 'ok'}",
    ]
    return "\n".join(l for l in lines if l is not None)


def evaluate_signal(symbol: str, signal: dict) -> dict:
    # Pre-fetch news so the agent has context from turn 1
    news_block = ""
    try:
        import events
        news = events.fetch_news(symbols=[symbol], limit=6)
        headlines = [
            f"  [{n.get('created','')[:10]}] {html.escape(n['headline'])}"
            for n in news
            if n.get("headline")
        ]
        if headlines:
            news_block = "\n═══ RECENT NEWS (" + symbol + ") ═══\n" + "\n".join(headlines[:6])
        else:
            news_block = f"\n═══ RECENT NEWS ═══\n  No recent headlines found for {symbol}."
    except Exception:
        news_block = "\n═══ RECENT NEWS ═══\n  News unavailable."

    signal_summary = _build_signal_summary(symbol, signal)

    system = (
        "You are a senior trading analyst embedded in an automated quant trading system. "
        "The quant system has already applied 10+ technical filters (ADX regime switching, "
        "EMA200 gate, SPY bear market gate, earnings avoidance, relative-strength ranking, "
        "sector/correlation caps, trailing stops). When you receive a signal, the heavy "
        "lifting is already done.\n\n"
        "YOUR JOB:\n"
        "1. Check the account state (buying power, open positions) via tools.\n"
        "2. Read the news headlines for this ticker.\n"
        "3. Approve the trade UNLESS you find a genuine reason to reject:\n"
        "   • Breaking negative catalyst (earnings miss, fraud, CEO resignation, "
        "regulatory action, product recall, litigation)\n"
        "   • Buying power is clearly insufficient for even a minimum position\n"
        "   • Portfolio already at max concentration (5+ open positions)\n"
        "4. Do NOT reject based on ticker unfamiliarity, general market uncertainty, "
        "or because the score is 'only' 2. The quant system is calibrated — trust it.\n\n"
        "Always call approve_trade as your final action with a concise one-sentence reason."
    )

    user = (
        f"{signal_summary}"
        f"{news_block}\n\n"
        "Check the account state with get_account and get_positions, review the news above, "
        "then call approve_trade with your decision."
    )

    messages = [
        {"role": "system", "content": system},
        {"role": "user",   "content": user},
    ]

    for _ in range(8):
        try:
            response = client.chat.completions.create(
                model=config.OPENAI_MODEL,
                tools=TOOLS,
                messages=messages,
                temperature=0,
            )
        except Exception as exc:
            return {"approved": False, "reason": f"openai agent error: {exc}", "size_multiplier": 1.0, "suggested_stop_pct": None}

        msg = response.choices[0].message
        messages.append(msg)

        if not msg.tool_calls:
            return {"approved": False, "reason": "agent did not call approve_trade", "size_multiplier": 1.0, "suggested_stop_pct": None}

        final_decision = None
        tool_results = []

        for tc in msg.tool_calls:
            result = _run_tool(tc.function.name, tc.function.arguments)
            tool_results.append({
                "role":         "tool",
                "tool_call_id": tc.id,
                "content":      result,
            })
            if tc.function.name == "approve_trade":
                try:
                    final_decision = json.loads(tc.function.arguments)
                except Exception:
                    pass

        messages.extend(tool_results)

        if final_decision is not None:
            approved = final_decision.get("decision") == "approve"
            return {
                "approved": approved,
                "reason": final_decision.get("reason", ""),
                "size_multiplier": float(final_decision.get("size_multiplier", 1.0)),
                "suggested_stop_pct": final_decision.get("suggested_stop_pct"),
            }

    return {"approved": False, "reason": "agent loop exhausted without decision", "size_multiplier": 1.0, "suggested_stop_pct": None}
