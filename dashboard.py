import streamlit as st
import time

import broker
import strategy
import risk
import agent
import events
import config
import screener

st.set_page_config(page_title="TradeAgent", page_icon="📈", layout="wide", initial_sidebar_state="expanded")

# ── CSS ────────────────────────────────────────────────────────────────────────
st.markdown("""
<style>
@import url('https://fonts.googleapis.com/css2?family=Space+Grotesk:wght@300;400;500;600;700&display=swap');

* { font-family: 'Space Grotesk', sans-serif; }
footer, [data-testid="stHeader"] { visibility: hidden; }

/* ── Ticker tape ── */
.ticker-wrap {
    overflow: hidden;
    background: linear-gradient(90deg, #0f172b, #1e1b4b, #0f172b);
    border: 1px solid #3730a3;
    border-radius: 8px;
    padding: 10px 0;
    margin-bottom: 20px;
}
.ticker-track {
    display: flex;
    gap: 48px;
    animation: ticker 30s linear infinite;
    width: max-content;
}
@keyframes ticker { from { transform: translateX(0); } to { transform: translateX(-50%); } }
.ticker-item { display: flex; align-items: center; gap: 8px; white-space: nowrap; }
.ticker-sym  { font-weight: 700; font-size: 0.85rem; color: #a5b4fc; letter-spacing: 0.05em; }
.ticker-price { font-size: 0.85rem; color: #e2e8f0; }
.ticker-up   { font-size: 0.75rem; color: #34d399; font-weight: 600; }
.ticker-down { font-size: 0.75rem; color: #f87171; font-weight: 600; }

/* ── Metric cards ── */
[data-testid="stMetric"] {
    background: linear-gradient(135deg, #1e1b4b 0%, #0f172b 100%);
    border: 1px solid #3730a3;
    border-radius: 12px;
    padding: 18px 22px;
    position: relative;
    overflow: hidden;
}
[data-testid="stMetric"]::before {
    content: '';
    position: absolute;
    top: 0; left: 0; right: 0;
    height: 2px;
    background: linear-gradient(90deg, #615fff, #a78bfa, #38bdf8);
}
[data-testid="stMetricLabel"] { font-size: 0.68rem; letter-spacing: 0.1em; text-transform: uppercase; color: #94a3b8 !important; }
[data-testid="stMetricValue"] { font-size: 1.55rem; font-weight: 700; color: #e2e8f0 !important; }

/* ── Section headers ── */
.section-header {
    display: flex;
    align-items: center;
    gap: 10px;
    font-size: 0.68rem;
    font-weight: 700;
    letter-spacing: 0.12em;
    text-transform: uppercase;
    color: #94a3b8;
    margin: 32px 0 14px 0;
    padding-bottom: 8px;
    border-bottom: 1px solid #1e293b;
}
.section-dot {
    width: 6px; height: 6px;
    border-radius: 50%;
    display: inline-block;
}

/* ── Signal badges ── */
.badge {
    display: inline-block;
    padding: 3px 12px;
    border-radius: 20px;
    font-size: 0.75rem;
    font-weight: 700;
    letter-spacing: 0.05em;
}
.badge-buy  { background: #052e16; color: #34d399; border: 1px solid #059669; }
.badge-sell { background: #2d0a0a; color: #f87171; border: 1px solid #dc2626; }
.badge-hold { background: #1e293b; color: #94a3b8; border: 1px solid #334155; }

/* ── Event cards ── */
.event-card {
    background: linear-gradient(135deg, #0f172b, #1e1b4b 80%);
    border: 1px solid #334155;
    border-radius: 10px;
    padding: 14px 18px;
    margin-bottom: 10px;
    position: relative;
    overflow: hidden;
}
.event-card.bullish { border-left: 4px solid #34d399; }
.event-card.bearish { border-left: 4px solid #f87171; }
.event-card.neutral { border-left: 4px solid #64748b; }

/* ── Alert boxes ── */
.alert { border-radius: 10px; padding: 14px 18px; margin: 10px 0; font-weight: 500; }
.alert-success { background: linear-gradient(135deg,#052e16,#064e3b); border: 1px solid #059669; color: #34d399; }
.alert-danger  { background: linear-gradient(135deg,#2d0a0a,#450a0a); border: 1px solid #dc2626; color: #f87171; }
.alert-neutral { background: linear-gradient(135deg,#0f172b,#1e293b); border: 1px solid #334155; color: #94a3b8; }
.alert-info    { background: linear-gradient(135deg,#0c1a2e,#1e3a5f); border: 1px solid #3b82f6; color: #93c5fd; }

/* ── Sidebar ── */
[data-testid="stSidebar"] {
    background: linear-gradient(180deg, #0f172b 0%, #1e1b4b 100%) !important;
    border-right: 1px solid #3730a3;
}
hr { border-color: #1e293b !important; }

/* ── Code block ── */
[data-testid="stCode"] { border: 1px solid #334155; border-radius: 8px; }

/* ── Dataframe ── */
[data-testid="stDataFrame"] { border: 1px solid #334155; border-radius: 10px; overflow: hidden; }

/* ── Mode pill ── */
.mode-pill {
    display: inline-block;
    padding: 3px 14px;
    border-radius: 20px;
    font-size: 0.72rem;
    font-weight: 700;
    letter-spacing: 0.06em;
    text-transform: uppercase;
}
</style>
""", unsafe_allow_html=True)


