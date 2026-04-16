import streamlit as st
import time
import plotly.graph_objects as go

import broker
import strategy
import risk
import agent
import events
import config
import screener
import charts
import backtest
import watchlist_store
import settings_store
import shadow_book
import trade_journal
from main import get_active_watchlist

st.set_page_config(page_title="TradeAgent", page_icon="📈", layout="wide", initial_sidebar_state="expanded")

# ── CSS ────────────────────────────────────────────────────────────────────────
st.markdown("""
<style>
@import url('https://fonts.googleapis.com/css2?family=Space+Grotesk:wght@300;400;500;600;700&display=swap');
* { font-family: 'Space Grotesk', sans-serif; }
footer { visibility: hidden; }
#MainMenu { visibility: hidden; }
[data-testid="stDecoration"] { display: none !important; }
[data-testid="stHeader"] { background: #0a0f1e !important; border-bottom: 1px solid #1e293b !important; }
[data-testid="stAppDeployButton"] { display: none !important; }
[data-testid="stSidebar"] { display: none !important; }
[data-testid="collapsedControl"] { display: none !important; }
[data-testid="stSidebarCollapsedControl"] { display: none !important; }
[data-testid="block-container"] { padding-top: 1.25rem; padding-bottom: 1rem; max-width: 1500px; }

[data-testid="stMetric"] {
    background: linear-gradient(135deg, #1e1b4b 0%, #0f172b 100%);
    border: 1px solid #3730a3; border-radius: 12px; padding: 18px 22px; position: relative; overflow: hidden;
}
[data-testid="stMetric"]::before {
    content:''; position:absolute; top:0; left:0; right:0; height:2px;
    background: linear-gradient(90deg, #615fff, #a78bfa, #38bdf8);
}
[data-testid="stMetricLabel"] { font-size:0.68rem; letter-spacing:0.1em; text-transform:uppercase; color:#94a3b8 !important; }
[data-testid="stMetricValue"] { font-size:1.55rem; font-weight:700; color:#e2e8f0 !important; }

.section-header {
    display:flex; align-items:center; gap:10px;
    font-size:0.68rem; font-weight:700; letter-spacing:0.12em; text-transform:uppercase;
    color:#94a3b8; margin:18px 0 12px 0; padding-bottom:8px; border-bottom:1px solid #1e293b;
}
.section-dot { width:6px; height:6px; border-radius:50%; display:inline-block; }

.focus-strip { display:flex; gap:10px; flex-wrap:wrap; margin:10px 0 14px 0; }
.focus-chip {
    background:linear-gradient(135deg,#0f172b,#111827);
    border:1px solid #243244;
    border-radius:999px;
    padding:7px 12px;
    color:#cbd5e1;
    font-size:0.78rem;
    white-space:nowrap;
}
.focus-chip b {
    color:#a5b4fc;
    font-size:0.7rem;
    letter-spacing:0.08em;
    text-transform:uppercase;
    margin-right:8px;
}

.event-card { background:linear-gradient(135deg,#0f172b,#1e1b4b 80%); border:1px solid #334155; border-radius:10px; padding:14px 18px; margin-bottom:10px; }
.event-card.bullish { border-left:4px solid #34d399; }
.event-card.bearish { border-left:4px solid #f87171; }
.event-card.neutral { border-left:4px solid #64748b; }

.alert { border-radius:10px; padding:14px 18px; margin:10px 0; font-weight:500; }
.alert-success { background:linear-gradient(135deg,#052e16,#064e3b); border:1px solid #059669; color:#34d399; }
.alert-danger  { background:linear-gradient(135deg,#2d0a0a,#450a0a); border:1px solid #dc2626; color:#f87171; }
.alert-neutral { background:linear-gradient(135deg,#0f172b,#1e293b); border:1px solid #334155; color:#94a3b8; }
.alert-info    { background:linear-gradient(135deg,#0c1a2e,#1e3a5f); border:1px solid #3b82f6; color:#93c5fd; }

.stat-card {
    background:#0f172b; border:1px solid #334155; border-radius:10px;
    padding:16px 20px; text-align:center; margin-bottom:8px;
}
.stat-label { font-size:0.68rem; color:#64748b; text-transform:uppercase; letter-spacing:0.08em; }
.stat-value { font-size:1.3rem; font-weight:700; color:#e2e8f0; margin-top:4px; }
hr { border-color:#1e293b !important; }

.mode-pill { display:inline-block; padding:3px 14px; border-radius:20px; font-size:0.72rem; font-weight:700; letter-spacing:0.06em; text-transform:uppercase; }
.ticker-wrap { overflow:hidden; background:linear-gradient(90deg,#0f172b,#1e1b4b,#0f172b); border:1px solid #3730a3; border-radius:8px; padding:10px 0; margin-bottom:20px; }
.ticker-track { display:flex; gap:48px; animation:ticker 30s linear infinite; width:max-content; }
@keyframes ticker { from{transform:translateX(0)} to{transform:translateX(-50%)} }
.ticker-item { display:flex; align-items:center; gap:8px; white-space:nowrap; }
.ticker-sym   { font-weight:700; font-size:0.85rem; color:#a5b4fc; letter-spacing:0.05em; }
.ticker-price { font-size:0.85rem; color:#e2e8f0; }
.ticker-up    { font-size:0.75rem; color:#34d399; font-weight:600; }
.ticker-down  { font-size:0.75rem; color:#f87171; font-weight:600; }

/* ── Tabs ── */
[data-testid="stTabs"] {
    background: #080d1a;
    border: 1px solid #1e293b;
    border-radius: 14px;
    padding: 0 4px 4px 4px;
    margin-top: 8px;
}
[data-testid="stTabs"] > div:first-child {
    background: linear-gradient(90deg, #0a0f1e, #0f172b);
    border-radius: 12px 12px 0 0;
    padding: 6px 8px 0 8px;
    border-bottom: 1px solid #1e293b;
    gap: 4px;
    overflow-x: auto;
    scrollbar-width: none;
}
[data-testid="stTabs"] > div:first-child::-webkit-scrollbar { display: none; }

[data-testid="stTab"] {
    background: transparent !important;
    border: 1px solid transparent !important;
    border-bottom: none !important;
    border-radius: 8px 8px 0 0 !important;
    color: #64748b !important;
    font-size: 0.78rem !important;
    font-weight: 600 !important;
    letter-spacing: 0.04em !important;
    padding: 8px 14px !important;
    white-space: nowrap;
    transition: all 0.15s ease;
}
[data-testid="stTab"]:hover {
    background: #1e293b !important;
    color: #a5b4fc !important;
    border-color: #334155 !important;
}
[data-testid="stTab"][aria-selected="true"] {
    background: linear-gradient(135deg, #1e1b4b, #0f172b) !important;
    border-color: #3730a3 !important;
    border-bottom-color: transparent !important;
    color: #a5b4fc !important;
    box-shadow: 0 -2px 0 0 #615fff inset;
}
[data-testid="stTabPanel"] {
    background: #080d1a;
    border-radius: 0 0 12px 12px;
    padding: 20px 18px !important;
}

div[data-testid="stRadio"] > div {
    gap: 0.45rem;
    flex-wrap: wrap;
}
div[data-testid="stRadio"] label {
    background: linear-gradient(135deg,#0f172b,#111827);
    border: 1px solid #334155;
    border-radius: 999px;
    padding: 0.2rem 0.7rem;
    transition: all 0.15s ease;
}
div[data-testid="stRadio"] label:hover {
    border-color: #615fff;
    transform: translateY(-1px);
}
div[data-testid="stRadio"] label p {
    color: #94a3b8 !important;
    font-size: 0.82rem !important;
    font-weight: 600 !important;
}
div[data-testid="stRadio"] label:has(input:checked) {
    border-color: #615fff;
    box-shadow: 0 0 0 1px #615fff33 inset;
    background: linear-gradient(135deg,#1e1b4b,#0f172b);
}
div[data-testid="stRadio"] label:has(input:checked) p {
    color: #e2e8f0 !important;
}

/* ── Inputs ── */
[data-testid="stSelectbox"] > div > div,
[data-testid="stNumberInput"] input,
[data-testid="stTextInput"] input {
    background: #0f172b !important;
    border: 1px solid #334155 !important;
    border-radius: 8px !important;
    color: #e2e8f0 !important;
    font-size: 0.83rem !important;
}
[data-testid="stSelectbox"] > div > div:focus-within,
[data-testid="stTextInput"] input:focus {
    border-color: #615fff !important;
    box-shadow: 0 0 0 2px #615fff33 !important;
}

/* ── Buttons ── */
[data-testid="stButton"] > button {
    border-radius: 8px !important;
    font-size: 0.82rem !important;
    font-weight: 600 !important;
    letter-spacing: 0.03em !important;
    transition: all 0.15s ease !important;
}
[data-testid="stButton"] > button[kind="primary"] {
    background: linear-gradient(135deg, #4f46e5, #615fff) !important;
    border: none !important;
    box-shadow: 0 2px 12px #615fff44 !important;
}
[data-testid="stButton"] > button[kind="primary"]:hover {
    background: linear-gradient(135deg, #615fff, #818cf8) !important;
    box-shadow: 0 4px 20px #615fff66 !important;
    transform: translateY(-1px);
}
[data-testid="stButton"] > button:not([kind="primary"]) {
    background: #1e293b !important;
    border: 1px solid #334155 !important;
    color: #94a3b8 !important;
}
[data-testid="stButton"] > button:not([kind="primary"]):hover {
    border-color: #615fff !important;
    color: #a5b4fc !important;
}

/* ── Sliders ── */
[data-testid="stSlider"] [data-testid="stThumbValue"] { color: #a5b4fc !important; }
[data-testid="stSlider"] [role="slider"] { background: #615fff !important; border-color: #a78bfa !important; }

/* ── Expander ── */
[data-testid="stExpander"] {
    background: #0f172b !important;
    border: 1px solid #1e293b !important;
    border-radius: 10px !important;
}
[data-testid="stExpander"] summary { color: #94a3b8 !important; font-size: 0.82rem !important; }

/* ── Spinner ── */
[data-testid="stSpinner"] { color: #615fff !important; }
</style>
""", unsafe_allow_html=True)


