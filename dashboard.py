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
    color:#94a3b8; margin:28px 0 14px 0; padding-bottom:8px; border-bottom:1px solid #1e293b;
}
.section-dot { width:6px; height:6px; border-radius:50%; display:inline-block; }

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

[data-testid="stSidebar"] { background:linear-gradient(180deg,#0f172b 0%,#1e1b4b 100%) !important; border-right:1px solid #3730a3; }
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

/* ── Sidebar inputs ── */
[data-testid="stSidebar"] [data-testid="stSelectbox"] > div > div,
[data-testid="stSidebar"] [data-testid="stNumberInput"] input,
[data-testid="stSidebar"] [data-testid="stTextInput"] input {
    background: #0f172b !important;
    border: 1px solid #334155 !important;
    border-radius: 8px !important;
    color: #e2e8f0 !important;
    font-size: 0.83rem !important;
}
[data-testid="stSidebar"] [data-testid="stSelectbox"] > div > div:focus-within,
[data-testid="stSidebar"] [data-testid="stTextInput"] input:focus {
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

def event_card(label, score, confidence, reason):
    if score > 0:   cls, icon, color = "bullish", "▲", "#34d399"
    elif score < 0: cls, icon, color = "bearish", "▼", "#f87171"
    else:           cls, icon, color = "neutral",  "●", "#64748b"
    st.markdown(f"""<div class="event-card {cls}">
        <span style="color:{color};font-weight:700;font-size:0.9rem">{icon} {label}</span>
        &nbsp;<span style="color:#64748b;font-size:0.78rem">score <b style="color:{color}">{score:+d}</b> &nbsp;·&nbsp; confidence <b style="color:#a5b4fc">{confidence}</b></span>
        <div style="color:#cbd5e1;font-size:0.83rem;margin-top:6px;line-height:1.4">{reason}</div>
    </div>""", unsafe_allow_html=True)

_SIGNAL_BADGES = {
    "BUY":  '<td><span style="background:#052e16;color:#34d399;border:1px solid #059669;padding:2px 12px;border-radius:20px;font-size:0.75rem;font-weight:700">▲ BUY</span></td>',
    "SELL": '<td><span style="background:#2d0a0a;color:#f87171;border:1px solid #dc2626;padding:2px 12px;border-radius:20px;font-size:0.75rem;font-weight:700">▼ SELL</span></td>',
    "HOLD": '<td><span style="background:#1e293b;color:#94a3b8;border:1px solid #334155;padding:2px 12px;border-radius:20px;font-size:0.75rem;font-weight:700">● HOLD</span></td>',
}
_STATUS_COLORS = {"FILLED":"#34d399","CANCELED":"#f87171","PENDING_NEW":"#f59e0b","NEW":"#f59e0b","PARTIALLY_FILLED":"#a5b4fc","REJECTED":"#f87171"}

def _cell_score(v):
    try:
        n = float(v)
        if n > 0:   color, prefix = "#34d399", "+"
        elif n < 0: color, prefix = "#f87171", ""
        else:       color, prefix = "#64748b", ""
        return f'<td style="color:{color};font-weight:700;text-align:center">{prefix}{int(n)}</td>'
    except Exception:
        return f'<td>{v}</td>'

def _cell_pnl(v):
    s = str(v)
    color = "#34d399" if not s.startswith("-") else "#f87171"
    return f'<td style="color:{color};font-weight:600;font-family:monospace">{s}</td>'

def _cell_rsi(v):
    try:
        n = float(v)
        if n > 65:
            color = "#f87171"
        elif n < 35:
            color = "#34d399"
        else:
            color = "#e2e8f0"
        return f'<td style="color:{color}">{v}</td>'
    except Exception:
        return f'<td>{v}</td>'

def _cell_pct(v):
    try:
        n = float(v)
        color = "#34d399" if n >= 0 else "#f87171"
        arrow = "▲" if n >= 0 else "▼"
        return f'<td style="color:{color};font-weight:600">{arrow} {abs(n):.2f}%</td>'
    except Exception:
        return f'<td>{v}</td>'

_CELL_DISPATCH = {
    "Signal":   lambda v,s: _SIGNAL_BADGES.get(s, f'<td style="color:#f87171">{s}</td>'),
    "Score":    lambda v,s: _cell_score(v),
    "side":     lambda v,s: f'<td><span style="color:{"#34d399" if s.upper() in ("BUY","LONG") else "#f87171"};font-weight:700">{s}</span></td>',
    "status":   lambda v,s: f'<td style="color:{_STATUS_COLORS.get(s.upper(),"#94a3b8")};font-weight:600;font-size:0.8rem">{s}</td>',
    "Symbol":   lambda v,s: f'<td style="color:#a5b4fc;font-weight:700;letter-spacing:0.04em">{s}</td>',
    "symbol":   lambda v,s: f'<td style="color:#a5b4fc;font-weight:700;letter-spacing:0.04em">{s}</td>',
    "RSI":      lambda v,s: _cell_rsi(v),
    "Reason":   lambda v,s: f'<td style="color:#94a3b8;font-size:0.8rem;white-space:normal;word-break:break-word;min-width:180px;max-width:360px" title="{s}">{s}</td>',
    "reason":   lambda v,s: f'<td style="color:#94a3b8;font-size:0.8rem;white-space:normal;word-break:break-word;min-width:180px;max-width:360px" title="{s}">{s}</td>',
    "change_pct": lambda v,s: _cell_pct(v),
    "pnl":      lambda v,s: _cell_pnl(v),
    "pnl_pct":  lambda v,s: _cell_pct(v),
    "unrealized_pnl":     lambda v,s: _cell_pnl(v),
    "unrealized_pnl_pct": lambda v,s: _cell_pnl(v),
    "time":     lambda v,s: f'<td style="color:#64748b;font-size:0.8rem;font-family:monospace">{s}</td>',
    "ATR":          lambda _,s: f'<td style="color:#64748b;font-size:0.8rem;font-family:monospace">{s}</td>',
    "Volume":       lambda _,s: f'<td style="color:#94a3b8;font-family:monospace;font-size:0.85rem">{s}</td>',
    "Trade Count":  lambda _,s: f'<td style="color:#94a3b8;font-family:monospace;font-size:0.85rem">{s}</td>',
    "Agent":    lambda v,s: f'<td style="text-align:center" title="{s}"><span style="cursor:help;font-size:1rem">🤖</span></td>' if s not in ("—","") else '<td style="color:#334155;text-align:center">—</td>',
    "Headline": lambda v,s: f'<td style="color:#cbd5e1;font-size:0.82rem;white-space:normal;word-break:break-word;max-width:480px">{s}</td>',
    **{k: (lambda v,s: f'<td style="color:#e2e8f0;font-family:monospace">{s}</td>')
       for k in ["Price","price","avg_entry","current_price","filled_avg","value","entry","exit"]},
}

def html_table(rows):
    if not rows: return
    cols = list(rows[0].keys())
    header = "".join(f'<th style="color:#64748b;font-size:0.68rem;font-weight:700;letter-spacing:0.1em;text-transform:uppercase;padding:10px 14px;border-bottom:1px solid #1e293b;white-space:nowrap">{c}</th>' for c in cols)
    body = ""
    for i, row in enumerate(rows):
        bg = "#0d1424" if i % 2 == 0 else "#0f172b"
        cells = "".join((_CELL_DISPATCH.get(c, lambda v,s: f'<td style="color:#cbd5e1">{s}</td>')(row[c], str(row[c])) for c in cols))
        body += f'<tr style="background:{bg}" onmouseover="this.style.background=\'#1e293b\'" onmouseout="this.style.background=\'{bg}\'">{cells}</tr>'
    st.markdown(f'<div style="border:1px solid #1e293b;border-radius:10px;overflow:hidden;margin-bottom:8px"><table style="width:100%;border-collapse:collapse;font-size:0.85rem"><thead><tr style="background:#0a0f1e">{header}</tr></thead><tbody>{body}</tbody></table></div>', unsafe_allow_html=True)

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


# ── Sidebar ────────────────────────────────────────────────────────────────────
provider = config.AGENT_PROVIDER.upper() if config.USE_AGENT else "NONE"
provider_label = {"CLAUDE":"Claude","OPENAI":"OpenAI","NONE":"No LLM"}.get(provider, provider)

with st.sidebar:
    if getattr(config, "SHADOW_MODE", False):
        mode_color = "#38bdf8"
        mode_label = "Shadow Mode"
        mode_icon  = "◎"
    elif config.PAPER_TRADING:
        mode_color = "#f59e0b"
        mode_label = "Paper Trading"
        mode_icon  = "◈"
    else:
        mode_color = "#ef4444"
        mode_label = "Live Trading"
        mode_icon  = "◆"
    st.markdown(f"""
<div style="padding:20px 4px 16px 4px;border-bottom:1px solid #1e293b;margin-bottom:4px">
  <div style="display:flex;align-items:center;gap:10px;margin-bottom:10px">
    <div style="
        width:38px;height:38px;border-radius:10px;
        background:linear-gradient(135deg,#4f46e5,#06b6d4);
        display:flex;align-items:center;justify-content:center;
        font-size:1.2rem;box-shadow:0 2px 12px #4f46e566;flex-shrink:0">
      ◈
    </div>
    <div>
      <div style="font-size:1.05rem;font-weight:700;color:#e2e8f0;letter-spacing:0.02em;line-height:1.2">TradeAgent</div>
      <div style="font-size:0.68rem;color:#64748b;letter-spacing:0.06em;text-transform:uppercase">AI Trading System</div>
    </div>
  </div>
  <span style="
      display:inline-flex;align-items:center;gap:5px;
      padding:3px 10px;border-radius:20px;font-size:0.7rem;font-weight:700;
      letter-spacing:0.07em;text-transform:uppercase;
      background:{mode_color}18;color:{mode_color};border:1px solid {mode_color}55">
    <span style="font-size:0.55rem">●</span> {mode_label}
  </span>
</div>
""", unsafe_allow_html=True)

    st.markdown("---")
    auto_refresh = st.toggle("Auto-refresh (30s)", value=False)
    if st.button("⟳ Refresh Now", use_container_width=True): st.rerun()

    st.markdown("---")
    st.markdown("**Watchlist**")
    watch_source = st.selectbox("", ["my_list","most_active","gainers","losers","etf"],
        format_func=lambda x: {"my_list":"⭐ My List","most_active":"🔥 Most Active","gainers":"📈 Top Gainers","losers":"📉 Top Losers","etf":"🗂 ETFs"}[x],
        label_visibility="collapsed")

    etf_themes = None
    top_n = 10

    # Seed store with config defaults on first run
    if not watchlist_store.load():
        for _sym in config.WATCHLIST:
            watchlist_store.add(_sym)

    if watch_source == "my_list":
        _my_wl = watchlist_store.load()

        # Add new symbol
        _add_col, _btn_col = st.columns([3, 1])
        with _add_col:
            _new_sym = st.text_input("Add ticker", placeholder="GOOG", label_visibility="collapsed", key="wl_add").upper().strip()
        with _btn_col:
            st.markdown("<div style='margin-top:6px'>", unsafe_allow_html=True)
            if st.button("＋", use_container_width=True, key="wl_add_btn") and _new_sym:
                watchlist_store.add(_new_sym)
                st.rerun()
            st.markdown("</div>", unsafe_allow_html=True)

        # Show current symbols — click × to remove
        for _sym in _my_wl:
            _c1, _c2 = st.columns([4, 1])
            _c1.markdown(f'<div style="padding:4px 0;color:#a5b4fc;font-weight:600;font-size:0.85rem">{_sym}</div>', unsafe_allow_html=True)
            if _c2.button("×", key=f"rm_{_sym}", help=f"Remove {_sym}"):
                watchlist_store.remove(_sym)
                st.rerun()

        watchlist = _my_wl

    elif watch_source == "etf":
        etf_themes = st.multiselect("Themes", options=list(screener.ETF_UNIVERSE.keys()), default=["Broad Market","Tech"])
        watchlist = screener.build_watchlist(watch_source, etf_themes=etf_themes or None)

    else:
        top_n = st.slider("Top N", 5, 25, 10)
        watchlist = screener.build_watchlist(watch_source, top_n=top_n)

    st.caption(f"{len(watchlist)} symbols · {', '.join(watchlist[:5])}{'…' if len(watchlist)>5 else ''}")

    st.markdown("---")
    st.markdown("**Bar Timeframe**")
    bar_timeframe = st.selectbox("", ["1Min","5Min","15Min","1Hour","1Day"],
        index=["1Min","5Min","15Min","1Hour","1Day"].index(config.BAR_TIMEFRAME),
        format_func=lambda x: {"1Min":"1 Min","5Min":"5 Min","15Min":"15 Min","1Hour":"1 Hour","1Day":"1 Day"}[x],
        label_visibility="collapsed")

    st.markdown("---")
    st.markdown("**Risk Settings**")
    _saved_settings = settings_store.load()
    _sl_default = int(_saved_settings.get("sl_pct", config.STOP_LOSS_PCT) * 100)
    _tp_default = int(_saved_settings.get("tp_pct", config.TAKE_PROFIT_PCT) * 100)
    _daily_stop_default = int(_saved_settings.get("daily_loss_stop_pct", config.DAILY_LOSS_STOP_PCT) * 100)
    _sector_cap_default = int(_saved_settings.get("max_sector_exposure_pct", config.MAX_SECTOR_EXPOSURE_PCT) * 100)
    _corr_cap_default = bool(_saved_settings.get("enable_correlation_cap", config.ENABLE_CORRELATION_CAP))
    _max_corr_default = max(0.50, min(0.99, float(_saved_settings.get("max_correlation", config.MAX_CORRELATION))))
    _max_corr_positions_default = max(1, min(20, int(_saved_settings.get("max_correlated_positions", config.MAX_CORRELATED_POSITIONS))))
    _corr_lookback_default = max(20, min(365, int(_saved_settings.get("correlation_lookback_days", config.CORRELATION_LOOKBACK_DAYS))))

    sl_pct = st.slider("Stop Loss %",   0, 20, _sl_default) / 100
    tp_pct = st.slider("Take Profit %", 0, 50, _tp_default) / 100
    daily_loss_stop_pct = st.slider("Daily Loss Stop %", 0, 20, _daily_stop_default) / 100
    max_sector_exposure_pct = st.slider("Sector Cap %", 0, 100, _sector_cap_default) / 100

    st.markdown("**Correlation Controls**")
    enable_correlation_cap = st.toggle("Enable Correlation Cap", value=_corr_cap_default)
    max_correlation = st.slider("Max Correlation", 0.50, 0.99, _max_corr_default, 0.01)
    max_correlated_positions = st.number_input(
        "Max Correlated Holdings",
        min_value=1,
        max_value=20,
        value=_max_corr_positions_default,
        step=1,
    )
    correlation_lookback_days = st.slider("Correlation Lookback (days)", 20, 365, _corr_lookback_default, 5)

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

    st.caption(
        f"Sector cap {max_sector_exposure_pct*100:.0f}% · "
        f"Daily stop {daily_loss_stop_pct*100:.1f}% · "
        f"Corr ≤ {max_correlation:.2f} ({max_correlated_positions} holdings)"
    )

    st.markdown("---")
    st.markdown("**Trading Mode**")
    dry_run_ui  = st.toggle("Dry Run (no orders)", value=config.DRY_RUN)
    shadow_mode = st.toggle("Shadow Mode (simulate outcomes)", value=getattr(config, "SHADOW_MODE", False))
    allow_short = st.toggle("Allow Short Selling", value=config.ALLOW_SHORT)
    if dry_run_ui  != config.DRY_RUN:    settings_store.save({"dry_run": dry_run_ui})
    if shadow_mode != getattr(config, "SHADOW_MODE", False): settings_store.save({"shadow_mode": shadow_mode})
    if allow_short != config.ALLOW_SHORT: settings_store.save({"allow_short": allow_short})

    st.markdown("---")
    st.markdown("**Event Filters**")
    run_geo      = st.toggle("🌍 Geopolitical", value=True)
    run_earnings = st.toggle("📊 Earnings",     value=True)
    run_macro    = st.toggle("🏦 Macro",        value=True)

    st.markdown("---")
    st.markdown("**Manual Order**")
    manual_symbol = st.selectbox("Symbol", watchlist if watchlist else config.WATCHLIST, label_visibility="collapsed")
    manual_qty    = st.number_input("Qty", min_value=1, value=1, step=1, label_visibility="collapsed")
    c1, c2 = st.columns(2)
    with c1:
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
            except Exception as e: st.error(str(e))
    with c2:
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
            except Exception as e: st.error(str(e))
    st.markdown("---")
    st.caption(f"🤖 Agent: **{provider_label}**")

# ── Header ─────────────────────────────────────────────────────────────────────
import os as _os
_log_path = _os.path.join(_os.path.dirname(__file__), "trade.log")
_log_age  = time.time() - _os.path.getmtime(_log_path) if _os.path.exists(_log_path) else float("inf")
_loop_running = _log_age < config.LOOP_INTERVAL_SEC * 2.5

_run_color = "#34d399" if _loop_running else "#64748b"
_run_label = "● Running" if _loop_running else "○ Stopped"

st.markdown(f"""
<div style="display:flex;align-items:center;gap:16px;margin-bottom:6px;padding-bottom:16px;border-bottom:1px solid #1e293b">
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

    c1,c2,c3,c4,c5,c6 = st.columns([1,1,1,1,1,1])
    c1.metric("Portfolio Value", f"${account['portfolio_value']:,.2f}")
    c2.metric("Equity",         f"${account['equity']:,.2f}")
    c3.metric("Cash",           f"${account['cash']:,.2f}")
    c4.metric("Buying Power",   f"${account['buying_power']:,.2f}")
    with c5:
        if st.button("🗑 Close All Positions", use_container_width=True):
            try:
                positions = broker.get_positions()
                for p in positions:
                    broker.close_position(p["symbol"])
                st.success(f"Closed {len(positions)} position(s)")
                st.rerun()
            except Exception as e:
                st.error(str(e))
    with c6:
        if st.button("Reset Risk Halt", use_container_width=True):
            risk.reset_halts(reset_peak=False)
            st.success("Risk halts reset.")
            st.rerun()
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

    _ds1, _ds2, _ds3, _ds4 = st.columns(4)
    _ds1.metric("Today's Trades",    _total_today_trades)
    _ds2.metric("Today's Realized",  f"${_today_pnl:+,.2f}")
    _ds3.metric("Today's Win Rate",  f"{_win_rate_today:.0f}%" if _total_today_trades else "—")
    _mode_label = "SHADOW" if getattr(config, "SHADOW_MODE", False) else ("ON" if config.DRY_RUN else "OFF")
    _ds4.metric("Dry Run", _mode_label)

    # live equity curve from all-time orders
    _live_fig = charts.live_equity_curve(_orders_all) if _orders_all else None
    if _live_fig:
        section("Live P&L Curve", "#34d399")
        st.plotly_chart(_live_fig, use_container_width=True)
except Exception:
    pass

# ── Ticker tape ────────────────────────────────────────────────────────────────
with st.spinner(""):
    ticker_tape(watchlist[:12])

# ── Tabs ───────────────────────────────────────────────────────────────────────
tab_signals, tab_charts, tab_positions, tab_orders, tab_events, tab_backtest, tab_watchlist, tab_alerts_cfg, tab_log = st.tabs([
    "📊 Signals", "🕯 Charts", "💼 Positions", "📋 Orders",
    "🌐 Events", "🔬 Backtest", "📌 Watchlist", "🔔 Alerts", "📄 Log"
])


# ═══════════════════════════════════════════════════════════════════════════════
# TAB 1 — SIGNALS
# ═══════════════════════════════════════════════════════════════════════════════
with tab_signals:
    if watch_source in ("most_active","gainers","losers"):
        label_map = {"most_active":"🔥 Most Active","gainers":"📈 Top Gainers","losers":"📉 Top Losers"}
        color_map = {"most_active":"#f59e0b","gainers":"#34d399","losers":"#f87171"}
        section(label_map[watch_source], color_map[watch_source])
        with st.spinner("Fetching screener..."):
            if watch_source == "most_active":
                raw = screener.most_active(top_n)
                rows = [
                    {
                        "Symbol":      r["symbol"],
                        "Volume":      f"{int(r['volume']):,}" if r.get("volume") else "—",
                        "Trade Count": f"{int(r['trade_count']):,}" if r.get("trade_count") else "—",
                    }
                    for r in raw
                ]
            elif watch_source == "gainers":
                raw = screener.top_gainers(top_n)
                rows = [
                    {
                        "Symbol":     r["symbol"],
                        "Price":      f"${float(r['price']):,.2f}" if r.get("price") else "—",
                        "change_pct": round(float(r["change_pct"]), 2) if r.get("change_pct") is not None else 0,
                    }
                    for r in raw
                ]
            else:
                raw = screener.top_losers(top_n)
                rows = [
                    {
                        "Symbol":     r["symbol"],
                        "Price":      f"${float(r['price']):,.2f}" if r.get("price") else "—",
                        "change_pct": round(float(r["change_pct"]), 2) if r.get("change_pct") is not None else 0,
                    }
                    for r in raw
                ]
        html_table(rows)

    section("Live Signals", "#34d399")
    signal_cache = {}
    signal_rows  = []
    with st.spinner("Computing signals..."):
        for symbol in watchlist:
            try:
                bars = broker.get_bars(symbol, timeframe=bar_timeframe)
                sig  = strategy.compute_signals(bars)
                signal_cache[symbol] = sig
                signal_rows.append({
                    "Symbol": symbol,
                    "Price":  f"${sig['price']:,.2f}" if sig["price"] else "—",
                    "Signal": sig["signal"].upper(),
                    "Score":  sig["score"],
                    "Regime": str(sig.get("regime", "range")).replace("_", " ").title(),
                    "RSI":    sig["rsi"] if sig["rsi"] else "—",
                    "ATR":    f"{sig['atr']:.3f}" if sig.get("atr") else "—",
                    "Reason": sig["reason"],
                    "Agent":  "—",
                })
            except Exception as e:
                signal_rows.append({"Symbol":symbol,"Price":"—","Signal":"ERROR","Score":0,"Regime":"—","RSI":"—","ATR":"—","Reason":str(e),"Agent":"—"})
    if not signal_rows:
        alert("neutral", "No symbols in watchlist.")
    else:
        html_table(signal_rows)

    # ── Symbol detail panel ─────────────────────────────────────────────────────
    section("Symbol Detail", "#38bdf8")

    # default to highest absolute score so the most interesting symbol is pre-selected
    _sorted_syms = sorted(
        [r for r in signal_rows if r["Signal"] != "ERROR"],
        key=lambda r: abs(r["Score"]),
        reverse=True,
    )
    if _sorted_syms:
        _default_sym = _sorted_syms[0]["Symbol"]
    elif watchlist:
        _default_sym = watchlist[0]
    else:
        _default_sym = None
    _sym_index   = watchlist.index(_default_sym) if _default_sym and _default_sym in watchlist else 0

    detail_sym = st.selectbox(
        "Select symbol for details",
        watchlist,
        index=_sym_index,
        key="detail_sym",
        label_visibility="collapsed",
        help="Select any symbol to see chart, technicals, and agent reasoning",
    )

    if detail_sym:
        try:
            _bars = broker.get_bars(detail_sym, timeframe=bar_timeframe)
            _sig  = signal_cache.get(detail_sym) or strategy.compute_signals(_bars)

            # ── Signal badge + technicals row ───────────────────────────────────
            _rsi_val   = _sig.get("rsi")
            _price_val = _sig.get("price")

            _d1, _d2, _d3, _d4, _d5 = st.columns(5)
            _d1.metric("Price",  f"${_price_val:,.2f}" if _price_val else "—")
            _d2.metric("Score",  f"{_sig['score']:+d}")
            _d3.metric("RSI(14)", f"{_rsi_val:.1f}" if _rsi_val else "—")
            _d4.metric("Signal", _sig["signal"].upper())
            _d5.metric("Regime", str(_sig.get("regime", "range")).replace("_", " ").title())

            # reason
            st.markdown(
                f'<div style="background:#0f172b;border:1px solid #1e293b;border-left:3px solid #38bdf8;'
                f'border-radius:8px;padding:10px 16px;color:#94a3b8;font-size:0.85rem;margin:4px 0 12px 0">'
                f'📝 {_sig["reason"]}</div>',
                unsafe_allow_html=True,
            )

            # ── Candlestick chart ───────────────────────────────────────────────
            _fig = charts.candlestick(_bars, detail_sym, _sig)
            st.plotly_chart(_fig, use_container_width=True)

            # ── Agent reasoning ─────────────────────────────────────────────────
            _agent_col1, _agent_col2 = st.columns([3, 1])
            with _agent_col2:
                _ask_agent = st.button(
                    f"🤖 Ask {provider_label}",
                    key="detail_ask_agent",
                    type="primary",
                    use_container_width=True,
                )
            with _agent_col1:
                if _ask_agent:
                    with st.spinner(f"{provider_label} analysing {detail_sym}..."):
                        _approved, _reason = agent.evaluate_signal(detail_sym, _sig)
                    if _approved:
                        alert("success", f"✅ APPROVED — {_reason}")
                    else:
                        alert("danger",  f"❌ REJECTED — {_reason}")
                else:
                    st.caption("Click **Ask Agent** to get LLM reasoning for this symbol.")

        except Exception as _e:
            alert("danger", f"Detail panel error: {_e}")

    # Agent approval
    section("Agent Trade Approval", "#a78bfa")
    spinner_label = f"{provider_label} is thinking..."
    al, ar = st.columns([2,1])
    with al:
        eval_symbol = st.selectbox("Symbol", watchlist, key="eval_sym", label_visibility="collapsed")
    with ar:
        if st.button(f"🤖 Ask {provider_label}", type="primary", use_container_width=True):
            try:
                bars = broker.get_bars(eval_symbol, timeframe=bar_timeframe)
                sig  = strategy.compute_signals(bars)
                with st.spinner(spinner_label):
                    approved, reason = agent.evaluate_signal(eval_symbol, sig)
                if approved: alert("success", f"✅ APPROVED — {reason}")
                else:        alert("danger",  f"❌ REJECTED — {reason}")
            except Exception as e: st.error(str(e))


# ═══════════════════════════════════════════════════════════════════════════════
# TAB 2 — CHARTS
# ═══════════════════════════════════════════════════════════════════════════════
with tab_charts:
    section("Candlestick Chart", "#38bdf8")
    col1, col2 = st.columns([2,1])
    with col1:
        chart_symbol = st.selectbox("Symbol", watchlist, key="chart_sym", label_visibility="collapsed")
    with col2:
        chart_tf = st.selectbox("Timeframe", ["1Min","5Min","15Min","1Hour","1Day"],
            index=["1Min","5Min","15Min","1Hour","1Day"].index(bar_timeframe), key="chart_tf", label_visibility="collapsed")

    with st.spinner(f"Loading {chart_symbol} bars..."):
        try:
            bars = broker.get_bars(chart_symbol, timeframe=chart_tf)
            sig  = signal_cache.get(chart_symbol) or strategy.compute_signals(bars)
            fig  = charts.candlestick(bars, chart_symbol, sig)
            st.plotly_chart(fig, use_container_width=True)

            # Quick stats under chart
            if bars:
                last  = bars[-1]
                prev  = bars[-2]["c"] if len(bars) > 1 else last["c"]
                chg   = ((last["c"] - prev) / prev) * 100
                r1,r2,r3,r4 = st.columns(4)
                r1.metric("Last",   f"${last['c']:,.2f}", f"{chg:+.2f}%")
                r2.metric("High",   f"${last['h']:,.2f}")
                r3.metric("Low",    f"${last['l']:,.2f}")
                r4.metric("Volume", f"{last['v']:,.0f}")
        except Exception as e:
            alert("danger", f"Chart error: {e}")


# ═══════════════════════════════════════════════════════════════════════════════
# TAB 3 — POSITIONS + P&L
# ═══════════════════════════════════════════════════════════════════════════════
with tab_positions:
    section("Open Positions & P&L", "#38bdf8")
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
                positions.append(
                    {
                        "symbol": p["symbol"],
                        "qty": _qty,
                        "side": _side,
                        "avg_entry": _entry,
                        "current_price": _current,
                        "unrealized_pnl": _pnl,
                        "unrealized_pnl_pct": _pnl_pct,
                    }
                )
        else:
            positions = broker.get_positions()
        if positions:
            total_pnl = sum(p["unrealized_pnl"] for p in positions)
            p1,p2,p3 = st.columns(3)
            pnl_color = "#34d399" if total_pnl >= 0 else "#f87171"
            p1.metric("Open Positions",  len(positions))
            p2.metric("Total Unr. P&L", f"${total_pnl:+,.2f}")
            p3.metric("SL / TP",        f"{sl_pct*100:.0f}% / {tp_pct*100:.0f}%")

            # Add SL/TP markers to each row
            rows = []
            for p in positions:
                sl_price = p["avg_entry"] * (1 - sl_pct) if sl_pct > 0 else "—"
                tp_price = p["avg_entry"] * (1 + tp_pct) if tp_pct > 0 else "—"
                rows.append({
                    "symbol":         p["symbol"],
                    "side":           p.get("side", "long").upper(),
                    "qty":            p["qty"],
                    "avg_entry":      f"${p['avg_entry']:,.2f}",
                    "current_price":  f"${p['current_price']:,.2f}",
                    "unrealized_pnl": f"${p['unrealized_pnl']:+,.2f}",
                    "unrealized_pnl_pct": f"{p['unrealized_pnl_pct']*100:+.2f}%",
                    "stop_loss":      f"${sl_price:,.2f}" if sl_price != "—" else "—",
                    "take_profit":    f"${tp_price:,.2f}" if tp_price != "—" else "—",
                })
            html_table(rows)
        else:
            alert("neutral", "No open positions.")
    except Exception as e:
        st.error(f"Failed to load positions: {e}")


# ═══════════════════════════════════════════════════════════════════════════════
# TAB 4 — ORDERS
# ═══════════════════════════════════════════════════════════════════════════════
with tab_orders:
    section("Recent Orders", "#f59e0b")
    try:
        if getattr(config, "SHADOW_MODE", False):
            summary = shadow_book.summary()
            closed = summary["closed_trades"]
            intents = summary["intents"]
            st.metric("Shadow Realized P&L", f"${summary['realized_pnl']:+,.2f}")
            if closed:
                section("Closed Shadow Trades", "#64748b")
                rows = [
                    {
                        "symbol": t["symbol"],
                        "side": t["side"].upper(),
                        "qty": t["qty"],
                        "entry": f"${t['entry_price']:,.2f}",
                        "exit": f"${t['exit_price']:,.2f}",
                        "pnl": f"${t['pnl']:+,.2f}",
                        "pnl_pct": f"{t['pnl_pct']:+.2f}%",
                        "exit_reason": t.get("close_reason", ""),
                        "exit_time": str(t.get("exit_time", ""))[:19].replace("T", " "),
                    }
                    for t in reversed(closed[-50:])
                ]
                html_table(rows)
            if intents:
                section("Shadow Intents", "#38bdf8")
                rows = [
                    {
                        "time": str(i.get("time", ""))[:19].replace("T", " "),
                        "symbol": i["symbol"],
                        "action": i["action"].upper(),
                        "qty": i["qty"],
                        "price": f"${float(i['price']):,.2f}",
                        "score": i.get("score", 0),
                    }
                    for i in reversed(intents[-50:])
                ]
                html_table(rows)
        else:
            orders = broker.get_orders(limit=30)
            if orders:
                # Realized P&L from matched buy/sell pairs
                buys  = {}
                realized = []
                for o in reversed(orders):
                    if o["status"] != "FILLED": continue
                    if o["side"] == "BUY":
                        buys[o["symbol"]] = o
                    elif o["side"] == "SELL" and o["symbol"] in buys:
                        b   = buys.pop(o["symbol"])
                        pnl = (o["filled_avg"] - b["filled_avg"]) * o["filled_qty"] if o["filled_avg"] and b["filled_avg"] else 0
                        realized.append({"Symbol": o["symbol"], "Buy": f"${b['filled_avg']:,.2f}", "Sell": f"${o['filled_avg']:,.2f}", "Qty": o["filled_qty"], "Realized P&L": f"${pnl:+,.2f}"})

                if realized:
                    total_realized = sum(float(r["Realized P&L"].replace("$","").replace(",","")) for r in realized)
                    st.metric("Total Realized P&L", f"${total_realized:+,.2f}")
                    html_table(realized)
                    st.markdown("---")

                section("All Orders", "#64748b")
                for o in orders:
                    o["side"]       = o["side"].upper()
                    o["filled_avg"] = f"${o['filled_avg']:,.2f}" if o["filled_avg"] else "—"
                    o["value"]      = f"${o['value']:,.2f}" if o["value"] else "—"
                html_table(orders)
            else:
                alert("neutral", "No recent orders.")
    except Exception as e:
        st.error(f"Failed to load orders: {e}")


# ═══════════════════════════════════════════════════════════════════════════════
# TAB 5 — EVENTS
# ═══════════════════════════════════════════════════════════════════════════════
with tab_events:
    section("Live News Feed", "#f59e0b")
    ev_c1, ev_c2 = st.columns([2, 1])
    with ev_c1:
        event_symbol = st.selectbox("Symbol", watchlist, key="event_sym", label_visibility="collapsed")
    with ev_c2:
        ev_news_n = st.slider("Headlines", 5, 20, 10, key="ev_news_n")

    # Always show live news — no LLM needed
    try:
        _news = events.fetch_news(symbols=[event_symbol], limit=ev_news_n)
        _news_rows = [
            {
                "Time":     n["created"][:16].replace("T", " ") if n["created"] else "—",
                "Source":   n["source"] or "—",
                "Headline": n["headline"],
            }
            for n in _news if n["headline"] and "[news fetch error" not in n["headline"]
        ]
        if _news_rows:
            html_table(_news_rows)
        else:
            alert("neutral", "No recent news found for this symbol.")
    except Exception as _e:
        alert("danger", f"News fetch error: {_e}")

    # Earnings auto-detect badge
    try:
        _eq_news = events.fetch_news(symbols=[event_symbol], keywords="earnings EPS guidance", limit=5)
        _has_earnings = any(
            any(kw in n["headline"].lower() for kw in ("earnings", "eps", "guidance", "beat", "miss"))
            for n in _eq_news if n["headline"] and "[news fetch error" not in n["headline"]
        )
        if _has_earnings:
            st.markdown(
                '<div class="alert alert-info" style="margin:8px 0">📊 <b>Earnings activity detected</b> '
                '— event analysis recommended</div>', unsafe_allow_html=True
            )
    except Exception:
        pass

    # LLM event analysis (on demand)
    section("LLM Event Analysis", "#a78bfa")
    if not config.USE_AGENT:
        alert("info", "Set AGENT_PROVIDER=claude or openai in .env to enable LLM event analysis.")
    else:
        if st.button(f"🔍 Analyse with {provider_label}", type="primary"):
            with st.spinner(f"{provider_label} scoring headlines..."):
                ev_result = events.get_event_score(
                    event_symbol, run_earnings=run_earnings, run_geo=run_geo, run_macro=run_macro
                )
            quant    = signal_cache.get(event_symbol, {"score": 0, "reason": "no quant data",
                                                       "signal": "hold", "rsi": None, "price": None,
                                                       "atr": None, "event_score": 0, "event_reasons": []})
            combined = strategy.apply_event_score(quant, ev_result)
            m1, m2, m3 = st.columns(3)
            m1.metric("Quant Score",    quant["score"])
            m2.metric("Event Score",    ev_result["event_score"])
            m3.metric("Combined Score", combined["score"])
            for sig in ev_result["signals"]:
                event_card(sig["event_type"].capitalize(), sig["score"], sig.get("confidence", "—"), sig["reason"])
            if combined["signal"] == "buy":
                alert("success", f"BUY — {combined['reason']}")
            elif combined["signal"] == "sell":
                alert("danger",  f"SELL — {combined['reason']}")
            else:
                alert("neutral", f"HOLD — {combined['reason']}")


# ═══════════════════════════════════════════════════════════════════════════════
# TAB 6 — BACKTEST
# ═══════════════════════════════════════════════════════════════════════════════
with tab_backtest:
    section("Strategy Backtest", "#a78bfa")
    bl, bm, bn, br = st.columns([2, 1, 1, 1])
    with bl:
        bt_symbol = st.selectbox("Symbol", watchlist, key="bt_sym", label_visibility="collapsed")
    with bm:
        bt_tf = st.selectbox(
            "Timeframe",
            ["1Min", "5Min", "15Min", "1Hour", "1Day"],
            index=4,
            key="bt_tf",
            label_visibility="collapsed",
        )
    with bn:
        _bt_lookback_opts = {"5d": 5, "20d": 20, "60d": 60, "180d": 180, "1y": 365, "2y": 730}
        bt_lookback_label = st.selectbox(
            "Lookback",
            list(_bt_lookback_opts.keys()),
            index=5,
            key="bt_lookback",
            label_visibility="collapsed",
        )
        bt_lookback_days = _bt_lookback_opts[bt_lookback_label]
    with br:
        run_bt = st.button("▶ Run Backtest", type="primary", use_container_width=True)

    if run_bt:
        with st.spinner(f"Backtesting {bt_symbol} · {bt_tf} · {bt_lookback_label}..."):
            result = backtest.run(bt_symbol, timeframe=bt_tf, lookback_days=bt_lookback_days)

        if "error" in result:
            alert("danger", result["error"])
            st.caption("💡 Tip: Alpaca free tier limits intraday history. Try **1Day** timeframe with **1y** or **2y** lookback for best results.")
        else:
            ret_color = "#34d399" if result["total_return_pct"] >= 0 else "#f87171"
            c1,c2,c3,c4 = st.columns(4)
            c1.metric("Total Return",   f"{result['total_return_pct']:+.2f}%")
            c2.metric("Sharpe Ratio",   result["sharpe"])
            c3.metric("Max Drawdown",   f"{result['max_drawdown_pct']:.2f}%")
            c4.metric("Win Rate",       f"{result['win_rate_pct']:.1f}%")

            c5,c6,c7,c8 = st.columns(4)
            c5.metric("Total Trades",   result["total_trades"])
            c6.metric("Profit Factor",  result["profit_factor"])
            c7.metric("Avg Win",        f"${result['avg_win']:,.2f}")
            c8.metric("Avg Loss",       f"${result['avg_loss']:,.2f}")

            # Equity curve
            if result["equity_curve"]:
                section("Equity Curve vs SPY", "#615fff")
                fig = charts.equity_curve(
                    result["equity_curve"],
                    benchmark_records=result.get("benchmark"),
                    trades=result.get("trades"),
                )
                st.plotly_chart(fig, use_container_width=True)

            # Trade log (hide internal date fields from table)
            if result["trades"]:
                section("Trade Log", "#64748b")
                _display_trades = [
                    {k: v for k, v in t.items() if k not in ("entry_date", "exit_date")}
                    for t in result["trades"]
                ]
                html_table(_display_trades)

    # ── Walk-forward validation ─────────────────────────────────────────────────
    st.markdown("---")
    section("Walk-Forward Validation", "#38bdf8")
    st.caption("Splits data into folds, tests out-of-sample performance to detect overfitting.")
    wf_c1, wf_c2, wf_c3 = st.columns([2, 1, 1])
    with wf_c1:
        wf_sym = st.selectbox("Symbol", watchlist, key="wf_sym", label_visibility="collapsed")
    with wf_c2:
        wf_tf = st.selectbox("Timeframe", ["1Day", "1Hour"], key="wf_tf", label_visibility="collapsed")
    with wf_c3:
        run_wf = st.button("▶ Walk-Forward", type="primary", use_container_width=True)

    if run_wf:
        with st.spinner(f"Running {5}-fold walk-forward on {wf_sym}..."):
            wf = backtest.walk_forward(wf_sym, timeframe=wf_tf)
        if "error" in wf:
            alert("danger", wf["error"])
        else:
            wf_m1, wf_m2, wf_m3, wf_m4 = st.columns(4)
            wf_m1.metric("Avg OOS Return",   f"{wf['avg_return_pct']:+.2f}%")
            wf_m2.metric("Avg Sharpe",        wf["avg_sharpe"])
            wf_m3.metric("Avg Win Rate",      f"{wf['avg_win_rate']:.1f}%")
            wf_m4.metric("Profitable Folds",  wf["profitable_folds"])
            html_table([{k: v for k, v in f.items() if k != "folds"} for f in wf["folds"]])

    # ── Parameter optimisation ─────────────────────────────────────────────────
    st.markdown("---")
    section("Parameter Optimisation (Grid Search)", "#a78bfa")
    st.caption("Searches signal threshold × stop loss × take profit combinations. Ranked by Sharpe ratio.")
    opt_c1, opt_c2 = st.columns([3, 1])
    with opt_c1:
        opt_sym = st.selectbox("Symbol", watchlist, key="opt_sym", label_visibility="collapsed")
    with opt_c2:
        run_opt = st.button("▶ Optimise", type="primary", use_container_width=True)

    if run_opt:
        with st.spinner(f"Grid searching {opt_sym} — testing 48 parameter combinations..."):
            opt = backtest.optimize(opt_sym)
        if "error" in opt:
            alert("danger", opt["error"])
        else:
            best = opt["best"]
            alert("success",
                  f"Best: threshold={best['threshold']}  SL={best['sl_pct']}  TP={best['tp_pct']}  "
                  f"→ Sharpe {best['sharpe']}  Return {best['return']:+.2f}%  Win {best['win_rate']:.1f}%")
            section("Top 20 Combinations", "#64748b")
            html_table(opt["results"])


# ═══════════════════════════════════════════════════════════════════════════════
# TAB 7 — WATCHLIST MANAGER
# ═══════════════════════════════════════════════════════════════════════════════
with tab_watchlist:
    section("Watchlist Manager", "#34d399")

    _wl_all = watchlist_store.load()

    st.markdown("**All symbols** (add or remove below):")
    if _wl_all:
        html_table([{"Symbol": s} for s in _wl_all])
    else:
        alert("neutral", "Watchlist is empty — add symbols below.")

    st.markdown("---")
    wl1, wl2 = st.columns(2)
    with wl1:
        st.markdown("**Add symbol**")
        new_sym = st.text_input("Ticker", placeholder="e.g. AAPL", label_visibility="collapsed").upper().strip()
        if st.button("Add", type="primary", use_container_width=True) and new_sym:
            watchlist_store.add(new_sym)
            st.success(f"Added {new_sym}")
            st.rerun()
    with wl2:
        st.markdown("**Remove symbol**")
        if _wl_all:
            rm_sym = st.selectbox("Symbol to remove", _wl_all, label_visibility="collapsed")
            if st.button("Remove", use_container_width=True):
                watchlist_store.remove(rm_sym)
                st.success(f"Removed {rm_sym}")
                st.rerun()
        else:
            st.caption("Nothing to remove.")


# ═══════════════════════════════════════════════════════════════════════════════
# TAB 8 — ALERTS CONFIG
# ═══════════════════════════════════════════════════════════════════════════════
with tab_alerts_cfg:
    section("Alert Configuration", "#f87171")
    st.caption("Set these in your `.env` file — no code changes needed.")

    a1, a2, a3 = st.columns(3)
    with a1:
        st.markdown("**📧 Email**")
        st.code("""ALERT_EMAIL_TO=you@gmail.com
ALERT_SMTP_HOST=smtp.gmail.com
ALERT_SMTP_PORT=465
ALERT_SMTP_USER=you@gmail.com
ALERT_SMTP_PASS=app_password""", language="bash")
        enabled = bool(config.ALERT_EMAIL_TO)
        st.markdown(f"Status: {'🟢 Configured' if enabled else '⚪ Not configured'}")

    with a2:
        st.markdown("**💬 Slack**")
        st.code("ALERT_SLACK_WEBHOOK=https://hooks.slack.com/...", language="bash")
        enabled = bool(config.ALERT_SLACK_WEBHOOK)
        st.markdown(f"Status: {'🟢 Configured' if enabled else '⚪ Not configured'}")

    with a3:
        st.markdown("**✈️ Telegram**")
        st.code("""ALERT_TELEGRAM_TOKEN=your_bot_token
ALERT_TELEGRAM_CHAT_ID=your_chat_id""", language="bash")
        enabled = bool(config.ALERT_TELEGRAM_TOKEN)
        st.markdown(f"Status: {'🟢 Configured' if enabled else '⚪ Not configured'}")

    st.markdown("---")
    st.markdown("**Test alert** (fires to all configured channels):")
    if st.button("🔔 Send test alert", type="primary"):
        try:
            import alerts as alert_module
            alert_module.send("Test Alert", "TradeAgent alert system is working correctly.")
            alert("success", "Test alert sent to all configured channels.")
        except Exception as e:
            alert("danger", f"Alert failed: {e}")


# ═══════════════════════════════════════════════════════════════════════════════
# TAB 9 — LOG
# ═══════════════════════════════════════════════════════════════════════════════
with tab_log:
    section("Trade Log", "#64748b")
    try:
        with open("trade.log") as f:
            lines = f.readlines()

        log_lc, log_rc = st.columns([3, 1])
        with log_lc:
            log_filter = st.selectbox(
                "Level",
                ["ALL", "ERROR", "WARNING", "INFO"],
                label_visibility="collapsed",
                key="log_level",
            )
        with log_rc:
            log_lines = st.slider("Lines", 20, 200, 60, key="log_lines_n")

        _level_colors = {"ERROR": "#f87171", "WARNING": "#f59e0b", "INFO": "#94a3b8", "DEBUG": "#64748b"}
        _level_bg     = {"ERROR": "#2d0a0a22", "WARNING": "#2d1a0022", "INFO": "", "DEBUG": ""}

        filtered = [l for l in lines if log_filter == "ALL" or f"[{log_filter}]" in l]
        display  = filtered[-log_lines:]

        html_lines = []
        for line in display:
            line = line.rstrip()
            level = "INFO"
            for lvl in ("ERROR", "WARNING", "INFO", "DEBUG"):
                if f"[{lvl}]" in line:
                    level = lvl
                    break
            color = _level_colors.get(level, "#cbd5e1")
            bg    = _level_bg.get(level, "")
            bg_style = f"background:{bg};" if bg else ""
            html_lines.append(
                f'<div style="{bg_style}padding:2px 8px;font-family:monospace;font-size:0.78rem;'
                f'color:{color};border-left:2px solid {color}33;margin-bottom:1px">{line}</div>'
            )

        with st.expander(f"📄 {len(display)} lines shown  ({len(lines)} total)", expanded=True):
            st.markdown(
                '<div style="background:#0a0f1e;border:1px solid #1e293b;border-radius:8px;padding:8px;'
                'max-height:500px;overflow-y:auto">' + "".join(html_lines) + "</div>",
                unsafe_allow_html=True,
            )

    except FileNotFoundError:
        alert("neutral", "No trade.log yet — run main.py to start logging.")

# ── Auto-refresh ───────────────────────────────────────────────────────────────
if auto_refresh:
    time.sleep(30)
    st.rerun()