# ── Helpers ────────────────────────────────────────────────────────────────────
def section(title: str, color: str = "#615fff"):
    st.markdown(
        f'<div class="section-header">'
        f'<span class="section-dot" style="background:{color}"></span>'
        f'{title}</div>',
        unsafe_allow_html=True,
    )


def event_card(label: str, score: int, confidence: str, reason: str):
    if score > 0:
        cls, icon, color = "bullish", "▲", "#34d399"
    elif score < 0:
        cls, icon, color = "bearish", "▼", "#f87171"
    else:
        cls, icon, color = "neutral", "●", "#64748b"
    st.markdown(f"""
    <div class="event-card {cls}">
        <span style="color:{color};font-weight:700;font-size:0.9rem">{icon} {label}</span>
        &nbsp;
        <span style="color:#64748b;font-size:0.78rem">score <b style="color:{color}">{score:+d}</b>
        &nbsp;·&nbsp; confidence <b style="color:#a5b4fc">{confidence}</b></span>
        <div style="color:#cbd5e1;font-size:0.83rem;margin-top:6px;line-height:1.4">{reason}</div>
    </div>""", unsafe_allow_html=True)


def alert(kind: str, text: str):
    icons = {"success": "▲", "danger": "▼", "neutral": "●", "info": "ℹ"}
    st.markdown(f'<div class="alert alert-{kind}">{icons.get(kind,"")} {text}</div>', unsafe_allow_html=True)


_SIGNAL_BADGES = {
    "BUY":  '<td><span style="background:#052e16;color:#34d399;border:1px solid #059669;padding:2px 12px;border-radius:20px;font-size:0.75rem;font-weight:700;letter-spacing:0.04em">▲ BUY</span></td>',
    "SELL": '<td><span style="background:#2d0a0a;color:#f87171;border:1px solid #dc2626;padding:2px 12px;border-radius:20px;font-size:0.75rem;font-weight:700;letter-spacing:0.04em">▼ SELL</span></td>',
    "HOLD": '<td><span style="background:#1e293b;color:#94a3b8;border:1px solid #334155;padding:2px 12px;border-radius:20px;font-size:0.75rem;font-weight:700;letter-spacing:0.04em">● HOLD</span></td>',
}


def _cell_signal(s: str) -> str:
    return _SIGNAL_BADGES.get(s, f'<td style="color:#f87171">{s}</td>')