# ── Helpers ────────────────────────────────────────────────────────────────────
def section(title, color="#615fff"):
    st.markdown(f'<div class="section-header"><span class="section-dot" style="background:{color}"></span>{title}</div>', unsafe_allow_html=True)

def alert(kind, text):
    icons = {"success":"▲","danger":"▼","neutral":"●","info":"ℹ"}
    st.markdown(f'<div class="alert alert-{kind}">{icons.get(kind,"")} {text}</div>', unsafe_allow_html=True)

def stat_card(label, value, color="#e2e8f0"):
    st.markdown(f'<div class="stat-card"><div class="stat-label">{label}</div><div class="stat-value" style="color:{color}">{value}</div></div>', unsafe_allow_html=True)

def focus_chips(items):
    chips = "".join(f'<span class="focus-chip"><b>{label}</b>{value}</span>' for label, value in items)
    st.markdown(f'<div class="focus-strip">{chips}</div>', unsafe_allow_html=True)

def event_card(label, score, confidence, reason):
    if score > 0:   cls, icon, color = "bullish", "▲", "#34d399"
    elif score < 0: cls, icon, color = "bearish", "▼", "#f87171"
    else:           cls, icon, color = "neutral",  "●", "#64748b"
    st.markdown(f"""<div class="event-card {cls}">
        <span style="color:{color};font-weight:700;font-size:0.9rem">{icon} {label}</span>
        &nbsp;<span style="color:#64748b;font-size:0.78rem">score <b style="color:{color}">{score:+d}</b> &nbsp;·&nbsp; confidence <b style="color:#a5b4fc">{confidence}</b></span>
        <div style="color:#cbd5e1;font-size:0.83rem;margin-top:6px;line-height:1.4">{reason}</div>
    </div>""", unsafe_allow_html=True)

_P = 'padding:8px 14px;vertical-align:middle'  # shared td padding

_SIGNAL_BADGES = {
    "BUY":  f'<td style="{_P};white-space:nowrap"><span style="background:#052e16;color:#34d399;border:1px solid #059669;padding:2px 12px;border-radius:20px;font-size:0.75rem;font-weight:700">▲ BUY</span></td>',
    "SELL": f'<td style="{_P};white-space:nowrap"><span style="background:#2d0a0a;color:#f87171;border:1px solid #dc2626;padding:2px 12px;border-radius:20px;font-size:0.75rem;font-weight:700">▼ SELL</span></td>',
    "HOLD": f'<td style="{_P};white-space:nowrap"><span style="background:#1e293b;color:#94a3b8;border:1px solid #334155;padding:2px 12px;border-radius:20px;font-size:0.75rem;font-weight:700">● HOLD</span></td>',
}
_STATUS_COLORS = {"FILLED":"#34d399","CANCELED":"#f87171","PENDING_NEW":"#f59e0b","NEW":"#f59e0b","PARTIALLY_FILLED":"#a5b4fc","REJECTED":"#f87171"}

def _cell_score(v):
    try:
        n = float(v)
        if n > 0:   color, prefix = "#34d399", "+"
        elif n < 0: color, prefix = "#f87171", ""
        else:       color, prefix = "#64748b", ""
        return f'<td style="{_P};color:{color};font-weight:700;text-align:center;white-space:nowrap">{prefix}{int(n)}</td>'
    except Exception:
        return f'<td style="{_P}">{v}</td>'

def _cell_pnl(v):
    s = str(v)
    color = "#34d399" if not s.startswith("-") else "#f87171"
    return f'<td style="{_P};color:{color};font-weight:600;font-family:monospace;white-space:nowrap">{s}</td>'

def _cell_rsi(v):
    try:
        n = float(v)
        color = "#f87171" if n > 65 else ("#34d399" if n < 35 else "#e2e8f0")
        return f'<td style="{_P};color:{color};white-space:nowrap">{v}</td>'
    except Exception:
        return f'<td style="{_P}">{v}</td>'

def _cell_pct(v):
    try:
        n = float(v)
        color = "#34d399" if n >= 0 else "#f87171"
        arrow = "▲" if n >= 0 else "▼"
        return f'<td style="{_P};color:{color};font-weight:600;white-space:nowrap">{arrow} {abs(n):.2f}%</td>'
    except Exception:
        return f'<td style="{_P}">{v}</td>'

def _cell_text(s: str, color: str = "#94a3b8", width: str = "240px") -> str:
    """
    Single-line truncated text cell.
    max-width on <td> is ignored by browsers — the constraint must be on an
    inner block element (div). Full text shown via title tooltip on hover.
    """
    safe = s.replace('"', "&quot;").replace("'", "&#39;")
    return (
        f'<td style="{_P}">'
        f'<div style="color:{color};font-size:0.8rem;white-space:nowrap;'
        f'overflow:hidden;text-overflow:ellipsis;max-width:{width}" title="{safe}">'
        f'{s}</div></td>'
    )

_CELL_DISPATCH = {
    "Signal":   lambda v,s: _SIGNAL_BADGES.get(s, f'<td style="{_P};color:#f87171">{s}</td>'),
    "Score":    lambda v,s: _cell_score(v),
    "side":     lambda v,s: f'<td style="{_P}"><span style="color:{"#34d399" if s.upper() in ("BUY","LONG") else "#f87171"};font-weight:700">{s}</span></td>',
    "status":   lambda v,s: f'<td style="{_P};color:{_STATUS_COLORS.get(s.upper(),"#94a3b8")};font-weight:600;font-size:0.8rem">{s}</td>',
    "Symbol":   lambda v,s: f'<td style="{_P};color:#a5b4fc;font-weight:700;letter-spacing:0.04em;white-space:nowrap">{s}</td>',
    "symbol":   lambda v,s: f'<td style="{_P};color:#a5b4fc;font-weight:700;letter-spacing:0.04em;white-space:nowrap">{s}</td>',
    "RSI":         lambda v,s: _cell_rsi(v),
    "Reason":      lambda v,s: _cell_text(s, "#94a3b8", "260px"),
    "reason":      lambda v,s: _cell_text(s, "#94a3b8", "260px"),
    "exit_reason": lambda v,s: _cell_text(s, "#64748b", "140px"),
    "Headline":    lambda v,s: _cell_text(s, "#cbd5e1", "340px"),
    "change_pct":  lambda v,s: _cell_pct(v),
    "pnl":         lambda v,s: _cell_pnl(v),
    "pnl_pct":     lambda v,s: _cell_pct(v),
    "unrealized_pnl":     lambda v,s: _cell_pnl(v),
    "unrealized_pnl_pct": lambda v,s: _cell_pnl(v),
    "time":        lambda v,s: f'<td style="{_P};color:#64748b;font-size:0.8rem;font-family:monospace;white-space:nowrap">{s}</td>',
    "ATR":         lambda _,s: f'<td style="{_P};color:#64748b;font-size:0.8rem;font-family:monospace;white-space:nowrap">{s}</td>',
    "Volume":      lambda _,s: f'<td style="{_P};color:#94a3b8;font-family:monospace;font-size:0.85rem;white-space:nowrap">{s}</td>',
    "Trade Count": lambda _,s: f'<td style="{_P};color:#94a3b8;font-family:monospace;font-size:0.85rem;white-space:nowrap">{s}</td>',
    "Agent": lambda v,s: (
        f'<td style="{_P};text-align:center;white-space:nowrap" title="{s}">'
        f'<span style="font-size:0.75rem;font-weight:700;'
        f'color:{"#34d399" if "approve" in s.lower() else "#f87171"};'
        f'background:{"#052e16" if "approve" in s.lower() else "#2d0a0a"};'
        f'border:1px solid {"#059669" if "approve" in s.lower() else "#dc2626"};'
        f'padding:1px 8px;border-radius:20px">'
        f'{"✓ OK" if "approve" in s.lower() else "✗ No"}</span></td>'
        if s not in ("—", "")
        else f'<td style="{_P};color:#334155;text-align:center;font-size:0.78rem">—</td>'
    ),
    **{k: (lambda v,s: f'<td style="{_P};color:#e2e8f0;font-family:monospace;white-space:nowrap">{s}</td>')
       for k in ["Price","price","avg_entry","current_price","filled_avg","value","entry","exit"]},
}