def _cell_score(val) -> str:
    try:
        n = float(val)
        if n > 0:
            color, prefix = "#34d399", "+"
        elif n < 0:
            color, prefix = "#f87171", ""
        else:
            color, prefix = "#64748b", ""
        return f'<td style="color:{color};font-weight:700;text-align:center">{prefix}{int(n)}</td>'
    except (ValueError, TypeError):
        return f'<td>{val}</td>'


def _cell_pct(val) -> str:
    try:
        n = float(val)
        color = "#34d399" if n >= 0 else "#f87171"
        arrow = "▲" if n >= 0 else "▼"
        return f'<td style="color:{color};font-weight:600">{arrow} {abs(n):.2f}%</td>'
    except (ValueError, TypeError):
        return f'<td>{val}</td>'


def _cell_rsi(val) -> str:
    try:
        n = float(val)
        if n > 65:
            color = "#f87171"
        elif n < 35:
            color = "#34d399"
        else:
            color = "#e2e8f0"
        return f'<td style="color:{color}">{val}</td>'
    except (ValueError, TypeError):
        return f'<td>{val}</td>'


def _cell_pnl(val) -> str:
    s = str(val)
    color = "#34d399" if not s.startswith("-") else "#f87171"
    return f'<td style="color:{color};font-weight:600;font-family:monospace">{s}</td>'


_CELL_DISPATCH = {
    "Signal":           lambda v, s: _cell_signal(s),
    "Score":            lambda v, s: _cell_score(v),
    "change_pct":       lambda v, s: _cell_pct(v),
    "Symbol":           lambda v, s: f'<td style="color:#a5b4fc;font-weight:700;letter-spacing:0.04em">{s}</td>',
    "Price":            lambda v, s: f'<td style="color:#e2e8f0;font-family:monospace">{s}</td>',
    "price":            lambda v, s: f'<td style="color:#e2e8f0;font-family:monospace">{s}</td>',
    "avg_entry":        lambda v, s: f'<td style="color:#e2e8f0;font-family:monospace">{s}</td>',
    "current_price":    lambda v, s: f'<td style="color:#e2e8f0;font-family:monospace">{s}</td>',
    "unrealized_pnl":   lambda v, s: _cell_pnl(v),
    "unrealized_pnl_pct": lambda v, s: _cell_pnl(v),
    "RSI":              lambda v, s: _cell_rsi(v),
    "Reason":           lambda v, s: f'<td style="color:#94a3b8;font-size:0.8rem;max-width:320px">{s}</td>',
}


def _cell(val, col: str) -> str:
    s = str(val)
    fn = _CELL_DISPATCH.get(col)
    if fn:
        return fn(val, s)
    return f'<td style="color:#cbd5e1">{s}</td>'


def html_table(rows: list[dict]):
    """Render a list of dicts as a fully styled HTML table."""
    if not rows:
        return
    cols = list(rows[0].keys())

    header = "".join(
        f'<th style="color:#64748b;font-size:0.68rem;font-weight:700;letter-spacing:0.1em;'
        f'text-transform:uppercase;padding:10px 14px;border-bottom:1px solid #1e293b;'
        f'white-space:nowrap">{c}</th>'
        for c in cols
    )

    body = ""
    for i, row in enumerate(rows):
        bg = "#0d1424" if i % 2 == 0 else "#0f172b"
        cells = "".join(_cell(row[c], c) for c in cols)
        body += (
            f'<tr style="background:{bg};transition:background 0.15s" '
            f'onmouseover="this.style.background=\'#1e293b\'" '
            f'onmouseout="this.style.background=\'{bg}\'">'
            f'{cells}</tr>'
        )

    st.markdown(f"""
    <div style="border:1px solid #1e293b;border-radius:10px;overflow:hidden;margin-bottom:8px">
    <table style="width:100%;border-collapse:collapse;font-size:0.85rem">
      <thead><tr style="background:#0a0f1e">{header}</tr></thead>
      <tbody>{body}</tbody>
    </table>
    </div>""", unsafe_allow_html=True)


def ticker_tape(symbols: list[str]):
    """Scrolling live-price ticker tape."""
    items = []
    for sym in symbols:
        try:
            bars = broker.get_bars(sym, timeframe=bar_timeframe)
            if len(bars) >= 2:
                prev, last = bars[-2]["c"], bars[-1]["c"]
                chg = ((last - prev) / prev) * 100
                arrow = "▲" if chg >= 0 else "▼"
                cls   = "ticker-up" if chg >= 0 else "ticker-down"
                items.append(
                    f'<span class="ticker-item">'
                    f'<span class="ticker-sym">{sym}</span>'
                    f'<span class="ticker-price">${last:,.2f}</span>'
                    f'<span class="{cls}">{arrow}{abs(chg):.2f}%</span>'
                    f'</span>'
                )
        except Exception:
            pass

    if not items:
        return

    doubled = "".join(items) * 2   # duplicate for seamless loop
    st.markdown(
        f'<div class="ticker-wrap"><div class="ticker-track">{doubled}</div></div>',
        unsafe_allow_html=True,
    )


def signal_badge(sig: str) -> str:
    cls = {"BUY": "buy", "SELL": "sell"}.get(sig, "hold")
    return f'<span class="badge badge-{cls}">{sig}</span>'




# ── Sidebar ────────────────────────────────────────────────────────────────────
provider = config.AGENT_PROVIDER.upper() if config.USE_AGENT else "NONE"
provider_label = {"CLAUDE": "Claude", "OPENAI": "OpenAI", "NONE": "No LLM"}.get(provider, provider)

with st.sidebar:
    st.markdown("## 📈 TradeAgent")
    mode_color = "#f59e0b" if config.PAPER_TRADING else "#ef4444"
    mode_label = "Paper Trading" if config.PAPER_TRADING else "Live Trading"
    st.markdown(f'<span class="mode-pill" style="background:{mode_color}22;color:{mode_color};border:1px solid {mode_color}">{mode_label}</span>', unsafe_allow_html=True)

    st.markdown("---")
    auto_refresh = st.toggle("Auto-refresh (30s)", value=True)
    if st.button("⟳ Refresh Now", use_container_width=True):
        st.rerun()

    st.markdown("---")
    st.markdown("**Watchlist Source**")
    watch_source = st.selectbox("", ["static", "most_active", "gainers", "losers", "etf"],
        format_func=lambda x: {
            "static": "📌 Static (config.py)", "most_active": "🔥 Most Active",
            "gainers": "📈 Top Gainers", "losers": "📉 Top Losers", "etf": "🗂 ETFs by Theme",
        }[x], label_visibility="collapsed")

    etf_themes = None
    if watch_source == "etf":
        etf_themes = st.multiselect("Themes", options=list(screener.ETF_UNIVERSE.keys()), default=["Broad Market", "Tech"])

    top_n = 10
    if watch_source in ("most_active", "gainers", "losers"):
        top_n = st.slider("Top N", min_value=5, max_value=25, value=10)

    watchlist = screener.build_watchlist(watch_source, top_n=top_n, etf_themes=etf_themes or None)
    st.caption(f"{len(watchlist)} symbols · {', '.join(watchlist[:6])}{'…' if len(watchlist) > 6 else ''}")

    st.markdown("---")
    st.markdown("**Bar Timeframe**")
    bar_timeframe = st.selectbox("", ["1Min", "5Min", "15Min", "1Hour", "1Day"],
        index=["1Min", "5Min", "15Min", "1Hour", "1Day"].index(config.BAR_TIMEFRAME),
        format_func=lambda x: {
            "1Min": "1 Minute", "5Min": "5 Minutes", "15Min": "15 Minutes",
            "1Hour": "1 Hour", "1Day": "1 Day",
        }[x], label_visibility="collapsed")

    st.markdown("---")
    st.markdown("**Event Filters**")
    run_geo      = st.toggle("🌍 Geopolitical", value=True)
    run_earnings = st.toggle("📊 Earnings",     value=True)
    run_macro    = st.toggle("🏦 Macro",        value=True)

    st.markdown("---")
    st.markdown("**Manual Order**")
    manual_symbol = st.selectbox("Symbol", watchlist if watchlist else config.WATCHLIST, label_visibility="collapsed")
    manual_qty = st.number_input("Qty", min_value=1, value=1, step=1, label_visibility="collapsed")
    c1, c2 = st.columns(2)
    with c1:
        if st.button("BUY", use_container_width=True, type="primary"):
            try:
                order = broker.place_market_order(manual_symbol, manual_qty, "buy")
                st.success(f"#{order['id'][:8]}")
            except Exception as e:
                st.error(str(e))
    with c2:
        if st.button("SELL", use_container_width=True):
            try:
                result = broker.close_position(manual_symbol)
                st.success("Closed")
            except Exception as e:
                st.error(str(e))

    st.markdown("---")
    st.caption(f"🤖 Agent: **{provider_label}**")