def html_table(rows, max_height=420):
    if not rows: return
    cols = list(rows[0].keys())
    header = "".join(
        f'<th style="color:#64748b;font-size:0.68rem;font-weight:700;letter-spacing:0.1em;'
        f'text-transform:uppercase;padding:10px 14px;border-bottom:1px solid #1e293b;'
        f'white-space:nowrap;position:sticky;top:0;background:#0a0f1e;z-index:2">{c}</th>'
        for c in cols
    )
    body = ""
    for i, row in enumerate(rows):
        bg = "#0d1424" if i % 2 == 0 else "#0f172b"
        cells = "".join(
            _CELL_DISPATCH.get(
                c,
                lambda v, s: f'<td style="{_P};color:#cbd5e1;white-space:nowrap">{s}</td>'
            )(row[c], str(row[c]))
            for c in cols
        )
        body += (
            f'<tr style="background:{bg}" '
            f'onmouseover="this.style.background=\'#1e293b\'" '
            f'onmouseout="this.style.background=\'{bg}\'">{cells}</tr>'
        )
    _height_style = f"max-height:{int(max_height)}px;" if max_height else ""
    # Use a scoped style block — `max-width` on inner divs (not td) is what
    # actually constrains text columns in browsers.
    st.markdown(
        f'<div style="border:1px solid #1e293b;border-radius:10px;overflow:auto;'
        f'{_height_style}margin-bottom:8px">'
        f'<table style="border-collapse:collapse;font-size:0.85rem;white-space:nowrap;width:100%">'
        f'<thead><tr style="background:#0a0f1e">{header}</tr></thead>'
        f'<tbody>{body}</tbody></table></div>',
        unsafe_allow_html=True,
    )

def ticker_tape(symbols):
    items = []
    for sym in symbols:
        try:
            bars = broker.get_bars(sym)
            if len(bars) >= 2:
                prev, last = bars[-2]["c"], bars[-1]["c"]
                chg = ((last - prev) / prev) * 100
                cls = "ticker-up" if chg >= 0 else "ticker-down"
                arrow = "▲" if chg >= 0 else "▼"
                items.append(f'<span class="ticker-item"><span class="ticker-sym">{sym}</span><span class="ticker-price">${last:,.2f}</span><span class="{cls}">{arrow}{abs(chg):.2f}%</span></span>')
        except Exception:
            pass
    if not items: return
    doubled = "".join(items) * 2
    st.markdown(f'<div class="ticker-wrap"><div class="ticker-track">{doubled}</div></div>', unsafe_allow_html=True)


provider = config.AGENT_PROVIDER.upper() if config.USE_AGENT else "NONE"
provider_label = {"CLAUDE":"Claude","OPENAI":"OpenAI","NONE":"No LLM"}.get(provider, provider)


@st.cache_data(ttl=120)
def _fetch_trending_tape(top_n: int = 20) -> list[dict]:
    """
    Fetch live trending tickers for the header tape.
    Returns list of {sym, price, chg_pct} dicts, cached 2 min.
    """
    try:
        symbols = screener.trending(top_n)
    except Exception:
        symbols = []
    items = []
    for sym in symbols:
        try:
            bars = broker.get_bars(sym, timeframe="1Day", lookback_days=3)
            if len(bars) >= 2:
                prev, last = float(bars[-2]["c"]), float(bars[-1]["c"])
                chg = (last - prev) / prev * 100
                items.append({"sym": sym, "price": last, "chg": chg})
        except Exception:
            pass
    return items


def build_signal_snapshot(watchlist, bar_timeframe, run_agent: bool = False):
    signal_cache = {}
    signal_rows = []
    with st.spinner("Computing signals..."):
        for symbol in watchlist:
            try:
                bars = broker.get_bars(symbol, timeframe=bar_timeframe)
                sig = strategy.compute_signals(bars)
                signal_cache[symbol] = sig

                agent_val = "—"
                if run_agent and config.USE_AGENT and sig["signal"] != "hold":
                    try:
                        _res = agent.evaluate_signal(symbol, sig)
                        agent_val = f"approved:{_res['reason'][:40]}" if _res["approved"] else f"rejected:{_res['reason'][:40]}"
                    except Exception:
                        agent_val = "—"

                signal_rows.append({
                    "Symbol": symbol,
                    "Price": f"${sig['price']:,.2f}" if sig["price"] else "—",
                    "Signal": sig["signal"].upper(),
                    "Score": sig["score"],
                    "Regime": str(sig.get("regime", "range")).replace("_", " ").title(),
                    "RSI": sig["rsi"] if sig["rsi"] else "—",
                    "ATR": f"{sig['atr']:.3f}" if sig.get("atr") else "—",
                    "Reason": sig["reason"],
                    **({"Agent": agent_val} if run_agent else {}),
                })
            except Exception as e:
                signal_rows.append({
                    "Symbol": symbol,
                    "Price": "—",
                    "Signal": "ERROR",
                    "Score": 0,
                    "Regime": "—",
                    "RSI": "—",
                    "ATR": "—",
                    "Reason": str(e),
                    **({"Agent": "—"} if run_agent else {}),
                })
    return signal_cache, signal_rows


def render_screener_snapshot(watch_source, top_n):
    if watch_source not in ("most_active", "gainers", "losers"):
        return
    label_map = {"most_active": "Most Active", "gainers": "Top Gainers", "losers": "Top Losers"}
    color_map = {"most_active": "#f59e0b", "gainers": "#34d399", "losers": "#f87171"}
    section(label_map[watch_source], color_map[watch_source])
    with st.spinner("Fetching screener..."):
        if watch_source == "most_active":
            raw = screener.most_active(top_n)
            rows = [
                {
                    "Symbol": r["symbol"],
                    "Volume": f"{int(r['volume']):,}" if r.get("volume") else "—",
                    "Trade Count": f"{int(r['trade_count']):,}" if r.get("trade_count") else "—",
                }
                for r in raw
            ]
        elif watch_source == "gainers":
            raw = screener.top_gainers(top_n)
            rows = [
                {
                    "Symbol": r["symbol"],
                    "Price": f"${float(r['price']):,.2f}" if r.get("price") else "—",
                    "change_pct": round(float(r["change_pct"]), 2) if r.get("change_pct") is not None else 0,
                }
                for r in raw
            ]
        else:
            raw = screener.top_losers(top_n)
            rows = [
                {
                    "Symbol": r["symbol"],
                    "Price": f"${float(r['price']):,.2f}" if r.get("price") else "—",
                    "change_pct": round(float(r["change_pct"]), 2) if r.get("change_pct") is not None else 0,
                }
                for r in raw
            ]
    html_table(rows, max_height=220)