# ── Header ─────────────────────────────────────────────────────────────────────
st.markdown(
    '<h1 style="background:linear-gradient(90deg,#a5b4fc,#38bdf8,#34d399);'
    '-webkit-background-clip:text;-webkit-text-fill-color:transparent;'
    'font-size:2rem;font-weight:700;margin-bottom:2px">TradeAgent</h1>',
    unsafe_allow_html=True,
)
st.markdown(
    f'<p style="color:#64748b;font-size:0.85rem;margin-top:0">'
    f'Agent: <b style="color:#a5b4fc">{provider_label}</b>'
    f' &nbsp;·&nbsp; {time.strftime("%A, %b %d  %H:%M")}</p>',
    unsafe_allow_html=True,
)

# ── Live ticker tape ───────────────────────────────────────────────────────────
with st.spinner(""):
    ticker_tape(watchlist[:12])

# ── Account metrics ────────────────────────────────────────────────────────────
try:
    account = broker.get_account()
    halt    = risk.check_drawdown(account)
    if halt:
        alert("danger", "MAX DRAWDOWN BREACHED — trading halted")

    section("Portfolio", "#a5b4fc")
    c1, c2, c3, c4 = st.columns(4)
    c1.metric("Portfolio Value", f"${account['portfolio_value']:,.2f}")
    c2.metric("Equity",         f"${account['equity']:,.2f}")
    c3.metric("Cash",           f"${account['cash']:,.2f}")
    c4.metric("Buying Power",   f"${account['buying_power']:,.2f}")

except Exception as e:
    st.error(f"Failed to load account: {e}")
    st.stop()

# ── Screener data ──────────────────────────────────────────────────────────────
if watch_source in ("most_active", "gainers", "losers"):
    label_map = {"most_active": "🔥 Most Active", "gainers": "📈 Top Gainers", "losers": "📉 Top Losers"}
    color_map = {"most_active": "#f59e0b", "gainers": "#34d399", "losers": "#f87171"}
    section(label_map[watch_source], color_map[watch_source])
    with st.spinner("Fetching screener..."):
        if watch_source == "most_active":
            rows = screener.most_active(top_n)
        elif watch_source == "gainers":
            rows = screener.top_gainers(top_n)
        else:
            rows = screener.top_losers(top_n)
    html_table(rows)

# ── Open positions ─────────────────────────────────────────────────────────────
section("Open Positions", "#38bdf8")
try:
    positions = broker.get_positions()
    if positions:
        for p in positions:
            p["unrealized_pnl"]     = f"${p['unrealized_pnl']:,.2f}"
            p["unrealized_pnl_pct"] = f"{p['unrealized_pnl_pct']*100:.2f}%"
            p["avg_entry"]          = f"${p['avg_entry']:,.2f}"
            p["current_price"]      = f"${p['current_price']:,.2f}"
        html_table(positions)
    else:
        alert("neutral", "No open positions.")
except Exception as e:
    st.error(f"Failed to load positions: {e}")

# ── Live signals ───────────────────────────────────────────────────────────────
section("Live Signals", "#34d399")

signal_cache = {}
signal_rows  = []

with st.spinner("Computing quant signals..."):
    for symbol in watchlist:
        try:
            bars = broker.get_bars(symbol, timeframe=bar_timeframe)
            sig  = strategy.compute_signals(bars)
            signal_cache[symbol] = sig
            signal_rows.append({
                "Symbol": symbol,
                "Price":  f"${sig['price']:,.2f}" if sig["price"] is not None else "—",
                "Signal": sig["signal"].upper(),
                "Score":  sig["score"],
                "RSI":    sig["rsi"] if sig["rsi"] is not None else "—",
                "Reason": sig["reason"],
            })
        except Exception as e:
            signal_rows.append({"Symbol": symbol, "Price": "—", "Signal": "ERROR", "Score": 0, "RSI": "—", "Reason": str(e)})

if not signal_rows:
    alert("neutral", "No symbols in watchlist.")
else:
    html_table(signal_rows)

# ── Event-driven signals ───────────────────────────────────────────────────────
section("Event-Driven Analysis", "#f59e0b")

if not config.USE_AGENT:
    alert("info", "Set AGENT_PROVIDER=claude or openai in .env to enable event analysis.")
else:
    left, right = st.columns([2, 1])
    with left:
        event_symbol = st.selectbox("Symbol", watchlist, key="event_sym", label_visibility="collapsed")
    with right:
        run_event = st.button(f"🔍 Analyse ({provider_label})", type="primary", use_container_width=True)

    if run_event:
        with st.spinner(f"{provider_label} scanning headlines..."):
            result = events.get_event_score(event_symbol, run_earnings=run_earnings, run_geo=run_geo, run_macro=run_macro)

        quant    = signal_cache.get(event_symbol, {"score": 0, "reason": "no quant data", "signal": "hold", "rsi": None, "price": None, "event_score": 0, "event_reasons": []})
        combined = strategy.apply_event_score(quant, result)

        m1, m2, m3 = st.columns(3)
        m1.metric("Quant Score",    quant["score"])
        m2.metric("Event Score",    result["event_score"])
        m3.metric("Combined Score", combined["score"])

        st.markdown("**Breakdown:**")
        for sig in result["signals"]:
            event_card(sig["event_type"].capitalize(), sig["score"], sig.get("confidence", "—"), sig["reason"])

        if combined["signal"] == "buy":
            alert("success", f"BUY signal — {combined['reason']}")
        elif combined["signal"] == "sell":
            alert("danger", f"SELL signal — {combined['reason']}")
        else:
            alert("neutral", f"HOLD — {combined['reason']}")

# ── Agent trade approval ───────────────────────────────────────────────────────
section("Agent Trade Approval", "#a78bfa")

al, ar = st.columns([2, 1])
with al:
    eval_symbol = st.selectbox("Symbol", watchlist, key="eval_sym", label_visibility="collapsed")
with ar:
    ask = st.button(f"🤖 Ask {provider_label}", type="primary", use_container_width=True)

if ask:
    try:
        bars = broker.get_bars(eval_symbol, timeframe=bar_timeframe)
        sig  = strategy.compute_signals(bars)
        with st.spinner(f"{provider_label} is thinking..."):
            approved, reason = agent.evaluate_signal(eval_symbol, sig)
        if approved:
            alert("success", f"✅ APPROVED — {reason}")
        else:
            alert("danger", f"❌ REJECTED — {reason}")
    except Exception as e:
        st.error(str(e))

# ── Trade log ──────────────────────────────────────────────────────────────────
section("Trade Log", "#64748b")
try:
    with open("trade.log", "r") as f:
        lines = f.readlines()
    st.code("".join(lines[-50:]), language="text")
except FileNotFoundError:
    alert("neutral", "No trade.log yet — run main.py to start logging.")

# ── Auto-refresh ───────────────────────────────────────────────────────────────
if auto_refresh:
    time.sleep(30)
    st.rerun()