def render_control_deck():
    _saved_settings = settings_store.load()
    top_n = 10

    section("Control Deck", "#38bdf8")
    with st.expander("Open trading controls", expanded=False):
        top_left, top_mid, top_right = st.columns([1.5, 1.2, 1.3])

        with top_left:
            st.markdown("**Watchlist Source**")
            watch_source = st.selectbox(
                "",
                ["my_list", "trending", "most_active", "gainers", "losers", "sector", "etf"],
                format_func=lambda x: {
                    "my_list":     "My List",
                    "trending":    "🔥 Trending Now",
                    "most_active": "Most Active",
                    "gainers":     "Top Gainers",
                    "losers":      "Top Losers",
                    "sector":      "Sector + ETF",
                    "etf":         "ETF Themes",
                }[x],
                label_visibility="collapsed",
            )

            if not watchlist_store.load():
                for _sym in config.WATCHLIST:
                    watchlist_store.add(_sym)

            if watch_source == "my_list":
                _my_wl = watchlist_store.load()
                _add_col, _btn_col = st.columns([3, 1])
                with _add_col:
                    _new_sym = st.text_input("Add ticker", placeholder="GOOG", label_visibility="collapsed", key="wl_add").upper().strip()
                with _btn_col:
                    if st.button("Add", use_container_width=True, key="wl_add_btn") and _new_sym:
                        watchlist_store.add(_new_sym)
                        st.rerun()

                if _my_wl:
                    for _sym in _my_wl[:8]:
                        _c1, _c2 = st.columns([4, 1])
                        _c1.markdown(f'<div style="padding:4px 0;color:#a5b4fc;font-weight:600;font-size:0.85rem">{_sym}</div>', unsafe_allow_html=True)
                        if _c2.button("x", key=f"rm_{_sym}", help=f"Remove {_sym}"):
                            watchlist_store.remove(_sym)
                            st.rerun()
                watchlist = _my_wl
            elif watch_source == "etf":
                etf_themes = st.multiselect("Themes", options=list(screener.ETF_UNIVERSE.keys()), default=["Broad Market", "Tech"])
                watchlist = screener.build_watchlist(watch_source, etf_themes=etf_themes or None)
            elif watch_source == "sector":
                _all_sectors = sorted(screener.SECTOR_UNIVERSE.keys())
                _sel_sectors = st.multiselect(
                    "Sectors",
                    options=_all_sectors,
                    default=["Tech", "Finance", "Broad Market"],
                    key="sector_pick",
                )
                watchlist = screener.build_watchlist("sector", sectors=_sel_sectors or None)
            elif watch_source == "trending":
                top_n = st.slider("Top N", 5, 30, 15)
                watchlist = screener.build_watchlist("trending", top_n=top_n)
            else:
                top_n = st.slider("Top N", 5, 25, 10)
                watchlist = screener.build_watchlist(watch_source, top_n=top_n)

        with top_mid:
            st.markdown("**Chart Feed**")
            bar_timeframe = st.selectbox(
                "",
                ["1Min", "5Min", "15Min", "1Hour", "1Day"],
                index=["1Min", "5Min", "15Min", "1Hour", "1Day"].index(config.BAR_TIMEFRAME),
                format_func=lambda x: {"1Min": "1 Min", "5Min": "5 Min", "15Min": "15 Min", "1Hour": "1 Hour", "1Day": "1 Day"}[x],
                label_visibility="collapsed",
            )

            auto_refresh = st.toggle("Auto-refresh (30s)", value=False)
            if st.button("Refresh Now", use_container_width=True):
                st.rerun()

            st.markdown("**Event Filters**")
            run_geo = st.toggle("Geopolitical", value=True)
            run_earnings = st.toggle("Earnings", value=True)
            run_macro = st.toggle("Macro", value=True)

        with top_right:
            st.markdown("**Trading Mode**")
            dry_run_ui = st.toggle("Dry Run", value=config.DRY_RUN)
            shadow_mode = st.toggle("Shadow Mode", value=getattr(config, "SHADOW_MODE", False))
            allow_short = st.toggle("Allow Short Selling", value=config.ALLOW_SHORT)
            if dry_run_ui != config.DRY_RUN:
                settings_store.save({"dry_run": dry_run_ui})
            if shadow_mode != getattr(config, "SHADOW_MODE", False):
                settings_store.save({"shadow_mode": shadow_mode})
            if allow_short != config.ALLOW_SHORT:
                settings_store.save({"allow_short": allow_short})

            st.markdown("**Manual Order**")
            manual_symbol = st.selectbox("Symbol", watchlist if watchlist else config.WATCHLIST, label_visibility="collapsed")
            manual_qty = st.number_input("Qty", min_value=1, value=1, step=1, label_visibility="collapsed")
            _buy_col, _sell_col = st.columns(2)
            with _buy_col:
                if st.button("BUY", use_container_width=True, type="primary"):
                    try:
                        if getattr(config, "SHADOW_MODE", False):
                            _bars = broker.get_bars(manual_symbol)
                            _px = float(_bars[-1]["c"]) if _bars else 0.0
                            shadow_book.record_intent(manual_symbol, "buy", manual_qty, _px, "manual order", 0)
                            shadow_book.open_position(manual_symbol, "long", manual_qty, _px, "manual order", 0)
                            st.success("Shadow BUY recorded")
                        elif config.DRY_RUN:
                            st.info("Dry run enabled: no order placed")
                        else:
                            order = broker.place_market_order(manual_symbol, manual_qty, "buy")
                            st.success(f"#{order['id'][:8]}")
                    except Exception as e:
                        st.error(str(e))
            with _sell_col:
                if st.button("SELL", use_container_width=True):
                    try:
                        if getattr(config, "SHADOW_MODE", False):
                            _bars = broker.get_bars(manual_symbol)
                            _pos = shadow_book.get_position(manual_symbol)
                            _px = float(_bars[-1]["c"]) if _bars else float(_pos["entry_price"]) if _pos else 0.0
                            trade = shadow_book.close_position(manual_symbol, _px, reason="manual close")
                            if trade:
                                st.success("Shadow position closed")
                            else:
                                st.info("No shadow position to close")
                        elif config.DRY_RUN:
                            st.info("Dry run enabled: no order placed")
                        else:
                            broker.close_position(manual_symbol)
                            st.success("Closed")
                    except Exception as e:
                        st.error(str(e))

        st.markdown("---")
        risk_left, risk_mid, risk_right = st.columns([1.4, 1, 1])
        with risk_left:
            st.markdown("**Risk Settings**")
            _sl_default = int(_saved_settings.get("sl_pct", config.STOP_LOSS_PCT) * 100)
            _tp_default = int(_saved_settings.get("tp_pct", config.TAKE_PROFIT_PCT) * 100)
            _daily_stop_default = int(_saved_settings.get("daily_loss_stop_pct", config.DAILY_LOSS_STOP_PCT) * 100)
            _sector_cap_default = int(_saved_settings.get("max_sector_exposure_pct", config.MAX_SECTOR_EXPOSURE_PCT) * 100)
            sl_pct = st.slider("Stop Loss %", 0, 20, _sl_default) / 100
            tp_pct = st.slider("Take Profit %", 0, 50, _tp_default) / 100
            daily_loss_stop_pct = st.slider("Daily Loss Stop %", 0, 20, _daily_stop_default) / 100
            max_sector_exposure_pct = st.slider("Sector Cap %", 0, 100, _sector_cap_default) / 100

        with risk_mid:
            st.markdown("**Correlation Controls**")
            _corr_cap_default = bool(_saved_settings.get("enable_correlation_cap", config.ENABLE_CORRELATION_CAP))
            _max_corr_default = max(0.50, min(0.99, float(_saved_settings.get("max_correlation", config.MAX_CORRELATION))))
            _max_corr_positions_default = max(1, min(20, int(_saved_settings.get("max_correlated_positions", config.MAX_CORRELATED_POSITIONS))))
            _corr_lookback_default = max(20, min(365, int(_saved_settings.get("correlation_lookback_days", config.CORRELATION_LOOKBACK_DAYS))))
            enable_correlation_cap = st.toggle("Enable Correlation Cap", value=_corr_cap_default)
            max_correlation = st.slider("Max Correlation", 0.50, 0.99, _max_corr_default, 0.01)
            max_correlated_positions = st.number_input("Max Correlated Holdings", min_value=1, max_value=20, value=_max_corr_positions_default, step=1)
            correlation_lookback_days = st.slider("Correlation Lookback", 20, 365, _corr_lookback_default, 5)

        with risk_right:
            st.markdown("**Account Actions**")
            if st.button("Close All Positions", use_container_width=True):
                try:
                    positions = broker.get_positions()
                    for p in positions:
                        broker.close_position(p["symbol"])
                    st.success(f"Closed {len(positions)} position(s)")
                    st.rerun()
                except Exception as e:
                    st.error(str(e))
            if st.button("Reset Risk Halt", use_container_width=True):
                risk.reset_halts(reset_peak=False)
                st.success("Risk halts reset.")
                st.rerun()

            st.caption(f"Agent: {provider_label}")

        _risk_settings_payload = {
            "sl_pct": sl_pct,
            "tp_pct": tp_pct,
            "daily_loss_stop_pct": daily_loss_stop_pct,
            "max_sector_exposure_pct": max_sector_exposure_pct,
            "enable_correlation_cap": enable_correlation_cap,
            "max_correlation": max_correlation,
            "max_correlated_positions": int(max_correlated_positions),
            "correlation_lookback_days": int(correlation_lookback_days),
        }
        if any(_saved_settings.get(k) != v for k, v in _risk_settings_payload.items()):
            settings_store.save(_risk_settings_payload)

    return {
        "auto_refresh": auto_refresh,
        "watch_source": watch_source,
        "watchlist": watchlist,
        "bar_timeframe": bar_timeframe,
        "sl_pct": sl_pct,
        "tp_pct": tp_pct,
        "daily_loss_stop_pct": daily_loss_stop_pct,
        "max_sector_exposure_pct": max_sector_exposure_pct,
        "max_correlation": max_correlation,
        "max_correlated_positions": int(max_correlated_positions),
        "run_geo": run_geo,
        "run_earnings": run_earnings,
        "run_macro": run_macro,
        "top_n": top_n,
        "dry_run_ui": dry_run_ui,
        "shadow_mode": shadow_mode,
        "allow_short": allow_short,
    }

# ── Header ─────────────────────────────────────────────────────────────────────
import os as _os
_log_path = _os.path.join(_os.path.dirname(__file__), "trade.log")
_log_age  = time.time() - _os.path.getmtime(_log_path) if _os.path.exists(_log_path) else float("inf")
_loop_running = _log_age < config.LOOP_INTERVAL_SEC * 2.5

_run_color = "#34d399" if _loop_running else "#64748b"
_run_label = "● Running" if _loop_running else "○ Stopped"

st.markdown(f"""
<div style="display:flex;align-items:center;gap:16px;margin-bottom:6px;padding-bottom:12px;border-bottom:1px solid #1e293b">
  <div style="
      width:48px;height:48px;border-radius:14px;flex-shrink:0;
      background:linear-gradient(135deg,#4f46e5 0%,#06b6d4 100%);
      display:flex;align-items:center;justify-content:center;
      font-size:1.5rem;box-shadow:0 4px 20px #4f46e566">
    ◈
  </div>
  <div>
    <div style="display:flex;align-items:baseline;gap:10px">
      <span style="
          font-size:1.9rem;font-weight:800;letter-spacing:-0.02em;
          background:linear-gradient(90deg,#a5b4fc,#38bdf8,#34d399);
          -webkit-background-clip:text;-webkit-text-fill-color:transparent">
        TradeAgent
      </span>
      <span style="font-size:0.72rem;color:#64748b;letter-spacing:0.1em;text-transform:uppercase;font-weight:600">
        AI Trading System
      </span>
    </div>
    <div style="display:flex;align-items:center;gap:16px;margin-top:2px">
      <span style="color:#64748b;font-size:0.8rem">
        Agent <b style="color:#a5b4fc">{provider_label}</b>
      </span>
      <span style="color:#1e293b">·</span>
      <span style="color:#64748b;font-size:0.8rem">
        Loop <b style="color:{_run_color}">{_run_label}</b>
      </span>
      <span style="color:#1e293b">·</span>
      <span style="color:#64748b;font-size:0.8rem;font-family:monospace">
        {time.strftime("%Y-%m-%d  %H:%M")}
      </span>
    </div>
  </div>
</div>
""", unsafe_allow_html=True)

# ── Trending ticker tape (always live, independent of watchlist selection) ──────
_tape_items = _fetch_trending_tape(20)
if _tape_items:
    _tape_html = "".join(
        f'<span class="ticker-item">'
        f'<span class="ticker-sym">{t["sym"]}</span>'
        f'<span class="ticker-price">${t["price"]:,.2f}</span>'
        f'<span class="{"ticker-up" if t["chg"] >= 0 else "ticker-down"}">'
        f'{"▲" if t["chg"] >= 0 else "▼"}{abs(t["chg"]):.2f}%</span>'
        f'</span>'
        for t in _tape_items
    )
    st.markdown(
        f'<div class="ticker-wrap"><div class="ticker-track">{_tape_html * 2}</div></div>',
        unsafe_allow_html=True,
    )

control_state = render_control_deck()
auto_refresh = control_state["auto_refresh"]
watch_source = control_state["watch_source"]
watchlist = control_state["watchlist"]
bar_timeframe = control_state["bar_timeframe"]
sl_pct = control_state["sl_pct"]
tp_pct = control_state["tp_pct"]
run_geo = control_state["run_geo"]
run_earnings = control_state["run_earnings"]
run_macro = control_state["run_macro"]
top_n = control_state["top_n"]

if control_state["shadow_mode"]:
    _mode_label = "Shadow"
elif config.PAPER_TRADING:
    _mode_label = "Paper"
else:
    _mode_label = "Live"

focus_chips([
    ("Watchlist", f"{watch_source.replace('_', ' ').title()} · {len(watchlist)} names"),
    ("Timeframe", bar_timeframe),
    ("Risk", f"SL {sl_pct*100:.0f}% / TP {tp_pct*100:.0f}%"),
    ("Mode", f"{_mode_label} · {'Dry Run' if control_state['dry_run_ui'] else 'Active'}"),
    ("Events", f"Geo {'On' if run_geo else 'Off'} · Earnings {'On' if run_earnings else 'Off'}"),
])

# ── Market status ──────────────────────────────────────────────────────────────
try:
    from alpaca.trading.client import TradingClient as _TC
    _clock = _TC(config.ALPACA_API_KEY, config.ALPACA_SECRET_KEY, paper=True).get_clock()
    _is_open     = _clock.is_open
    _next_open   = _clock.next_open.strftime("%Y-%m-%d %H:%M ET")
    _next_close  = _clock.next_close.strftime("%H:%M ET")
    if _is_open:
        st.markdown(
            f'<div class="alert alert-success" style="margin-bottom:12px">'
            f'🟢 <b>Market Open</b> &nbsp;·&nbsp; Closes at <b>{_next_close}</b>'
            f'</div>',
            unsafe_allow_html=True,
        )
    else:
        st.markdown(
            f'<div class="alert alert-neutral" style="margin-bottom:12px">'
            f'🔴 <b>Market Closed</b> &nbsp;·&nbsp; Opens <b>{_next_open}</b> &nbsp;·&nbsp; '
            f'No new orders will be placed until then.'
            f'</div>',
            unsafe_allow_html=True,
        )
except Exception:
    pass

# ── Account ────────────────────────────────────────────────────────────────────
try:
    account = broker.get_account()
    dd_state = risk.evaluate_drawdown(account)
    day_state = risk.update_daily_loss_guard(account)
    peak = dd_state["peak_equity"]
    drawdown = dd_state["drawdown_pct"] * 100

    if dd_state["halted"]:
        alert("danger", f"MAX DRAWDOWN HALT ACTIVE — {drawdown:.2f}% from peak ${peak:,.2f}.")
    if day_state["halted"]:
        alert("danger", f"DAILY LOSS STOP ACTIVE — {day_state['daily_loss_pct']*100:.2f}% vs open.")

    if config.PAPER_TRADING and account["equity"] < 1000:
        st.warning(
            "⚠️ Paper account equity is very low. "
            "To reset to $100,000: go to **alpaca.markets → Paper Account → Reset** "
            "or close all positions below.",
            icon=None,
        )

except Exception as e:
    st.error(f"Failed to load account: {e}"); st.stop()

# ── Daily summary + live equity curve ─────────────────────────────────────────
try:
    _today = time.strftime("%Y-%m-%d")
    if getattr(config, "SHADOW_MODE", False):
        _shadow = shadow_book.summary()
        _orders_all = []
        _today_trades = [t for t in _shadow["closed_trades"] if str(t.get("exit_time", "")).startswith(_today)]
        _today_pnl = sum(float(t.get("pnl", 0)) for t in _today_trades)
        _today_wins = sum(1 for t in _today_trades if float(t.get("pnl", 0)) > 0)
        _today_losses = sum(1 for t in _today_trades if float(t.get("pnl", 0)) <= 0)
    else:
        _orders_all = broker.get_orders(limit=50)
        _today_orders = [o for o in _orders_all if o.get("time", "").startswith(_today) and o.get("status") == "FILLED"]
        _buys_today: dict = {}
        _today_pnl = 0.0
        _today_wins = 0
        _today_losses = 0
        for o in reversed(_today_orders):
            if o["side"] == "BUY":
                _buys_today[o["symbol"]] = o
            elif o["side"] == "SELL" and o["symbol"] in _buys_today:
                _b = _buys_today.pop(o["symbol"])
                if o["filled_avg"] and _b["filled_avg"]:
                    _pnl = (o["filled_avg"] - _b["filled_avg"]) * (o.get("filled_qty") or 1)
                    _today_pnl += _pnl
                    if _pnl >= 0:
                        _today_wins += 1
                    else:
                        _today_losses += 1

    _total_today_trades = _today_wins + _today_losses
    _win_rate_today = (_today_wins / _total_today_trades * 100) if _total_today_trades else 0.0

    _mode_label = "SHADOW" if getattr(config, "SHADOW_MODE", False) else ("ON" if config.DRY_RUN else "OFF")
    focus_chips([
        ("Portfolio", f"${account['portfolio_value']:,.0f}"),
        ("Cash", f"${account['cash']:,.0f}"),
        ("Buying Power", f"${account['buying_power']:,.0f}"),
        ("Today", f"${_today_pnl:+,.2f}"),
        ("Trades", str(_total_today_trades)),
        ("Win Rate", f"{_win_rate_today:.0f}%" if _total_today_trades else "—"),
        ("Execution", _mode_label),
    ])

    _live_fig = charts.live_equity_curve(_orders_all) if _orders_all else None
except Exception:
    _live_fig = None
    pass

# ── Workspace ──────────────────────────────────────────────────────────────────
section("Workspace", "#615fff")
_panel_options = ["Overview", "Charts", "Positions", "Orders", "Events", "Backtest", "Watchlist", "Alerts", "Journal", "Log"]
_saved_panel = settings_store.get("dashboard_panel", "Overview")
if _saved_panel not in _panel_options:
    _saved_panel = "Overview"
active_panel = st.radio(
    "Panel",
    _panel_options,
    index=_panel_options.index(_saved_panel),
    horizontal=True,
    label_visibility="collapsed",
)
if active_panel != _saved_panel:
    settings_store.save({"dashboard_panel": active_panel})


def render_overview_panel():
    if not watchlist:
        alert("neutral", "No symbols in watchlist.")
        return

    render_screener_snapshot(watch_source, top_n)
    _ov_left, _ov_right = st.columns([3, 1])
    with _ov_right:
        run_agent_scan = st.toggle(
            f"Agent scan ({provider_label})",
            value=False,
            key="ov_agent_scan",
            help="Run LLM approval check on every BUY/SELL signal. Slower but fills the Agent column.",
            disabled=not config.USE_AGENT,
        )
    signal_cache, signal_rows = build_signal_snapshot(watchlist, bar_timeframe, run_agent=run_agent_scan)
    if not signal_rows:
        alert("neutral", "No symbols in watchlist.")
        return

    _buys = sum(1 for r in signal_rows if r["Signal"] == "BUY")
    _sells = sum(1 for r in signal_rows if r["Signal"] == "SELL")
    _holds = sum(1 for r in signal_rows if r["Signal"] == "HOLD")
    focus_chips([
        ("Signals", f"{_buys} buy · {_sells} sell · {_holds} hold"),
        ("Universe", f"{len(signal_rows)} symbols"),
        ("Focus", sorted(signal_rows, key=lambda r: abs(r['Score']), reverse=True)[0]["Symbol"]),
    ])

    left, right = st.columns([1.05, 1.35], gap="large")
    with left:
        section("Signal Board", "#34d399")
        html_table(signal_rows, max_height=480)

    with right:
        section("Focused Symbol", "#38bdf8")
        _sorted_syms = sorted([r for r in signal_rows if r["Signal"] != "ERROR"], key=lambda r: abs(r["Score"]), reverse=True)
        _default_sym = _sorted_syms[0]["Symbol"] if _sorted_syms else watchlist[0]
        _sym_index = watchlist.index(_default_sym) if _default_sym in watchlist else 0
        detail_sym = st.selectbox(
            "Select symbol for details",
            watchlist,
            index=_sym_index,
            key="detail_sym",
            label_visibility="collapsed",
        )

        try:
            _bars = broker.get_bars(detail_sym, timeframe=bar_timeframe)
            _sig = signal_cache.get(detail_sym) or strategy.compute_signals(_bars)
            _rsi_val = _sig.get("rsi")
            _price_val = _sig.get("price")

            _d1, _d2, _d3, _d4, _d5 = st.columns(5)
            _d1.metric("Price", f"${_price_val:,.2f}" if _price_val else "—")
            _d2.metric("Score", f"{_sig['score']:+d}")
            _d3.metric("RSI", f"{_rsi_val:.1f}" if _rsi_val else "—")
            _d4.metric("Signal", _sig["signal"].upper())
            _d5.metric("Regime", str(_sig.get("regime", "range")).replace("_", " ").title())

            st.markdown(
                f'<div style="background:#0f172b;border:1px solid #1e293b;border-left:3px solid #38bdf8;'
                f'border-radius:8px;padding:10px 16px;color:#94a3b8;font-size:0.85rem;margin:4px 0 12px 0">'
                f'{_sig["reason"]}</div>',
                unsafe_allow_html=True,
            )

            _fig = charts.candlestick(_bars, detail_sym, _sig)
            _fig.update_layout(height=380, margin=dict(l=16, r=16, t=40, b=18))
            st.plotly_chart(_fig, use_container_width=True)

            _agent_col1, _agent_col2 = st.columns([3, 1])
            with _agent_col2:
                _ask_agent = st.button(f"Ask {provider_label}", key="detail_ask_agent", type="primary", use_container_width=True)
            with _agent_col1:
                if _ask_agent:
                    with st.spinner(f"{provider_label} analysing {detail_sym}..."):
                        _ar = agent.evaluate_signal(detail_sym, _sig)
                        _approved, _reason = _ar["approved"], _ar["reason"]
                    if _approved:
                        alert("success", f"Approved: {_reason}")
                    else:
                        alert("danger", f"Rejected: {_reason}")
                else:
                    st.caption("Use the agent button for a quick qualitative check on the focused symbol.")

            if _live_fig:
                with st.expander("Live Equity Curve", expanded=False):
                    _mini_fig = go.Figure(_live_fig)
                    _mini_fig.update_layout(height=240, margin=dict(l=16, r=16, t=30, b=12))
                    st.plotly_chart(_mini_fig, use_container_width=True)
        except Exception as _e:
            alert("danger", f"Detail panel error: {_e}")


def render_charts_panel():
    if not watchlist:
        alert("neutral", "No symbols in watchlist.")
        return
    section("Chart Studio", "#38bdf8")
    col1, col2 = st.columns([2, 1])
    with col1:
        chart_symbol = st.selectbox("Symbol", watchlist, key="chart_sym", label_visibility="collapsed")
    with col2:
        chart_tf = st.selectbox("Timeframe", ["1Min", "5Min", "15Min", "1Hour", "1Day"], index=["1Min", "5Min", "15Min", "1Hour", "1Day"].index(bar_timeframe), key="chart_tf", label_visibility="collapsed")

    with st.spinner(f"Loading {chart_symbol} bars..."):
        try:
            bars = broker.get_bars(chart_symbol, timeframe=chart_tf)
            sig = strategy.compute_signals(bars)
            fig = charts.candlestick(bars, chart_symbol, sig)
            fig.update_layout(height=440, margin=dict(l=16, r=16, t=40, b=18))
            st.plotly_chart(fig, use_container_width=True)
            if bars:
                last = bars[-1]
                prev = bars[-2]["c"] if len(bars) > 1 else last["c"]
                chg = ((last["c"] - prev) / prev) * 100
                r1, r2, r3, r4 = st.columns(4)
                r1.metric("Last", f"${last['c']:,.2f}", f"{chg:+.2f}%")
                r2.metric("High", f"${last['h']:,.2f}")
                r3.metric("Low", f"${last['l']:,.2f}")
                r4.metric("Volume", f"{last['v']:,.0f}")
        except Exception as e:
            alert("danger", f"Chart error: {e}")

    if _live_fig:
        with st.expander("Portfolio Equity Curve", expanded=False):
            _chart_fig = go.Figure(_live_fig)
            _chart_fig.update_layout(height=260, margin=dict(l=16, r=16, t=30, b=12))
            st.plotly_chart(_chart_fig, use_container_width=True)


def render_positions_panel():
    section("Open Positions", "#38bdf8")
    try:
        if getattr(config, "SHADOW_MODE", False):
            positions = []
            for p in shadow_book.summary()["open_positions"]:
                _entry = float(p["entry_price"])
                _bars = broker.get_bars(p["symbol"])
                _current = float(_bars[-1]["c"]) if _bars else _entry
                _qty = float(p["qty"])
                _side = p.get("side", "long")
                _pnl = (_current - _entry) * _qty if _side == "long" else (_entry - _current) * _qty
                _pnl_pct = (_pnl / (_entry * _qty)) if _entry > 0 and _qty > 0 else 0.0
                positions.append({"symbol": p["symbol"], "qty": _qty, "side": _side, "avg_entry": _entry, "current_price": _current, "unrealized_pnl": _pnl, "unrealized_pnl_pct": _pnl_pct})
        else:
            positions = broker.get_positions()
        if positions:
            total_pnl = sum(p["unrealized_pnl"] for p in positions)
            p1, p2, p3 = st.columns(3)
            p1.metric("Open Positions", len(positions))
            p2.metric("Total Unr. P&L", f"${total_pnl:+,.2f}")
            p3.metric("SL / TP", f"{sl_pct*100:.0f}% / {tp_pct*100:.0f}%")
            rows = []
            for p in positions:
                sl_price = p["avg_entry"] * (1 - sl_pct) if sl_pct > 0 else "—"
                tp_price = p["avg_entry"] * (1 + tp_pct) if tp_pct > 0 else "—"
                rows.append({
                    "symbol": p["symbol"],
                    "side": p.get("side", "long").upper(),
                    "qty": p["qty"],
                    "avg_entry": f"${p['avg_entry']:,.2f}",
                    "current_price": f"${p['current_price']:,.2f}",
                    "unrealized_pnl": f"${p['unrealized_pnl']:+,.2f}",
                    "unrealized_pnl_pct": f"{p['unrealized_pnl_pct']*100:+.2f}%",
                    "stop_loss": f"${sl_price:,.2f}" if sl_price != "—" else "—",
                    "take_profit": f"${tp_price:,.2f}" if tp_price != "—" else "—",
                })
            html_table(rows, max_height=460)
        else:
            alert("neutral", "No open positions.")
    except Exception as e:
        st.error(f"Failed to load positions: {e}")


def render_orders_panel():
    section("Orders & Fills", "#f59e0b")
    try:
        if getattr(config, "SHADOW_MODE", False):
            summary = shadow_book.summary()
            closed = summary["closed_trades"]
            intents = summary["intents"]
            st.metric("Shadow Realized P&L", f"${summary['realized_pnl']:+,.2f}")
            if closed:
                section("Closed Shadow Trades", "#64748b")
                rows = [{
                    "symbol": t["symbol"],
                    "side": t["side"].upper(),
                    "qty": t["qty"],
                    "entry": f"${t['entry_price']:,.2f}",
                    "exit": f"${t['exit_price']:,.2f}",
                    "pnl": f"${t['pnl']:+,.2f}",
                    "pnl_pct": f"{t['pnl_pct']:+.2f}%",
                    "exit_reason": t.get("close_reason", ""),
                    "exit_time": str(t.get("exit_time", ""))[:19].replace("T", " "),
                } for t in reversed(closed[-50:])]
                html_table(rows, max_height=260)
            if intents:
                with st.expander("Shadow Intents", expanded=False):
                    rows = [{
                        "time": str(i.get("time", ""))[:19].replace("T", " "),
                        "symbol": i["symbol"],
                        "action": i["action"].upper(),
                        "qty": i["qty"],
                        "price": f"${float(i['price']):,.2f}",
                        "score": i.get("score", 0),
                    } for i in reversed(intents[-50:])]
                    html_table(rows, max_height=340)
        else:
            orders = broker.get_orders(limit=30)
            if not orders:
                alert("neutral", "No recent orders.")
                return

            buys = {}
            realized = []
            for o in reversed(orders):
                if o["status"] != "FILLED":
                    continue
                if o["side"] == "BUY":
                    buys[o["symbol"]] = o
                elif o["side"] == "SELL" and o["symbol"] in buys:
                    b = buys.pop(o["symbol"])
                    pnl = (o["filled_avg"] - b["filled_avg"]) * o["filled_qty"] if o["filled_avg"] and b["filled_avg"] else 0
                    realized.append({"Symbol": o["symbol"], "Buy": f"${b['filled_avg']:,.2f}", "Sell": f"${o['filled_avg']:,.2f}", "Qty": o["filled_qty"], "Realized P&L": f"${pnl:+,.2f}"})

            if realized:
                total_realized = sum(float(r["Realized P&L"].replace("$", "").replace(",", "")) for r in realized)
                st.metric("Total Realized P&L", f"${total_realized:+,.2f}")
                html_table(realized, max_height=240)

            section("All Orders", "#64748b")
            for o in orders:
                o["side"] = o["side"].upper()
                o["filled_avg"] = f"${o['filled_avg']:,.2f}" if o["filled_avg"] else "—"
                o["value"] = f"${o['value']:,.2f}" if o["value"] else "—"
            html_table(orders, max_height=380)
    except Exception as e:
        st.error(f"Failed to load orders: {e}")


def render_events_panel():
    if not watchlist:
        alert("neutral", "No symbols in watchlist.")
        return
    section("News & Event Flow", "#f59e0b")
    ev_c1, ev_c2 = st.columns([2, 1])
    with ev_c1:
        event_symbol = st.selectbox("Symbol", watchlist, key="event_sym", label_visibility="collapsed")
    with ev_c2:
        ev_news_n = st.slider("Headlines", 5, 20, 10, key="ev_news_n")

    try:
        _news = events.fetch_news(symbols=[event_symbol], limit=ev_news_n)
        _news_rows = [{
            "Time": n["created"][:16].replace("T", " ") if n["created"] else "—",
            "Source": n["source"] or "—",
            "Headline": n["headline"],
        } for n in _news if n["headline"] and "[news fetch error" not in n["headline"]]
        if _news_rows:
            html_table(_news_rows, max_height=280)
        else:
            alert("neutral", "No recent news found for this symbol.")
    except Exception as _e:
        alert("danger", f"News fetch error: {_e}")

    try:
        _eq_news = events.fetch_news(symbols=[event_symbol], keywords="earnings EPS guidance", limit=5)
        _has_earnings = any(any(kw in n["headline"].lower() for kw in ("earnings", "eps", "guidance", "beat", "miss")) for n in _eq_news if n["headline"] and "[news fetch error" not in n["headline"])
        if _has_earnings:
            st.markdown('<div class="alert alert-info" style="margin:8px 0">Earnings activity detected — event analysis recommended</div>', unsafe_allow_html=True)
    except Exception:
        pass

    section("LLM Event Analysis", "#a78bfa")
    if not config.USE_AGENT:
        alert("info", "Set AGENT_PROVIDER=claude or openai in .env to enable LLM event analysis.")
    else:
        if st.button(f"Analyse with {provider_label}", key="events_agent", type="primary"):
            with st.spinner(f"{provider_label} scoring headlines..."):
                ev_result = events.get_event_score(event_symbol, run_earnings=run_earnings, run_geo=run_geo, run_macro=run_macro)
            try:
                _event_bars = broker.get_bars(event_symbol, timeframe=bar_timeframe)
                quant = strategy.compute_signals(_event_bars)
            except Exception:
                quant = {"score": 0, "reason": "no quant data", "signal": "hold", "rsi": None, "price": None, "atr": None, "event_score": 0, "event_reasons": []}
            combined = strategy.apply_event_score(quant, ev_result)
            m1, m2, m3 = st.columns(3)
            m1.metric("Quant Score", quant["score"])
            m2.metric("Event Score", ev_result["event_score"])
            m3.metric("Combined Score", combined["score"])
            for sig in ev_result["signals"]:
                event_card(sig["event_type"].capitalize(), sig["score"], sig.get("confidence", "—"), sig["reason"])
            if combined["signal"] == "buy":
                alert("success", f"BUY — {combined['reason']}")
            elif combined["signal"] == "sell":
                alert("danger", f"SELL — {combined['reason']}")
            else:
                alert("neutral", f"HOLD — {combined['reason']}")


def render_backtest_panel():
    if not watchlist:
        alert("neutral", "No symbols in watchlist.")
        return
    section("Backtest Studio", "#a78bfa")
    bl, bm, bn, br = st.columns([2, 1, 1, 1])
    with bl:
        bt_symbol = st.selectbox("Symbol", watchlist, key="bt_sym", label_visibility="collapsed")
    with bm:
        bt_tf = st.selectbox("Timeframe", ["1Min", "5Min", "15Min", "1Hour", "1Day"], index=4, key="bt_tf", label_visibility="collapsed")
    with bn:
        _bt_lookback_opts = {"5d": 5, "20d": 20, "60d": 60, "180d": 180, "1y": 365, "2y": 730}
        bt_lookback_label = st.selectbox("Lookback", list(_bt_lookback_opts.keys()), index=5, key="bt_lookback", label_visibility="collapsed")
        bt_lookback_days = _bt_lookback_opts[bt_lookback_label]
    with br:
        run_bt = st.button("Run Backtest", type="primary", use_container_width=True)

    if run_bt:
        with st.spinner(f"Backtesting {bt_symbol} · {bt_tf} · {bt_lookback_label}..."):
            result = backtest.run(bt_symbol, timeframe=bt_tf, lookback_days=bt_lookback_days)
        if "error" in result:
            alert("danger", result["error"])
            st.caption("Tip: Alpaca free tier limits intraday history. Try 1Day timeframe with 1y or 2y lookback.")
        else:
            c1, c2, c3, c4 = st.columns(4)
            c1.metric("Total Return", f"{result['total_return_pct']:+.2f}%")
            c2.metric("Sharpe Ratio", result["sharpe"])
            c3.metric("Max Drawdown", f"{result['max_drawdown_pct']:.2f}%")
            c4.metric("Win Rate", f"{result['win_rate_pct']:.1f}%")
            c5, c6, c7, c8 = st.columns(4)
            c5.metric("Total Trades", result["total_trades"])
            c6.metric("Profit Factor", result["profit_factor"])
            c7.metric("Avg Win", f"${result['avg_win']:,.2f}")
            c8.metric("Avg Loss", f"${result['avg_loss']:,.2f}")

            if result["equity_curve"]:
                fig = charts.equity_curve(result["equity_curve"], benchmark_records=result.get("benchmark"), trades=result.get("trades"))
                fig.update_layout(height=320, margin=dict(l=16, r=16, t=40, b=18))
                st.plotly_chart(fig, use_container_width=True)

            if result["trades"]:
                _display_trades = [{k: v for k, v in t.items() if k not in ("entry_date", "exit_date")} for t in result["trades"]]
                html_table(_display_trades, max_height=320)

    with st.expander("Walk-Forward Validation", expanded=False):
        st.caption("Splits data into folds and checks out-of-sample performance.")
        wf_c1, wf_c2, wf_c3 = st.columns([2, 1, 1])
        with wf_c1:
            wf_sym = st.selectbox("Symbol", watchlist, key="wf_sym", label_visibility="collapsed")
        with wf_c2:
            wf_tf = st.selectbox("Timeframe", ["1Day", "1Hour"], key="wf_tf", label_visibility="collapsed")
        with wf_c3:
            run_wf = st.button("Walk-Forward", type="primary", use_container_width=True)
        if run_wf:
            with st.spinner(f"Running 5-fold walk-forward on {wf_sym}..."):
                wf = backtest.walk_forward(wf_sym, timeframe=wf_tf)
            if "error" in wf:
                alert("danger", wf["error"])
            else:
                wf_m1, wf_m2, wf_m3, wf_m4 = st.columns(4)
                wf_m1.metric("Avg OOS Return", f"{wf['avg_return_pct']:+.2f}%")
                wf_m2.metric("Avg Sharpe", wf["avg_sharpe"])
                wf_m3.metric("Avg Win Rate", f"{wf['avg_win_rate']:.1f}%")
                wf_m4.metric("Profitable Folds", wf["profitable_folds"])
                html_table([{k: v for k, v in f.items() if k != "folds"} for f in wf["folds"]], max_height=260)

    with st.expander("Parameter Optimisation", expanded=False):
        st.caption("Searches threshold, stop loss, and take profit combinations ranked by Sharpe ratio.")
        opt_c1, opt_c2 = st.columns([3, 1])
        with opt_c1:
            opt_sym = st.selectbox("Symbol", watchlist, key="opt_sym", label_visibility="collapsed")
        with opt_c2:
            run_opt = st.button("Optimise", type="primary", use_container_width=True)
        if run_opt:
            with st.spinner(f"Grid searching {opt_sym}..."):
                opt = backtest.optimize(opt_sym)
            if "error" in opt:
                alert("danger", opt["error"])
            else:
                best = opt["best"]
                alert("success", f"Best: threshold={best['threshold']} · SL={best['sl_pct']} · TP={best['tp_pct']} · Sharpe {best['sharpe']}")
                html_table(opt["results"], max_height=320)


def render_watchlist_panel():
    section("Watchlist Manager", "#34d399")
    _wl_all = watchlist_store.load()
    if _wl_all:
        html_table([{"Symbol": s} for s in _wl_all], max_height=320)
    else:
        alert("neutral", "Watchlist is empty — add symbols below.")

    wl1, wl2 = st.columns(2)
    with wl1:
        st.markdown("**Add symbol**")
        new_sym = st.text_input("Ticker", placeholder="e.g. AAPL", label_visibility="collapsed").upper().strip()
        if st.button("Add Symbol", type="primary", use_container_width=True) and new_sym:
            watchlist_store.add(new_sym)
            st.success(f"Added {new_sym}")
            st.rerun()
    with wl2:
        st.markdown("**Remove symbol**")
        if _wl_all:
            rm_sym = st.selectbox("Symbol to remove", _wl_all, label_visibility="collapsed")
            if st.button("Remove Symbol", use_container_width=True):
                watchlist_store.remove(rm_sym)
                st.success(f"Removed {rm_sym}")
                st.rerun()
        else:
            st.caption("Nothing to remove.")


def render_alerts_panel():
    section("Alert Configuration", "#f87171")
    st.caption("Set these in your .env file — no code changes needed.")
    a1, a2, a3 = st.columns(3)
    with a1:
        st.markdown("**Email**")
        st.code("""ALERT_EMAIL_TO=you@gmail.com
ALERT_SMTP_HOST=smtp.gmail.com
ALERT_SMTP_PORT=465
ALERT_SMTP_USER=you@gmail.com
ALERT_SMTP_PASS=app_password""", language="bash")
        st.markdown(f"Status: {'Configured' if bool(config.ALERT_EMAIL_TO) else 'Not configured'}")
    with a2:
        st.markdown("**Slack**")
        st.code("ALERT_SLACK_WEBHOOK=https://hooks.slack.com/...", language="bash")
        st.markdown(f"Status: {'Configured' if bool(config.ALERT_SLACK_WEBHOOK) else 'Not configured'}")
    with a3:
        st.markdown("**Telegram**")
        st.code("""ALERT_TELEGRAM_TOKEN=your_bot_token
ALERT_TELEGRAM_CHAT_ID=your_chat_id""", language="bash")
        st.markdown(f"Status: {'Configured' if bool(config.ALERT_TELEGRAM_TOKEN) else 'Not configured'}")

    if st.button("Send Test Alert", type="primary"):
        try:
            import alerts as alert_module
            alert_module.send("Test Alert", "TradeAgent alert system is working correctly.")
            alert("success", "Test alert sent to all configured channels.")
        except Exception as e:
            alert("danger", f"Alert failed: {e}")


def render_journal_panel():
    section("Trade Journal", "#a78bfa")
    try:
        stats = trade_journal.get_stats()
        if stats.get("total_decisions", 0) == 0:
            alert("neutral", "No journal entries yet — run main.py to start recording decisions.")
            return

        # ── Summary metrics ────────────────────────────────────────────────────
        j1, j2, j3, j4, j5 = st.columns(5)
        j1.metric("Total Decisions", stats["total_decisions"])
        j2.metric("Approved", stats["approved"])
        j3.metric("Rejected", stats["rejected"])
        j4.metric("Approval Rate", f"{stats['approval_rate']*100:.0f}%")
        win_rate_val = stats.get("win_rate", 0)
        j5.metric(
            "Win Rate",
            f"{win_rate_val*100:.0f}%" if stats.get("total_outcomes", 0) > 0 else "—",
            help="Closed trades only — needs log_outcome entries",
        )

        # ── Recent decisions ───────────────────────────────────────────────────
        import json, os
        _jfile = os.path.join(os.path.dirname(__file__), "trade_journal.json") if False else "trade_journal.json"
        try:
            with open(_jfile) as _f:
                _records = json.load(_f)
        except Exception:
            _records = []

        decisions = [r for r in _records if r.get("type") == "decision"]
        outcomes  = [r for r in _records if r.get("type") == "outcome"]

        if decisions:
            section("Recent Decisions", "#64748b")
            dec_rows = []
            for d in reversed(decisions[-50:]):
                dec_rows.append({
                    "Time":     d.get("time", "")[:16].replace("T", " "),
                    "Symbol":   d.get("symbol", ""),
                    "Action":   d.get("action", "").upper(),
                    "Decision": "APPROVE" if d.get("approved") else "REJECT",
                    "Score":    d.get("score", 0),
                    "Sentiment":f"{d.get('sentiment', 0):+d}",
                    "Size":     f"x{d.get('size_multiplier', 1.0):.1f}",
                    "Macro":    "YES" if d.get("macro_day") else "—",
                    "Reason":   d.get("reason", ""),
                })
            html_table(dec_rows, max_height=380)

        if outcomes:
            section("Closed Trades (Outcomes)", "#64748b")
            out_rows = []
            total_pnl = 0.0
            for o in reversed(outcomes[-50:]):
                pnl = float(o.get("pnl", 0))
                total_pnl += pnl
                out_rows.append({
                    "Time":       o.get("time", "")[:16].replace("T", " "),
                    "Symbol":     o.get("symbol", ""),
                    "Entry":      f"${float(o.get('entry_price', 0)):,.2f}",
                    "Exit":       f"${float(o.get('exit_price', 0)):,.2f}",
                    "P&L":        f"${pnl:+,.2f}",
                    "Exit Reason": o.get("exit_reason", ""),
                })
            _oc1, _oc2 = st.columns(2)
            _oc1.metric("Total Closed P&L", f"${total_pnl:+,.2f}")
            _oc2.metric("Trades Logged", len(outcomes))
            html_table(out_rows, max_height=340)
        elif decisions:
            alert("neutral", "No closed-trade outcomes yet — will appear after first stop-loss or take-profit.")

    except Exception as _je:
        st.error(f"Journal error: {_je}")


def render_log_panel():
    section("Trade Log", "#64748b")
    try:
        with open("trade.log") as f:
            lines = f.readlines()
        log_lc, log_rc = st.columns([3, 1])
        with log_lc:
            log_filter = st.selectbox("Level", ["ALL", "ERROR", "WARNING", "INFO"], label_visibility="collapsed", key="log_level")
        with log_rc:
            log_lines = st.slider("Lines", 20, 200, 60, key="log_lines_n")

        _level_colors = {"ERROR": "#f87171", "WARNING": "#f59e0b", "INFO": "#94a3b8", "DEBUG": "#64748b"}
        _level_bg = {"ERROR": "#2d0a0a22", "WARNING": "#2d1a0022", "INFO": "", "DEBUG": ""}
        filtered = [l for l in lines if log_filter == "ALL" or f"[{log_filter}]" in l]
        display = filtered[-log_lines:]
        html_lines = []
        for line in display:
            line = line.rstrip()
            level = "INFO"
            for lvl in ("ERROR", "WARNING", "INFO", "DEBUG"):
                if f"[{lvl}]" in line:
                    level = lvl
                    break
            color = _level_colors.get(level, "#cbd5e1")
            bg = _level_bg.get(level, "")
            bg_style = f"background:{bg};" if bg else ""
            html_lines.append(f'<div style="{bg_style}padding:2px 8px;font-family:monospace;font-size:0.78rem;color:{color};border-left:2px solid {color}33;margin-bottom:1px">{line}</div>')

        st.markdown('<div style="background:#0a0f1e;border:1px solid #1e293b;border-radius:8px;padding:8px;max-height:520px;overflow-y:auto">' + "".join(html_lines) + "</div>", unsafe_allow_html=True)
    except FileNotFoundError:
        alert("neutral", "No trade.log yet — run main.py to start logging.")


if active_panel == "Overview":
    render_overview_panel()
elif active_panel == "Charts":
    render_charts_panel()
elif active_panel == "Positions":
    render_positions_panel()
elif active_panel == "Orders":
    render_orders_panel()
elif active_panel == "Events":
    render_events_panel()
elif active_panel == "Backtest":
    render_backtest_panel()
elif active_panel == "Watchlist":
    render_watchlist_panel()
elif active_panel == "Alerts":
    render_alerts_panel()
elif active_panel == "Journal":
    render_journal_panel()
elif active_panel == "Log":
    render_log_panel()

# ── Auto-refresh ───────────────────────────────────────────────────────────────
if auto_refresh:
    time.sleep(30)
    st.rerun()
