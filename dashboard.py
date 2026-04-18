import streamlit as st
import time
import plotly.graph_objects as go
import pandas as pd
from collections import deque

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
@import url('https://fonts.googleapis.com/css2?family=Manrope:wght@400;500;600;700;800&family=Sora:wght@600;700;800&family=JetBrains+Mono:wght@500;700&display=swap');

:root {
    --bg-0: #050a16;
    --bg-1: #0a1428;
    --bg-2: #0f1d38;
    --surface-0: rgba(8, 17, 34, 0.84);
    --surface-1: rgba(12, 24, 46, 0.92);
    --surface-2: rgba(14, 30, 55, 0.95);
    --border-0: #263a57;
    --border-1: #365172;
    --text-main: #e8eef9;
    --text-soft: #b9c9df;
    --text-dim: #7f95b3;
    --accent: #22d3ee;
    --accent-2: #38bdf8;
    --success: #34d399;
    --danger: #fb7185;
    --warning: #f59e0b;
    --shadow-lg: 0 20px 48px rgba(2, 8, 20, 0.48);
    --space-1: 0.35rem;
    --space-2: 0.55rem;
    --space-3: 0.8rem;
    --space-4: 1.1rem;
    --radius-sm: 10px;
    --radius-md: 14px;
    --radius-lg: 18px;
}

* { font-family: 'Manrope', sans-serif; }
html, body, .stApp {
    color: var(--text-main);
    background:
        radial-gradient(circle at 3% 8%, rgba(34, 211, 238, 0.16), transparent 36%),
        radial-gradient(circle at 92% 0%, rgba(56, 189, 248, 0.16), transparent 38%),
        radial-gradient(circle at 50% 110%, rgba(14, 165, 233, 0.14), transparent 44%),
        linear-gradient(160deg, var(--bg-0) 0%, var(--bg-1) 56%, var(--bg-0) 100%);
    background-attachment: fixed;
}

code, pre, [data-testid="stCodeBlock"], [data-testid="stMarkdownPre"] {
    font-family: 'JetBrains Mono', monospace !important;
}

footer { visibility: hidden; }
#MainMenu { visibility: hidden; }
[data-testid="stDecoration"] { display: none !important; }
[data-testid="stAppDeployButton"] { display: none !important; }
[data-testid="stSidebar"] { display: none !important; }
[data-testid="collapsedControl"] { display: none !important; }
[data-testid="stSidebarCollapsedControl"] { display: none !important; }
[data-testid="stHeader"] {
    background: transparent !important;
    backdrop-filter: none !important;
    border-bottom: none !important;
    min-height: 0 !important;
    height: 0 !important;
}
[data-testid="block-container"] {
    padding-top: 1rem;
    padding-bottom: 1.25rem;
    max-width: 1360px;
}

h1, h2, h3, h4, h5, h6 { color: var(--text-main); letter-spacing: -0.015em; }
p, li, span, label, [data-testid="stCaptionContainer"] { color: var(--text-soft); }
[data-testid="stMarkdownContainer"] p { font-size: 0.9rem; line-height: 1.48; }
[data-testid="stCaptionContainer"] p { font-size: 0.76rem; line-height: 1.4; }
[data-testid="stWidgetLabel"] p {
    color: var(--text-dim) !important;
    font-size: 0.74rem !important;
    letter-spacing: 0.06em;
    text-transform: uppercase;
    font-weight: 700 !important;
}
hr { border-color: rgba(54, 81, 114, 0.75) !important; }

.hero-shell {
    position: relative;
    overflow: hidden;
    display: flex;
    align-items: center;
    gap: 1rem;
    padding: 1rem 1.1rem 1.03rem 1.1rem;
    border-radius: var(--radius-lg);
    border: 1px solid var(--border-0);
    background: linear-gradient(135deg, rgba(8, 18, 35, 0.95), rgba(11, 25, 48, 0.95));
    box-shadow: var(--shadow-lg);
    margin-bottom: 0.55rem;
}
.hero-shell::after {
    content: '';
    position: absolute;
    width: 300px;
    height: 300px;
    right: -130px;
    bottom: -140px;
    border-radius: 999px;
    background: radial-gradient(circle, rgba(34, 211, 238, 0.24) 0%, rgba(34, 211, 238, 0) 74%);
    pointer-events: none;
}
.hero-logo {
    width: 56px;
    height: 56px;
    border-radius: 16px;
    flex-shrink: 0;
    display: flex;
    align-items: center;
    justify-content: center;
    font-family: 'Sora', sans-serif;
    font-size: 1.24rem;
    font-weight: 800;
    letter-spacing: -0.06em;
    color: #f0f9ff;
    background: linear-gradient(148deg, #075985 0%, #0891b2 42%, #0ea5a8 100%);
    border: 1px solid rgba(125, 211, 252, 0.45);
    box-shadow: 0 12px 24px rgba(7, 89, 133, 0.54), inset 0 1px 0 rgba(224, 242, 254, 0.28);
}
.hero-copy { display: flex; flex-direction: column; gap: 0.32rem; min-width: 0; }
.hero-title-row {
    display: flex;
    align-items: center;
    gap: 0.6rem;
    flex-wrap: wrap;
    padding-bottom: 0.02rem;
}
.hero-title {
    display: block;
    font-family: 'Sora', sans-serif;
    font-size: 1.82rem;
    line-height: 1.22;
    padding-bottom: 0.08em;
    margin: 0;
    font-weight: 800;
    letter-spacing: -0.036em;
    color: #e6f3ff;
    text-rendering: optimizeLegibility;
    -webkit-font-smoothing: antialiased;
}
.hero-title-accent {
    color: #67e8f9;
    text-shadow: 0 0 20px rgba(34, 211, 238, 0.22);
}
.hero-tag {
    font-size: 0.65rem;
    letter-spacing: 0.11em;
    text-transform: uppercase;
    color: #9db5d6;
    font-weight: 700;
    border: 1px solid rgba(61, 90, 126, 0.6);
    background: rgba(11, 30, 55, 0.72);
    border-radius: 999px;
    padding: 0.13rem 0.5rem;
    padding-bottom: 0.02em;
}
.hero-meta {
    display: flex;
    align-items: center;
    flex-wrap: wrap;
    gap: 0.5rem;
    color: #89a5c8;
    font-size: 0.75rem;
}
.hero-meta b { color: #d4e7ff; font-weight: 800; }
.hero-sep { color: #304766; }
.hero-time {
    font-family: 'JetBrains Mono', monospace;
    font-size: 0.72rem;
    color: #8aa6c8;
}
.loop-state {
    display: inline-flex;
    align-items: center;
    gap: 0.34rem;
    border-radius: 999px;
    padding: 0.15rem 0.52rem;
    font-size: 0.72rem;
    font-weight: 700;
    border: 1px solid #38506f;
}
.loop-state.running {
    background: rgba(22, 163, 74, 0.14);
    border-color: rgba(74, 222, 128, 0.4);
    color: #bbf7d0;
}
.loop-state.running::before {
    content: '';
    width: 7px;
    height: 7px;
    border-radius: 999px;
    background: #22c55e;
    box-shadow: 0 0 0 rgba(34, 197, 94, 0.6);
    animation: livePulse 1.55s ease-out infinite;
}
.loop-state.stopped {
    background: rgba(71, 85, 105, 0.2);
    border-color: rgba(100, 116, 139, 0.42);
    color: #94a3b8;
}
.loop-state.stopped::before {
    content: '';
    width: 7px;
    height: 7px;
    border-radius: 999px;
    background: #64748b;
}
@keyframes livePulse {
    0% { box-shadow: 0 0 0 0 rgba(34, 197, 94, 0.55); }
    70% { box-shadow: 0 0 0 8px rgba(34, 197, 94, 0); }
    100% { box-shadow: 0 0 0 0 rgba(34, 197, 94, 0); }
}

[data-testid="stMetric"] {
    position: relative;
    overflow: hidden;
    border-radius: var(--radius-md);
    border: 1px solid var(--border-0);
    background: linear-gradient(160deg, var(--surface-1) 0%, var(--surface-2) 100%);
    padding: 15px 18px;
    transition: border-color 0.2s ease, transform 0.2s ease, box-shadow 0.22s ease;
}
[data-testid="stMetric"]::before {
    content: '';
    position: absolute;
    inset: 0 auto auto 0;
    width: 100%;
    height: 2px;
    background: linear-gradient(90deg, #22d3ee, #38bdf8, #22c55e);
}
[data-testid="stMetric"]:hover {
    border-color: var(--accent-2);
    box-shadow: 0 12px 30px rgba(3, 105, 161, 0.32);
    transform: translateY(-1px);
}
[data-testid="stMetricLabel"] {
    font-size: 0.64rem;
    letter-spacing: 0.11em;
    text-transform: uppercase;
    color: var(--text-dim) !important;
    font-weight: 700;
}
[data-testid="stMetricValue"] {
    font-size: 1.42rem;
    font-weight: 800;
    color: var(--text-main) !important;
}

.section-header {
    display: flex;
    align-items: center;
    gap: 10px;
    margin: 24px 0 12px 0;
    padding-bottom: 7px;
    border-bottom: 1px solid rgba(54, 81, 114, 0.7);
    font-size: 0.66rem;
    font-weight: 700;
    letter-spacing: 0.12em;
    text-transform: uppercase;
    color: var(--text-dim);
}
.section-dot {
    width: 7px;
    height: 7px;
    border-radius: 50%;
    display: inline-block;
    box-shadow: 0 0 0 4px rgba(34, 211, 238, 0.14);
}

.focus-strip { display: flex; flex-wrap: wrap; gap: 8px; margin: 10px 0 13px 0; }
.focus-chip {
    display: inline-flex;
    align-items: center;
    gap: 8px;
    border-radius: 999px;
    padding: 6px 11px;
    color: #d0def1;
    font-size: 0.75rem;
    white-space: nowrap;
    border: 1px solid #2f4663;
    background: linear-gradient(140deg, rgba(9, 20, 39, 0.86), rgba(18, 37, 64, 0.9));
    transition: transform 0.18s ease, border-color 0.18s ease, box-shadow 0.2s ease;
}
.focus-chip:hover {
    transform: translateY(-1px);
    border-color: #4d719a;
    box-shadow: 0 8px 20px rgba(8, 47, 73, 0.38);
}
.focus-chip b {
    color: #67e8f9;
    font-size: 0.66rem;
    letter-spacing: 0.08em;
    text-transform: uppercase;
}

.event-card {
    background: linear-gradient(145deg, rgba(11, 22, 42, 0.95), rgba(15, 31, 58, 0.93));
    border: 1px solid #2d4563;
    border-radius: 11px;
    padding: 13px 16px;
    margin-bottom: 9px;
    transition: border-color 0.18s ease, transform 0.18s ease;
}
.event-card:hover {
    border-color: #4a7098;
    transform: translateY(-1px);
}
.event-card.bullish { border-left: 4px solid #22c55e; }
.event-card.bearish { border-left: 4px solid #fb7185; }
.event-card.neutral { border-left: 4px solid #64748b; }

.alert {
    border-radius: var(--radius-sm);
    padding: 11px 14px;
    margin: 9px 0;
    font-weight: 600;
    border: 1px solid #2f4663;
    backdrop-filter: blur(5px);
}
.alert-success { background: linear-gradient(135deg, rgba(5, 46, 22, 0.82), rgba(6, 78, 59, 0.8)); color: #6ee7b7; border-color: rgba(16, 185, 129, 0.48); }
.alert-danger  { background: linear-gradient(135deg, rgba(69, 10, 10, 0.84), rgba(127, 29, 29, 0.8)); color: #fda4af; border-color: rgba(244, 63, 94, 0.48); }
.alert-neutral { background: linear-gradient(135deg, rgba(15, 23, 42, 0.84), rgba(30, 41, 59, 0.82)); color: #c3d4ec; border-color: rgba(71, 95, 126, 0.55); }
.alert-info    { background: linear-gradient(135deg, rgba(8, 47, 73, 0.84), rgba(14, 116, 144, 0.8)); color: #bae6fd; border-color: rgba(56, 189, 248, 0.5); }

.stat-card {
    background: linear-gradient(145deg, rgba(12, 24, 46, 0.94), rgba(16, 32, 60, 0.9));
    border: 1px solid #304a69;
    border-radius: var(--radius-sm);
    padding: 14px 17px;
    text-align: center;
    margin-bottom: 8px;
}
.stat-label {
    color: var(--text-dim);
    font-size: 0.64rem;
    text-transform: uppercase;
    letter-spacing: 0.09em;
    font-weight: 700;
}
.stat-value {
    font-size: 1.2rem;
    font-weight: 800;
    color: var(--text-main);
    margin-top: 4px;
}

.ticker-wrap {
    overflow: hidden;
    border-radius: var(--radius-sm);
    border: 1px solid #2f4766;
    background: linear-gradient(90deg, rgba(8, 18, 36, 0.98), rgba(11, 27, 49, 0.95), rgba(8, 18, 36, 0.98));
    box-shadow: inset 0 1px 0 rgba(103, 232, 249, 0.08);
    padding: 9px 0;
    margin-bottom: 20px;
}
.ticker-track {
    display: flex;
    gap: 44px;
    width: max-content;
    animation: tickerScroll 34s linear infinite;
}
.ticker-wrap:hover .ticker-track { animation-play-state: paused; }
@keyframes tickerScroll { from { transform: translateX(0); } to { transform: translateX(-50%); } }
.ticker-item { display: inline-flex; align-items: center; gap: 8px; white-space: nowrap; }
.ticker-sym { font-weight: 800; font-size: 0.8rem; color: #67e8f9; letter-spacing: 0.05em; }
.ticker-price { font-size: 0.8rem; color: var(--text-main); }
.ticker-up, .ticker-down { font-size: 0.71rem; font-weight: 700; }
.ticker-up { color: #34d399; }
.ticker-down { color: #fb7185; }

[data-testid="stTabs"] {
    border-radius: var(--radius-md);
    border: 1px solid #2f4766;
    background: rgba(9, 20, 39, 0.88);
    backdrop-filter: blur(5px);
    margin-top: 8px;
}
[data-testid="stTabs"] > div:first-child {
    background: linear-gradient(90deg, rgba(8, 18, 35, 0.92), rgba(12, 28, 51, 0.95));
    border-radius: 12px 12px 0 0;
    padding: 6px 8px 0 8px;
    border-bottom: 1px solid #2f4766;
    gap: 4px;
    overflow-x: auto;
    scrollbar-width: none;
}
[data-testid="stTabs"] > div:first-child::-webkit-scrollbar { display: none; }
[data-testid="stTab"] {
    border: 1px solid transparent !important;
    border-bottom: none !important;
    border-radius: 8px 8px 0 0 !important;
    background: transparent !important;
    color: var(--text-dim) !important;
    font-size: 0.75rem !important;
    font-weight: 700 !important;
    letter-spacing: 0.04em !important;
    padding: 7px 12px !important;
    white-space: nowrap;
    transition: all 0.17s ease;
}
[data-testid="stTab"]:hover {
    background: rgba(20, 40, 68, 0.8) !important;
    color: #cbe8ff !important;
    border-color: #3f5f85 !important;
}
[data-testid="stTab"][aria-selected="true"] {
    background: linear-gradient(135deg, rgba(8, 47, 73, 0.74), rgba(14, 116, 144, 0.68)) !important;
    color: #e0f2fe !important;
    border-color: #4f7ca8 !important;
    box-shadow: inset 0 -2px 0 #67e8f9;
}
[data-testid="stTabPanel"] {
    background: rgba(8, 18, 35, 0.84);
    border-radius: 0 0 var(--radius-sm) var(--radius-sm);
    padding: 18px 16px !important;
}

div[data-testid="stRadio"] > div {
    gap: 0.46rem;
    flex-wrap: wrap;
}
div[data-testid="stRadio"] label {
    background: linear-gradient(135deg, rgba(9, 20, 39, 0.9), rgba(15, 31, 58, 0.9));
    border: 1px solid #2f4663;
    border-radius: 999px;
    padding: 0.18rem 0.64rem;
    transition: all 0.17s ease;
}
div[data-testid="stRadio"] label:hover {
    border-color: #4d729a;
    transform: translateY(-1px);
}
div[data-testid="stRadio"] label p {
    color: var(--text-soft) !important;
    font-size: 0.78rem !important;
    font-weight: 700 !important;
}
div[data-testid="stRadio"] label:has(input:checked) {
    border-color: #67e8f9;
    box-shadow: 0 0 0 1px rgba(103, 232, 249, 0.25) inset;
    background: linear-gradient(135deg, rgba(8, 47, 73, 0.8), rgba(14, 116, 144, 0.72));
}
div[data-testid="stRadio"] label:has(input:checked) p { color: #ecfeff !important; }

[data-testid="stSelectbox"] > div > div,
[data-testid="stNumberInput"] input,
[data-testid="stTextInput"] input,
[data-testid="stMultiSelect"] > div > div {
    background: rgba(11, 24, 46, 0.92) !important;
    border: 1px solid #304969 !important;
    border-radius: var(--radius-sm) !important;
    color: var(--text-main) !important;
    font-size: 0.81rem !important;
}
[data-testid="stSelectbox"] > div > div:focus-within,
[data-testid="stTextInput"] input:focus,
[data-testid="stNumberInput"] input:focus,
[data-testid="stMultiSelect"] > div > div:focus-within {
    border-color: #67e8f9 !important;
    box-shadow: 0 0 0 2px rgba(103, 232, 249, 0.2) !important;
}

[data-testid="stButton"] > button {
    border-radius: var(--radius-sm) !important;
    min-height: 38px;
    font-size: 0.79rem !important;
    font-weight: 700 !important;
    letter-spacing: 0.02em !important;
    transition: all 0.18s ease !important;
}
[data-testid="stButton"] > button[kind="primary"] {
    border: none !important;
    color: #ecfeff !important;
    background: linear-gradient(135deg, #0284c7, #06b6d4) !important;
    box-shadow: 0 10px 24px rgba(6, 182, 212, 0.34) !important;
}
[data-testid="stButton"] > button[kind="primary"]:hover {
    background: linear-gradient(135deg, #0ea5e9, #22d3ee) !important;
    box-shadow: 0 14px 30px rgba(34, 211, 238, 0.32) !important;
    transform: translateY(-1px);
}
[data-testid="stButton"] > button:not([kind="primary"]) {
    background: linear-gradient(135deg, rgba(11, 24, 46, 0.88), rgba(20, 40, 68, 0.88)) !important;
    border: 1px solid #324c6e !important;
    color: var(--text-soft) !important;
}
[data-testid="stButton"] > button:not([kind="primary"]):hover {
    border-color: #67e8f9 !important;
    color: #e0f2fe !important;
}

[data-testid="stSlider"] [data-testid="stThumbValue"] { color: #7dd3fc !important; }
[data-testid="stSlider"] [role="slider"] {
    background: #22d3ee !important;
    border-color: #67e8f9 !important;
}

[data-testid="stToggle"] > label > div[data-testid="stMarkdownContainer"] p {
    font-size: 0.79rem !important;
    color: var(--text-soft) !important;
}

[data-testid="stExpander"] {
    border-radius: var(--radius-sm) !important;
    border: 1px solid #2c4361 !important;
    background: linear-gradient(145deg, rgba(9, 20, 39, 0.9), rgba(13, 28, 52, 0.9)) !important;
    overflow: hidden;
}
[data-testid="stExpander"] summary {
    color: var(--text-soft) !important;
    font-size: 0.79rem !important;
}
[data-testid="stExpander"] summary span { font-weight: 700 !important; }

[data-testid="stPlotlyChart"] {
    border: 1px solid #2b4362;
    border-radius: var(--radius-md);
    padding: 4px;
    width: 100%;
    box-sizing: border-box;
    overflow: hidden;
    background: linear-gradient(145deg, rgba(9, 20, 39, 0.75), rgba(12, 26, 49, 0.72));
    box-shadow: inset 0 1px 0 rgba(103, 232, 249, 0.07);
}

[data-testid="stSpinner"] { color: #22d3ee !important; }
::-webkit-scrollbar { width: 8px; height: 8px; }
::-webkit-scrollbar-track { background: #0a1324; }
::-webkit-scrollbar-thumb { background: #2c4566; border-radius: 999px; }
::-webkit-scrollbar-thumb:hover { background: #3e6591; }

.module-stamp {
    display: inline-flex;
    align-items: center;
    gap: 0.36rem;
    margin-bottom: 0.4rem;
    border-radius: 999px;
    border: 1px solid #2e4968;
    background: rgba(8, 18, 35, 0.82);
    color: #9bb3d4;
    font-size: 0.66rem;
    font-weight: 700;
    letter-spacing: 0.04em;
    text-transform: uppercase;
    padding: 0.22rem 0.56rem;
}

.health-strip {
    display: flex;
    align-items: center;
    flex-wrap: wrap;
    gap: 0.45rem;
    margin: 0.22rem 0 0.8rem 0;
}
.health-pill {
    display: inline-flex;
    align-items: center;
    gap: 0.36rem;
    border-radius: 999px;
    border: 1px solid #2d4563;
    background: rgba(8, 18, 35, 0.78);
    padding: 0.2rem 0.56rem;
    font-size: 0.69rem;
    font-weight: 700;
    color: #bfd4ef;
}
.health-pill.ok {
    border-color: rgba(74, 222, 128, 0.42);
    color: #bbf7d0;
    background: rgba(22, 101, 52, 0.18);
}
.health-pill.warn {
    border-color: rgba(251, 146, 60, 0.48);
    color: #fed7aa;
    background: rgba(124, 45, 18, 0.22);
}
.health-pill.err {
    border-color: rgba(251, 113, 133, 0.48);
    color: #fecdd3;
    background: rgba(136, 19, 55, 0.2);
}
.health-pill .dot {
    width: 8px;
    height: 8px;
    border-radius: 999px;
    background: currentColor;
    opacity: 0.85;
}

.workspace-nav-note {
    color: #8ea8ca;
    font-size: 0.73rem;
    margin: 0.18rem 0 0.35rem 0;
    letter-spacing: 0.03em;
}
.workspace-focus-card {
    position: relative;
    overflow: hidden;
    border: 1px solid #2d4563;
    border-radius: var(--radius-md);
    background: linear-gradient(145deg, rgba(9, 20, 39, 0.92), rgba(12, 28, 52, 0.94));
    padding: 0.72rem 0.9rem 0.72rem 1rem;
    margin: 0.08rem 0 0.58rem 0;
}
.workspace-focus-card::before {
    content: '';
    position: absolute;
    left: 0;
    top: 0;
    bottom: 0;
    width: 4px;
    background: var(--panel-accent, #67e8f9);
}
.workspace-focus-head {
    display: flex;
    align-items: center;
    flex-wrap: wrap;
    gap: 0.46rem;
}
.workspace-focus-title {
    font-family: 'Sora', sans-serif;
    font-size: 1.04rem;
    font-weight: 700;
    letter-spacing: -0.01em;
    color: #e7f3ff;
}
.workspace-focus-badge {
    border: 1px solid #355173;
    background: rgba(11, 28, 52, 0.8);
    color: #9dc0e7;
    border-radius: 999px;
    font-size: 0.62rem;
    letter-spacing: 0.09em;
    text-transform: uppercase;
    font-weight: 800;
    padding: 0.13rem 0.45rem;
}
.workspace-focus-text {
    margin-top: 0.28rem;
    color: #aac2df;
    font-size: 0.8rem;
    line-height: 1.42;
}
.workspace-focus-tip {
    margin-top: 0.2rem;
    color: #86a4cb;
    font-size: 0.72rem;
    letter-spacing: 0.02em;
}
.workspace-subnote {
    color: #8ea8ca;
    font-size: 0.72rem;
    margin: 0.08rem 0 0.35rem 0;
    letter-spacing: 0.02em;
}
.workspace-active-chip {
    display: inline-flex;
    align-items: center;
    gap: 0.38rem;
    margin-top: 0.46rem;
    border: 1px solid #304a69;
    border-radius: 999px;
    padding: 0.22rem 0.58rem;
    background: rgba(10, 23, 44, 0.86);
    color: #9cb8da;
    font-size: 0.71rem;
    letter-spacing: 0.03em;
}
.workspace-active-chip b {
    color: #d7e9ff;
    font-weight: 800;
}
.snapshot-note {
    color: #8ea8ca;
    font-size: 0.72rem;
    margin: 0.22rem 0 0.32rem 0;
    letter-spacing: 0.02em;
}
.panel-quick-note {
    color: #8ea8ca;
    font-size: 0.69rem;
    text-transform: uppercase;
    letter-spacing: 0.08em;
    margin: 0.05rem 0 0.36rem 0;
}

.table-tools {
    display: flex;
    flex-wrap: wrap;
    gap: 0.4rem;
    margin: 0 0 0.52rem 0;
}

.skeleton-wrap {
    border: 1px solid #2c4462;
    border-radius: var(--radius-sm);
    background: rgba(9, 21, 41, 0.84);
    padding: 0.8rem;
    margin: 0.3rem 0 0.65rem 0;
}
.skeleton-line {
    height: 0.72rem;
    border-radius: 999px;
    margin-bottom: 0.56rem;
    background: linear-gradient(90deg, rgba(38, 61, 89, 0.44), rgba(76, 110, 150, 0.42), rgba(38, 61, 89, 0.44));
    background-size: 220% 100%;
    animation: shimmer 1.2s linear infinite;
}
.skeleton-line:last-child { margin-bottom: 0; width: 72%; }
@keyframes shimmer {
    0% { background-position: 200% 0; }
    100% { background-position: -20% 0; }
}

a:focus-visible,
button:focus-visible,
input:focus-visible,
textarea:focus-visible,
[role="button"]:focus-visible,
[data-baseweb="select"] *:focus-visible,
[data-testid="stButton"] > button:focus-visible {
    outline: 2px solid #67e8f9 !important;
    outline-offset: 2px !important;
    box-shadow: none !important;
}

@media (max-width: 1180px) {
    [data-testid="stMetricValue"] { font-size: 1.28rem; }
    [data-testid="block-container"] { max-width: 100%; }
}

@media (max-width: 900px) {
    [data-testid="block-container"] {
        padding-left: 0.82rem;
        padding-right: 0.82rem;
        padding-top: 0.72rem;
    }
    .hero-shell { padding: 0.82rem 0.9rem; border-radius: 13px; align-items: center; }
    .hero-title { font-size: 1.58rem; line-height: 1.2; }
    .hero-meta { row-gap: 0.42rem; }
    .focus-chip {
        width: 100%;
        justify-content: space-between;
    }
    .ticker-track { animation-duration: 42s; gap: 28px; }
}

@media (max-width: 680px) {
    [data-testid="block-container"] { padding-bottom: 5.6rem; }
    .hero-shell {
        flex-direction: column;
        align-items: flex-start;
        gap: 0.75rem;
    }
    .hero-logo { width: 46px; height: 46px; font-size: 1.05rem; border-radius: 12px; }
    .hero-title-row { gap: 0.48rem; align-items: flex-end; }
    .hero-title { font-size: 1.4rem; line-height: 1.18; padding-bottom: 0.09em; }
    .hero-tag { font-size: 0.62rem; }
    .hero-meta { font-size: 0.71rem; }
    .hero-sep { display: none; }
    div[data-testid="stRadio"] label { padding: 0.18rem 0.58rem; }
    [data-testid="stButton"] > button { min-height: 44px; font-size: 0.84rem !important; }
}

@media (prefers-reduced-motion: reduce) {
    .ticker-track,
    .loop-state.running::before,
    [data-testid="stMetric"],
    [data-testid="stButton"] > button,
    .focus-chip {
        animation: none !important;
        transition: none !important;
        transform: none !important;
    }
}
</style>
""", unsafe_allow_html=True)

_ui_density_profile = settings_store.get("ui_density_profile", "Pro")
if _ui_density_profile not in ("Pro", "Airy"):
    _ui_density_profile = "Pro"

if _ui_density_profile == "Airy":
    st.markdown("""
    <style>
    [data-testid="block-container"] { max-width: 1440px; }
    [data-testid="stMarkdownContainer"] p { font-size: 0.95rem; line-height: 1.56; }
    [data-testid="stMetric"] { padding: 18px 22px; border-radius: 16px; }
    [data-testid="stMetricValue"] { font-size: 1.58rem; }
    [data-testid="stButton"] > button { min-height: 42px; font-size: 0.83rem !important; border-radius: 12px !important; }
    [data-testid="stSelectbox"] > div > div,
    [data-testid="stNumberInput"] input,
    [data-testid="stTextInput"] input,
    [data-testid="stMultiSelect"] > div > div { min-height: 42px; border-radius: 12px !important; }
    .hero-shell { padding: 1.1rem 1.3rem; border-radius: 20px; }
    .hero-title { font-size: 2rem; }
    .focus-strip { gap: 10px; margin: 12px 0 15px 0; }
    .focus-chip { padding: 8px 13px; font-size: 0.79rem; }
    .section-header { margin: 24px 0 13px 0; }
    .health-pill { padding: 0.24rem 0.66rem; font-size: 0.73rem; }
    </style>
    """, unsafe_allow_html=True)


# ── Helpers ────────────────────────────────────────────────────────────────────
def section(title, color="#22d3ee"):
    st.markdown(f'<div class="section-header"><span class="section-dot" style="background:{color}"></span>{title}</div>', unsafe_allow_html=True)

def alert(kind, text):
    icons = {"success":"▲","danger":"▼","neutral":"●","info":"ℹ"}
    st.markdown(f'<div class="alert alert-{kind}">{icons.get(kind,"")} {text}</div>', unsafe_allow_html=True)

def stat_card(label, value, color="#e2e8f0"):
    st.markdown(f'<div class="stat-card"><div class="stat-label">{label}</div><div class="stat-value" style="color:{color}">{value}</div></div>', unsafe_allow_html=True)

def focus_chips(items):
    chips = "".join(f'<span class="focus-chip"><b>{label}</b>{value}</span>' for label, value in items)
    st.markdown(f'<div class="focus-strip">{chips}</div>', unsafe_allow_html=True)

def notify(text: str, kind: str = "info"):
    """Non-blocking UX feedback with graceful fallback on older Streamlit versions."""
    if hasattr(st, "toast"):
        st.toast(text, icon={"success": "✅", "warning": "⚠️", "error": "⛔"}.get(kind, "ℹ️"))
    else:
        if kind == "success":
            st.success(text)
        elif kind == "warning":
            st.warning(text)
        elif kind == "error":
            st.error(text)
        else:
            st.info(text)

def module_stamp(label: str):
    st.markdown(
        f'<div class="module-stamp">{label} · Updated {time.strftime("%H:%M:%S")}</div>',
        unsafe_allow_html=True,
    )

def loading_skeleton(lines: int = 4):
    lines_html = "".join('<div class="skeleton-line"></div>' for _ in range(max(2, lines)))
    holder = st.empty()
    holder.markdown(f'<div class="skeleton-wrap">{lines_html}</div>', unsafe_allow_html=True)
    return holder

def render_health_strip(items: list[tuple[str, str, str]]):
    chips = "".join(
        f'<span class="health-pill {cls}"><span class="dot"></span>{label}: {value}</span>'
        for label, value, cls in items
    )
    st.markdown(f'<div class="health-strip">{chips}</div>', unsafe_allow_html=True)

_PANEL_META = [
    {"id": "overview", "label": "Overview", "icon": "◉"},
    {"id": "charts", "label": "Charts", "icon": "▦"},
    {"id": "positions", "label": "Positions", "icon": "◫"},
    {"id": "orders", "label": "Orders", "icon": "◎"},
    {"id": "events", "label": "Events", "icon": "✦"},
    {"id": "backtest", "label": "Backtest", "icon": "◬"},
    {"id": "watchlist", "label": "Watchlist", "icon": "☰"},
    {"id": "alerts", "label": "Alerts", "icon": "⚑"},
    {"id": "journal", "label": "Journal", "icon": "✎"},
    {"id": "log", "label": "Log", "icon": "⌘"},
]
_PANEL_BY_ID = {p["id"]: p["label"] for p in _PANEL_META}
_PANEL_BY_LABEL = {p["label"]: p["id"] for p in _PANEL_META}
_PANEL_GROUPS = {
    "Trade Desk": ["overview", "charts", "positions", "orders"],
    "Research": ["events", "backtest", "journal", "log"],
    "Setup": ["watchlist", "alerts"],
}
_PANEL_INFO = {
    "overview": {"desc": "Live signal board, focus symbol, and quick AI checks.", "accent": "#14b8a6", "tip": "Start here for a full market pulse."},
    "charts": {"desc": "Price action workspace with compare and layout modes.", "accent": "#38bdf8", "tip": "Use Dual layout for side-by-side symbol analysis."},
    "positions": {"desc": "Open holdings, risk context, and unrealized P&L tracking.", "accent": "#34d399", "tip": "Watch this panel when market volatility spikes."},
    "orders": {"desc": "Order flow, fills, and realized performance history.", "accent": "#f59e0b", "tip": "Validate execution quality and trade outcomes."},
    "events": {"desc": "Headline stream and event-scored signal overlays.", "accent": "#f97316", "tip": "Run event analysis before taking discretionary entries."},
    "backtest": {"desc": "Historical strategy testing and parameter exploration.", "accent": "#a78bfa", "tip": "Use this before changing live thresholds."},
    "watchlist": {"desc": "Manage symbols and curate your active trading universe.", "accent": "#22c55e", "tip": "Keep only high-conviction names for clarity."},
    "alerts": {"desc": "Configure and validate outbound alert channels.", "accent": "#ef4444", "tip": "Run test alerts after environment updates."},
    "journal": {"desc": "Decision history and closed-trade outcomes in one place.", "accent": "#06b6d4", "tip": "Review this weekly to improve discipline."},
    "log": {"desc": "System logs for monitoring and troubleshooting.", "accent": "#64748b", "tip": "Check this first if anything feels off."},
}

def _group_for_panel(panel_id: str) -> str:
    for group, panels in _PANEL_GROUPS.items():
        if panel_id in panels:
            return group
    return next(iter(_PANEL_GROUPS.keys()))

def render_workspace_focus(panel_id: str):
    meta = _PANEL_INFO.get(panel_id, {})
    panel_label = _PANEL_BY_ID.get(panel_id, "Overview")
    group = _group_for_panel(panel_id)
    desc = meta.get("desc", "Workspace panel")
    tip = meta.get("tip", "")
    accent = meta.get("accent", "#67e8f9")
    st.markdown(
        f'<div class="workspace-focus-card" style="--panel-accent:{accent}">'
        f'<div class="workspace-focus-head"><span class="workspace-focus-title">{panel_label}</span>'
        f'<span class="workspace-focus-badge">{group}</span></div>'
        f'<div class="workspace-focus-text">{desc}</div>'
        f'<div class="workspace-focus-tip">Tip: {tip}</div>'
        f'</div>',
        unsafe_allow_html=True,
    )

def render_panel_nav(active_panel_id: str) -> str:
    panel_ids = [p["id"] for p in _PANEL_META]
    panel_lookup = {p["id"]: p for p in _PANEL_META}
    if active_panel_id not in panel_ids:
        active_panel_id = "overview"
    if "workspace_panel_nav" not in st.session_state or st.session_state["workspace_panel_nav"] not in panel_ids:
        st.session_state["workspace_panel_nav"] = active_panel_id
    if "workspace_panel_group" not in st.session_state:
        st.session_state["workspace_panel_group"] = _group_for_panel(st.session_state["workspace_panel_nav"])

    group_names = list(_PANEL_GROUPS.keys())
    if st.session_state["workspace_panel_group"] not in group_names:
        st.session_state["workspace_panel_group"] = group_names[0]

    st.markdown('<div class="workspace-nav-note">Step 1: choose a lane. Step 2: choose a panel.</div>', unsafe_allow_html=True)
    nav_left, nav_right = st.columns([1.0, 2.4], gap="small")
    with nav_left:
        group_choice = st.selectbox("Lane", group_names, key="workspace_panel_group", label_visibility="collapsed")
    group_panels = _PANEL_GROUPS[group_choice]
    current_panel = st.session_state.get("workspace_panel_nav", active_panel_id)
    if current_panel not in group_panels:
        st.session_state["workspace_panel_nav"] = group_panels[0]

    with nav_right:
        selected_id = st.radio(
            "Workspace panel",
            group_panels,
            horizontal=True,
            label_visibility="collapsed",
            key="workspace_panel_nav",
            format_func=lambda pid: f'{panel_lookup[pid]["icon"]} {panel_lookup[pid]["label"]}',
        )
    return selected_id

def request_workspace_panel(panel_id: str):
    if panel_id not in _PANEL_BY_ID:
        return
    st.session_state["workspace_panel_requested"] = panel_id
    st.rerun()

def render_panel_quick_actions(panel_id: str):
    panel_ids = [p["id"] for p in _PANEL_META]
    if panel_id not in panel_ids:
        panel_id = panel_ids[0]
    idx = panel_ids.index(panel_id)
    prev_id = panel_ids[idx - 1] if idx > 0 else panel_ids[-1]
    next_id = panel_ids[(idx + 1) % len(panel_ids)]

    st.markdown('<div class="panel-quick-note">Quick actions</div>', unsafe_allow_html=True)
    qa_prev, qa_next, qa_refresh, qa_jump, qa_go = st.columns([0.95, 0.95, 0.95, 1.75, 0.6], gap="small")
    with qa_prev:
        if st.button("← Prev", key=f"qa_prev_{panel_id}", use_container_width=True, help=f"Go to {_PANEL_BY_ID[prev_id]}"):
            request_workspace_panel(prev_id)
    with qa_next:
        if st.button("Next →", key=f"qa_next_{panel_id}", use_container_width=True, help=f"Go to {_PANEL_BY_ID[next_id]}"):
            request_workspace_panel(next_id)
    with qa_refresh:
        if st.button("Refresh", key=f"qa_refresh_{panel_id}", use_container_width=True):
            st.rerun()
    with qa_jump:
        jump_target = st.selectbox(
            "Jump panel",
            panel_ids,
            index=idx,
            key=f"qa_jump_{panel_id}",
            format_func=lambda pid: _PANEL_BY_ID[pid],
            label_visibility="collapsed",
        )
    with qa_go:
        if st.button("Go", key=f"qa_go_{panel_id}", use_container_width=True) and jump_target != panel_id:
            request_workspace_panel(jump_target)

def render_market_snapshot(context_chips, health_items, portfolio_chips, tape_items):
    st.markdown('<div class="snapshot-note">Need a quick pulse? Open Market Snapshot.</div>', unsafe_allow_html=True)
    _first_snapshot_key = "market_snapshot_first_open_done"
    _snapshot_expanded = _first_snapshot_key not in st.session_state
    with st.expander("Market Snapshot", expanded=_snapshot_expanded):
        focus_chips(context_chips)
        render_health_strip(health_items)
        focus_chips(portfolio_chips)
        if tape_items:
            tape_html = "".join(
                f'<span class="ticker-item">'
                f'<span class="ticker-sym">{t["sym"]}</span>'
                f'<span class="ticker-price">${t["price"]:,.2f}</span>'
                f'<span class="{"ticker-up" if t["chg"] >= 0 else "ticker-down"}">'
                f'{"▲" if t["chg"] >= 0 else "▼"}{abs(t["chg"]):.2f}%</span>'
                f'</span>'
                for t in tape_items
            )
            st.markdown(
                f'<div class="ticker-wrap"><div class="ticker-track">{tape_html * 2}</div></div>',
                unsafe_allow_html=True,
            )
        else:
            st.caption("Trending ticker feed unavailable right now.")
    if _snapshot_expanded:
        st.session_state[_first_snapshot_key] = True

def apply_dashboard_preset(preset: str):
    payload = {}
    panel_id = None
    if preset == "Scalping":
        payload.update({
            "watch_source": "trending",
            "bar_timeframe": "1Min",
            "chart_layout": "Dual",
            "table_density": "Compact",
            "ui_density_profile": "Pro",
        })
        panel_id = "charts"
    elif preset == "Swing":
        payload.update({
            "watch_source": "my_list",
            "bar_timeframe": "1Day",
            "chart_layout": "Single",
            "table_density": "Comfortable",
            "ui_density_profile": "Airy",
        })
        panel_id = "overview"
    elif preset == "Backtest":
        payload.update({
            "bar_timeframe": "1Day",
            "chart_layout": "Single",
            "table_density": "Compact",
            "ui_density_profile": "Pro",
        })
        panel_id = "backtest"
    elif preset == "Risk":
        payload.update({
            "watch_source": "my_list",
            "bar_timeframe": "15Min",
            "chart_layout": "Single",
            "table_density": "Compact",
            "ui_density_profile": "Pro",
        })
        panel_id = "positions"

    payload["dashboard_preset"] = preset
    if panel_id:
        payload["dashboard_panel"] = _PANEL_BY_ID.get(panel_id, "Overview")
    settings_store.save(payload)
    if panel_id:
        st.session_state["workspace_panel_nav"] = panel_id
    st.rerun()

def event_card(label, score, confidence, reason):
    if score > 0:   cls, icon, color = "bullish", "▲", "#34d399"
    elif score < 0: cls, icon, color = "bearish", "▼", "#f87171"
    else:           cls, icon, color = "neutral",  "●", "#64748b"
    st.markdown(f"""<div class="event-card {cls}">
        <span style="color:{color};font-weight:700;font-size:0.9rem">{icon} {label}</span>
        &nbsp;<span style="color:#7f95b3;font-size:0.78rem">score <b style="color:{color}">{score:+d}</b> &nbsp;·&nbsp; confidence <b style="color:#7dd3fc">{confidence}</b></span>
        <div style="color:#cbd5e1;font-size:0.83rem;margin-top:6px;line-height:1.4">{reason}</div>
    </div>""", unsafe_allow_html=True)

_P = 'padding:8px 14px;vertical-align:middle'  # shared td padding

_SIGNAL_BADGES = {
    "BUY":  f'<td style="{_P};white-space:nowrap"><span style="background:#052e16;color:#34d399;border:1px solid #059669;padding:2px 12px;border-radius:20px;font-size:0.75rem;font-weight:700">▲ BUY</span></td>',
    "SELL": f'<td style="{_P};white-space:nowrap"><span style="background:#431407;color:#fdba74;border:1px solid #ea580c;padding:2px 12px;border-radius:20px;font-size:0.75rem;font-weight:700">▼ SELL</span></td>',
    "HOLD": f'<td style="{_P};white-space:nowrap"><span style="background:#1e293b;color:#cbd5e1;border:1px solid #334155;padding:2px 12px;border-radius:20px;font-size:0.75rem;font-weight:700">● HOLD</span></td>',
}
_STATUS_COLORS = {"FILLED":"#7dd3fc","CANCELED":"#fb923c","PENDING_NEW":"#f59e0b","NEW":"#f59e0b","PARTIALLY_FILLED":"#67e8f9","REJECTED":"#fb923c"}

def _cell_score(v):
    try:
        n = float(v)
        if n > 0:   color, prefix = "#7dd3fc", "+"
        elif n < 0: color, prefix = "#fdba74", ""
        else:       color, prefix = "#64748b", ""
        return f'<td style="{_P};color:{color};font-weight:700;text-align:center;white-space:nowrap">{prefix}{int(n)}</td>'
    except Exception:
        return f'<td style="{_P}">{v}</td>'

def _cell_pnl(v):
    s = str(v)
    color = "#7dd3fc" if not s.startswith("-") else "#fdba74"
    return f'<td style="{_P};color:{color};font-weight:600;font-family:monospace;white-space:nowrap">{s}</td>'

def _cell_rsi(v):
    try:
        n = float(v)
        color = "#fdba74" if n > 65 else ("#7dd3fc" if n < 35 else "#e2e8f0")
        return f'<td style="{_P};color:{color};white-space:nowrap">{v}</td>'
    except Exception:
        return f'<td style="{_P}">{v}</td>'

def _cell_pct(v):
    try:
        n = float(v)
        color = "#7dd3fc" if n >= 0 else "#fdba74"
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
    "Signal":   lambda v,s: _SIGNAL_BADGES.get(s, f'<td style="{_P};color:#fdba74">{s}</td>'),
    "Score":    lambda v,s: _cell_score(v),
    "side":     lambda v,s: f'<td style="{_P}"><span style="color:{"#34d399" if s.upper() in ("BUY","LONG") else "#fdba74"};font-weight:700">{s}</span></td>',
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
        f'color:{"#34d399" if "approve" in s.lower() else "#fdba74"};'
        f'background:{"#052e16" if "approve" in s.lower() else "#431407"};'
        f'border:1px solid {"#059669" if "approve" in s.lower() else "#ea580c"};'
        f'padding:1px 8px;border-radius:20px">'
        f'{"✓ OK" if "approve" in s.lower() else "✗ No"}</span></td>'
        if s not in ("—", "")
        else f'<td style="{_P};color:#334155;text-align:center;font-size:0.78rem">—</td>'
    ),
    **{k: (lambda v,s: f'<td style="{_P};color:#e2e8f0;font-family:monospace;white-space:nowrap">{s}</td>')
       for k in ["Price","price","avg_entry","current_price","filled_avg","value","entry","exit"]},
}

def html_table(rows, max_height=420, table_key=None, show_tools=True):
    if not rows:
        return

    cols = list(rows[0].keys())
    _sig = "|".join(cols)
    _sig_num = sum(ord(ch) for ch in _sig) % 100000
    table_key = table_key or f"tbl_{_sig_num}"

    _preset_density = settings_store.get("table_density", "Comfortable")
    _density_default_idx = 0 if _preset_density == "Compact" else 1

    if show_tools:
        cols_state_key = f"{table_key}_cols"
        schema_state_key = f"{table_key}_cols_schema"
        prev_schema = st.session_state.get(schema_state_key)
        prev_selected = st.session_state.get(cols_state_key)

        if prev_schema is None:
            st.session_state[schema_state_key] = list(cols)
        else:
            prev_schema_list = list(prev_schema)
            if prev_schema_list != cols:
                if isinstance(prev_selected, list):
                    merged_cols = [c for c in prev_selected if c in cols]
                    for c in cols:
                        if c not in prev_schema_list and c not in merged_cols:
                            merged_cols.append(c)
                    st.session_state[cols_state_key] = merged_cols or list(cols)
                st.session_state[schema_state_key] = list(cols)

        with st.expander("Table tools", expanded=False):
            t1, t2, t3 = st.columns([1.1, 1.3, 2.6])
            with t1:
                density = st.radio(
                    "Density",
                    ["Compact", "Comfortable"],
                    index=_density_default_idx,
                    key=f"{table_key}_density",
                    horizontal=True,
                )
            with t2:
                sticky_first = st.toggle("Sticky first column", value=True, key=f"{table_key}_sticky")
            with t3:
                visible_cols = st.multiselect(
                    "Visible columns",
                    options=cols,
                    default=cols,
                    key=f"{table_key}_cols",
                )
    else:
        density = "Comfortable"
        sticky_first = True
        visible_cols = cols

    if not visible_cols:
        visible_cols = cols

    if len(rows) > 220:
        df = pd.DataFrame(rows)
        df = df[[c for c in visible_cols if c in df.columns]]
        st.dataframe(df, use_container_width=True, height=max_height if max_height else 460, hide_index=True)
        st.caption(f"Virtualized table mode enabled ({len(rows)} rows).")
        return

    font_size = "0.79rem" if density == "Compact" else "0.85rem"
    row_bg = ("#0b1931", "#0e213f")

    header_cells = []
    for i, c in enumerate(visible_cols):
        sticky_style = ""
        if sticky_first and i == 0:
            sticky_style = "position:sticky;left:0;z-index:4;"
        header_cells.append(
            f'<th style="color:#7f95b3;font-size:0.68rem;font-weight:700;letter-spacing:0.1em;'
            f'text-transform:uppercase;padding:10px 14px;border-bottom:1px solid #2b4462;'
            f'white-space:nowrap;top:0;background:#081325;{sticky_style}">{c}</th>'
        )
    header = "".join(header_cells)

    body = ""
    for i, row in enumerate(rows):
        bg = row_bg[i % 2]
        cells_html = []
        for col_idx, c in enumerate(visible_cols):
            cell_html = _CELL_DISPATCH.get(
                c,
                lambda v, s: f'<td style="{_P};color:#cbd5e1;white-space:nowrap">{s}</td>'
            )(row.get(c), str(row.get(c, "")))
            if sticky_first and col_idx == 0 and cell_html.startswith('<td style="'):
                cell_html = cell_html.replace(
                    '<td style="',
                    f'<td style="position:sticky;left:0;z-index:1;background:{bg};',
                    1,
                )
            cells_html.append(cell_html)
        cells = "".join(cells_html)
        body += (
            f'<tr style="background:{bg}" '
            f'onmouseover="this.style.background=\'#173457\'" '
            f'onmouseout="this.style.background=\'{bg}\'">{cells}</tr>'
        )

    _height_style = f"max-height:{int(max_height)}px;" if max_height else ""
    st.markdown(
        f'<div style="border:1px solid #2b4362;border-radius:12px;overflow:auto;'
        f'{_height_style}margin-bottom:8px">'
        f'<table style="border-collapse:collapse;font-size:{font_size};white-space:nowrap;width:100%">'
        f'<thead><tr style="background:#081325">{header}</tr></thead>'
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
                sig = strategy.compute_signals(bars, timeframe=bar_timeframe)
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
    html_table(rows, max_height=220, table_key="screener_snapshot")


def render_control_deck():
    _saved_settings = settings_store.load()
    top_n = 10
    _preset_options = ["Scalping", "Swing", "Backtest", "Risk", "Custom"]

    _ws_options = ["my_list", "trending", "most_active", "gainers", "losers", "sector", "etf"]
    _ws_saved = settings_store.get("watch_source", "my_list")
    if _ws_saved not in _ws_options:
        _ws_saved = "my_list"
    watch_source = _ws_saved

    _tf_options = ["1Min", "5Min", "15Min", "1Hour", "1Day"]
    _tf_saved = settings_store.get("bar_timeframe", config.BAR_TIMEFRAME)
    _tf_saved = _tf_saved if _tf_saved in _tf_options else config.BAR_TIMEFRAME
    bar_timeframe = _tf_saved

    auto_refresh = st.session_state.get("auto_refresh_toggle", False)
    run_geo = bool(_saved_settings.get("run_geo", True))
    run_earnings = bool(_saved_settings.get("run_earnings", True))
    run_macro = bool(_saved_settings.get("run_macro", True))

    dry_run_ui = bool(_saved_settings.get("dry_run", config.DRY_RUN))
    shadow_mode = bool(_saved_settings.get("shadow_mode", getattr(config, "SHADOW_MODE", False)))
    allow_short = bool(_saved_settings.get("allow_short", config.ALLOW_SHORT))

    _sl_default = int(_saved_settings.get("sl_pct", config.STOP_LOSS_PCT) * 100)
    _tp_default = int(_saved_settings.get("tp_pct", config.TAKE_PROFIT_PCT) * 100)
    _daily_stop_default = int(_saved_settings.get("daily_loss_stop_pct", config.DAILY_LOSS_STOP_PCT) * 100)
    _sector_cap_default = int(_saved_settings.get("max_sector_exposure_pct", config.MAX_SECTOR_EXPOSURE_PCT) * 100)
    sl_pct = _sl_default / 100
    tp_pct = _tp_default / 100
    daily_loss_stop_pct = _daily_stop_default / 100
    max_sector_exposure_pct = _sector_cap_default / 100

    _corr_cap_default = bool(_saved_settings.get("enable_correlation_cap", config.ENABLE_CORRELATION_CAP))
    _max_corr_default = max(0.50, min(0.99, float(_saved_settings.get("max_correlation", config.MAX_CORRELATION))))
    _max_corr_positions_default = max(1, min(20, int(_saved_settings.get("max_correlated_positions", config.MAX_CORRELATED_POSITIONS))))
    _corr_lookback_default = max(20, min(365, int(_saved_settings.get("correlation_lookback_days", config.CORRELATION_LOOKBACK_DAYS))))
    enable_correlation_cap = _corr_cap_default
    max_correlation = _max_corr_default
    max_correlated_positions = _max_corr_positions_default
    correlation_lookback_days = _corr_lookback_default

    if not watchlist_store.load():
        for _sym in config.WATCHLIST:
            watchlist_store.add(_sym)
    watchlist = watchlist_store.load()

    section("Control Deck", "#38bdf8")
    with st.expander("Trading controls", expanded=False):
        p1, p2, p3 = st.columns([1.4, 1, 1.4])
        with p1:
            _preset_saved = settings_store.get("dashboard_preset", "Scalping")
            _preset_idx = _preset_options.index(_preset_saved) if _preset_saved in _preset_options else 0
            _preset_pick = st.selectbox("Layout preset", _preset_options, index=_preset_idx, key="preset_pick")
        with p2:
            if st.button("Apply Preset", use_container_width=True, key="preset_apply_btn"):
                apply_dashboard_preset(_preset_pick)
        with p3:
            if st.button("Save Current as Custom", use_container_width=True, key="preset_save_btn"):
                settings_store.save({
                    "dashboard_preset": "Custom",
                    "watch_source": watch_source,
                    "bar_timeframe": bar_timeframe,
                    "dry_run": dry_run_ui,
                    "shadow_mode": shadow_mode,
                    "allow_short": allow_short,
                    "ui_density_profile": settings_store.get("ui_density_profile", "Pro"),
                })
                notify("Current control layout saved as Custom.", kind="success")

        st.caption("Work left to right: define symbols, set execution mode, then tune risk limits.")
        universe_tab, execution_tab, risk_tab = st.tabs(["1. Universe", "2. Execution", "3. Risk & Safety"])

        with universe_tab:
            u_left, u_mid = st.columns([1.55, 1.15])
            with u_left:
                watch_source = st.selectbox(
                    "Watchlist source",
                    _ws_options,
                    index=_ws_options.index(_ws_saved),
                    format_func=lambda x: {
                        "my_list": "My List",
                        "trending": "🔥 Trending Now",
                        "most_active": "Most Active",
                        "gainers": "Top Gainers",
                        "losers": "Top Losers",
                        "sector": "Sector + ETF",
                        "etf": "ETF Themes",
                    }[x],
                )
                if watch_source != _ws_saved:
                    settings_store.save({"watch_source": watch_source})

                if watch_source == "my_list":
                    _my_wl = watchlist_store.load()
                    _add_col, _btn_col = st.columns([3, 1])
                    with _add_col:
                        _new_sym = st.text_input("Add ticker", placeholder="GOOG", key="wl_add").upper().strip()
                    with _btn_col:
                        if st.button("Add", use_container_width=True, key="wl_add_btn") and _new_sym:
                            watchlist_store.add(_new_sym)
                            notify(f"Added {_new_sym} to watchlist.", kind="success")
                            st.rerun()
                    if _my_wl:
                        for _sym in _my_wl[:8]:
                            _c1, _c2 = st.columns([4, 1])
                            _c1.markdown(f'<div style="padding:4px 0;color:#7dd3fc;font-weight:700;font-size:0.85rem">{_sym}</div>', unsafe_allow_html=True)
                            if _c2.button("Remove", key=f"rm_{_sym}", help=f"Remove {_sym}"):
                                watchlist_store.remove(_sym)
                                notify(f"Removed {_sym}.", kind="warning")
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
                    top_n = st.slider("Top N", 5, 30, 15, key="watch_topn_trending")
                    watchlist = screener.build_watchlist("trending", top_n=top_n)
                else:
                    top_n = st.slider("Top N", 5, 25, 10, key="watch_topn_other")
                    watchlist = screener.build_watchlist(watch_source, top_n=top_n)

            with u_mid:
                bar_timeframe = st.selectbox(
                    "Chart timeframe",
                    _tf_options,
                    index=_tf_options.index(_tf_saved),
                    format_func=lambda x: {"1Min": "1 Min", "5Min": "5 Min", "15Min": "15 Min", "1Hour": "1 Hour", "1Day": "1 Day"}[x],
                )
                if bar_timeframe != _tf_saved:
                    settings_store.save({"bar_timeframe": bar_timeframe})

                auto_refresh = st.toggle("Auto-refresh (30s)", value=auto_refresh, key="auto_refresh_toggle")
                if st.button("Refresh Now", use_container_width=True, key="refresh_now_btn"):
                    st.rerun()

                run_geo = st.toggle("Geopolitical events", value=run_geo, key="run_geo_toggle")
                run_earnings = st.toggle("Earnings events", value=run_earnings, key="run_earnings_toggle")
                run_macro = st.toggle("Macro events", value=run_macro, key="run_macro_toggle")
                settings_store.save({"run_geo": run_geo, "run_earnings": run_earnings, "run_macro": run_macro})

        with execution_tab:
            e_left, e_mid = st.columns([1.1, 1.3])
            with e_left:
                dry_run_ui = st.toggle("Dry Run", value=dry_run_ui, key="dry_run_toggle")
                shadow_mode = st.toggle("Shadow Mode", value=shadow_mode, key="shadow_mode_toggle")
                allow_short = st.toggle("Allow Short Selling", value=allow_short, key="allow_short_toggle")
                settings_store.save({
                    "dry_run": dry_run_ui,
                    "shadow_mode": shadow_mode,
                    "allow_short": allow_short,
                })

                if st.button("Close All Positions", use_container_width=True, key="close_all_positions_btn"):
                    try:
                        positions = broker.get_positions()
                        for p in positions:
                            broker.close_position(p["symbol"])
                        notify(f"Closed {len(positions)} position(s).", kind="success")
                        st.rerun()
                    except Exception as e:
                        st.error(str(e))

            with e_mid:
                manual_symbol = st.selectbox(
                    "Manual symbol",
                    watchlist if watchlist else config.WATCHLIST,
                    key="manual_symbol_ctrl",
                )
                manual_qty = st.number_input("Manual quantity", min_value=1, value=1, step=1, key="manual_qty_ctrl")
                _buy_col, _sell_col = st.columns(2)
                with _buy_col:
                    if st.button("BUY", use_container_width=True, type="primary", key="manual_buy_btn"):
                        try:
                            if shadow_mode:
                                _bars = broker.get_bars(manual_symbol)
                                _px = float(_bars[-1]["c"]) if _bars else 0.0
                                shadow_book.record_intent(manual_symbol, "buy", manual_qty, _px, "manual order", 0)
                                shadow_book.open_position(manual_symbol, "long", manual_qty, _px, "manual order", 0)
                                notify("Shadow BUY recorded.", kind="success")
                            elif dry_run_ui:
                                notify("Dry run enabled: no order placed.", kind="warning")
                            else:
                                order = broker.place_market_order(manual_symbol, manual_qty, "buy")
                                notify(f"Order placed #{order['id'][:8]}.", kind="success")
                        except Exception as e:
                            st.error(str(e))
                with _sell_col:
                    if st.button("SELL", use_container_width=True, key="manual_sell_btn"):
                        try:
                            if shadow_mode:
                                _bars = broker.get_bars(manual_symbol)
                                _pos = shadow_book.get_position(manual_symbol)
                                _px = float(_bars[-1]["c"]) if _bars else float(_pos["entry_price"]) if _pos else 0.0
                                trade = shadow_book.close_position(manual_symbol, _px, reason="manual close")
                                notify("Shadow position closed." if trade else "No shadow position to close.", kind="success" if trade else "warning")
                            elif dry_run_ui:
                                notify("Dry run enabled: no order placed.", kind="warning")
                            else:
                                broker.close_position(manual_symbol)
                                notify("Position close submitted.", kind="success")
                        except Exception as e:
                            st.error(str(e))

        with risk_tab:
            r_left, r_mid, r_right = st.columns([1.25, 1.05, 1.0])
            with r_left:
                sl_pct = st.slider("Stop Loss %", 0, 20, _sl_default, key="risk_sl_pct") / 100
                tp_pct = st.slider("Take Profit %", 0, 50, _tp_default, key="risk_tp_pct") / 100
                daily_loss_stop_pct = st.slider("Daily Loss Stop %", 0, 20, _daily_stop_default, key="risk_daily_loss_stop") / 100
                max_sector_exposure_pct = st.slider("Sector Cap %", 0, 100, _sector_cap_default, key="risk_sector_cap") / 100
            with r_mid:
                enable_correlation_cap = st.toggle("Enable Correlation Cap", value=_corr_cap_default, key="risk_corr_cap")
                max_correlation = st.slider("Max Correlation", 0.50, 0.99, _max_corr_default, 0.01, key="risk_max_corr")
                max_correlated_positions = st.number_input(
                    "Max Correlated Holdings",
                    min_value=1,
                    max_value=20,
                    value=_max_corr_positions_default,
                    step=1,
                    key="risk_max_corr_holdings",
                )
                correlation_lookback_days = st.slider("Correlation Lookback", 20, 365, _corr_lookback_default, 5, key="risk_corr_lookback")
            with r_right:
                if st.button("Reset Risk Halt", use_container_width=True, key="risk_reset_halt_btn"):
                    risk.reset_halts(reset_peak=False)
                    notify("Risk halts reset.", kind="success")
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

_run_label = "Running" if _loop_running else "Stopped"
_run_class = "running" if _loop_running else "stopped"

st.markdown(f"""
<div class="hero-shell">
  <div class="hero-logo">TA</div>
  <div class="hero-copy">
    <div class="hero-title-row">
      <span class="hero-title">Trade<span class="hero-title-accent">Agent</span></span>
      <span class="hero-tag">AI Trading System</span>
    </div>
    <div class="hero-meta">
      <span>Agent <b>{provider_label}</b></span>
      <span class="hero-sep">•</span>
      <span>Loop <span class="loop-state {_run_class}">{_run_label}</span></span>
      <span class="hero-sep">•</span>
      <span class="hero-time">{time.strftime("%Y-%m-%d  %H:%M")}</span>
    </div>
  </div>
</div>
""", unsafe_allow_html=True)

# ── Trending ticker tape (always live, independent of watchlist selection) ──────
_tape_items = _fetch_trending_tape(20)

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

_context_snapshot_chips = [
    ("Watchlist", f"{watch_source.replace('_', ' ').title()} · {len(watchlist)} names"),
    ("Timeframe", bar_timeframe),
    ("Risk", f"SL {sl_pct*100:.0f}% / TP {tp_pct*100:.0f}%"),
    ("Mode", f"{_mode_label} · {'Dry Run' if control_state['dry_run_ui'] else 'Active'}"),
    ("Events", f"Geo {'On' if run_geo else 'Off'} · Earnings {'On' if run_earnings else 'Off'}"),
]

# ── Market status ──────────────────────────────────────────────────────────────
_is_open = None
_market_status_text = "Unavailable"
_market_status_class = "warn"
try:
    from alpaca.trading.client import TradingClient as _TC
    _clock = _TC(config.ALPACA_API_KEY, config.ALPACA_SECRET_KEY, paper=True).get_clock()
    _is_open     = _clock.is_open
    _next_open   = _clock.next_open.strftime("%Y-%m-%d %H:%M ET")
    _next_close  = _clock.next_close.strftime("%H:%M ET")
    if _is_open:
        _market_status_text = f"Open · close {_next_close}"
        _market_status_class = "ok"
    else:
        _market_status_text = f"Closed · open {_next_open}"
        _market_status_class = "warn"
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
_orders_all = []
_today_pnl = 0.0
_today_wins = 0
_today_losses = 0
_total_today_trades = 0
_win_rate_today = 0.0
_live_fig = None
try:
    _today = time.strftime("%Y-%m-%d")
    if getattr(config, "SHADOW_MODE", False):
        _shadow = shadow_book.summary()
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

    _live_fig = charts.live_equity_curve(_orders_all) if _orders_all else None
except Exception:
    pass

_health_snapshot_items = [
    ("Broker", "Connected", "ok"),
    ("Market", _market_status_text, _market_status_class),
    ("Drawdown Guard", "Halted" if dd_state["halted"] else "Normal", "err" if dd_state["halted"] else "ok"),
    ("Daily Guard", "Halted" if day_state["halted"] else "Normal", "err" if day_state["halted"] else "ok"),
    ("Mode", _mode_label, "warn" if _mode_label in ("Paper", "Shadow") else "ok"),
]
_execution_state = "Shadow" if control_state["shadow_mode"] else ("Dry Run" if control_state["dry_run_ui"] else "Live")
_portfolio_snapshot_chips = [
    ("Portfolio", f"${account['portfolio_value']:,.0f}"),
    ("Cash", f"${account['cash']:,.0f}"),
    ("Buying Power", f"${account['buying_power']:,.0f}"),
    ("Today", f"${_today_pnl:+,.2f}"),
    ("Trades", str(_total_today_trades)),
    ("Win Rate", f"{_win_rate_today:.0f}%" if _total_today_trades else "—"),
    ("Execution", _execution_state),
]
render_market_snapshot(_context_snapshot_chips, _health_snapshot_items, _portfolio_snapshot_chips, _tape_items)

# ── Workspace ──────────────────────────────────────────────────────────────────
section("Workspace", "#22d3ee")
_saved_panel_label = settings_store.get("dashboard_panel", "Overview")
_saved_panel_id = _PANEL_BY_LABEL.get(_saved_panel_label, "overview")
if _saved_panel_id not in _PANEL_BY_ID:
    _saved_panel_id = "overview"

active_panel_id = st.session_state.get("workspace_panel_nav", _saved_panel_id)
if active_panel_id not in _PANEL_BY_ID:
    active_panel_id = _saved_panel_id

_requested_panel_id = st.session_state.pop("workspace_panel_requested", None)
if _requested_panel_id in _PANEL_BY_ID:
    active_panel_id = _requested_panel_id
    st.session_state["workspace_panel_nav"] = _requested_panel_id
    st.session_state["workspace_panel_group"] = _group_for_panel(_requested_panel_id)

_ws_nav_col, _ws_focus_col = st.columns([2.1, 1.15], gap="large")
with _ws_nav_col:
    active_panel_id = render_panel_nav(active_panel_id)
with _ws_focus_col:
    render_workspace_focus(active_panel_id)

active_panel = _PANEL_BY_ID[active_panel_id]
if _saved_panel_label != active_panel:
    settings_store.save({"dashboard_panel": active_panel})

st.markdown('<div class="workspace-subnote">Step 3: tune display preferences only when needed.</div>', unsafe_allow_html=True)
with st.expander("View preferences", expanded=False):
    _tool_l, _tool_m, _tool_n = st.columns(3)
    with _tool_l:
        _density_saved = settings_store.get("table_density", "Comfortable")
        _density_idx = 0 if _density_saved == "Compact" else 1
        _density_pick = st.selectbox("Table view", ["Compact", "Comfortable"], index=_density_idx, key="workspace_table_density")
        if _density_pick != _density_saved:
            settings_store.save({"table_density": _density_pick})
            st.rerun()
    with _tool_m:
        _layout_saved = settings_store.get("chart_layout", "Single")
        _layout_opts = ["Single", "Split", "Dual"]
        _layout_idx = _layout_opts.index(_layout_saved) if _layout_saved in _layout_opts else 0
        _layout_pick = st.selectbox("Chart canvas", _layout_opts, index=_layout_idx, key="workspace_chart_layout")
        if _layout_pick != _layout_saved:
            settings_store.save({"chart_layout": _layout_pick})
            st.rerun()
    with _tool_n:
        _ui_saved = settings_store.get("ui_density_profile", "Pro")
        _ui_opts = ["Pro", "Airy"]
        _ui_idx = _ui_opts.index(_ui_saved) if _ui_saved in _ui_opts else 0
        _ui_pick = st.selectbox("Interface style", _ui_opts, index=_ui_idx, key="workspace_ui_density")
        if _ui_pick != _ui_saved:
            settings_store.save({"ui_density_profile": _ui_pick})
            st.rerun()
st.markdown(f'<div class="workspace-active-chip">Active panel <b>{active_panel}</b></div>', unsafe_allow_html=True)


def render_overview_panel():
    if not watchlist:
        alert("neutral", "No symbols in watchlist.")
        return

    module_stamp("Overview")
    section("Overview Desk", "#14b8a6")
    render_panel_quick_actions("overview")
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
    _ov_skeleton = loading_skeleton(4)
    signal_cache, signal_rows = build_signal_snapshot(watchlist, bar_timeframe, run_agent=run_agent_scan)
    _ov_skeleton.empty()
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

    _overview_board_height = 620
    _overview_chart_height = 340
    _overview_reason_height = 68

    left, right = st.columns([1.05, 1.35], gap="large")
    with left:
        section("Signal Board", "#34d399")
        html_table(signal_rows, max_height=_overview_board_height, table_key="overview_signal_board")

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
            _sig = signal_cache.get(detail_sym) or strategy.compute_signals(_bars, timeframe=bar_timeframe)
            _rsi_val = _sig.get("rsi")
            _price_val = _sig.get("price")

            _m1, _m2, _m3, _m4, _m5 = st.columns(5, gap="small")
            _m1.metric("Price", f"${_price_val:,.2f}" if _price_val else "—")
            _m2.metric("Score", f"{_sig['score']:+d}")
            _m3.metric("RSI", f"{_rsi_val:.1f}" if _rsi_val else "—")
            _m4.metric("Signal", _sig["signal"].upper())
            _m5.metric("Regime", str(_sig.get("regime", "range")).replace("_", " ").title())

            st.markdown(
                f'<div style="background:#0f172b;border:1px solid #1e293b;border-left:3px solid #38bdf8;'
                f'border-radius:8px;padding:10px 16px;color:#94a3b8;font-size:0.85rem;margin:4px 0 12px 0;'
                f'height:{_overview_reason_height}px;overflow:auto;">'
                f'{_sig["reason"]}</div>',
                unsafe_allow_html=True,
            )

            _fig = charts.candlestick(_bars, detail_sym, _sig)
            _fig.update_layout(height=_overview_chart_height, margin=dict(l=16, r=16, t=40, b=18))
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

        except Exception as _e:
            alert("danger", f"Detail panel error: {_e}")

    if _live_fig:
        with st.expander("Live Equity Curve", expanded=False):
            _mini_fig = go.Figure(_live_fig)
            _mini_fig.update_layout(height=240, margin=dict(l=16, r=16, t=30, b=12))
            st.plotly_chart(_mini_fig, use_container_width=True)


def render_charts_panel():
    if not watchlist:
        alert("neutral", "No symbols in watchlist.")
        return
    module_stamp("Chart Studio")
    section("Chart Studio", "#38bdf8")
    render_panel_quick_actions("charts")
    _tf_options = ["1Min", "5Min", "15Min", "1Hour", "1Day"]
    _layout_saved = settings_store.get("chart_layout", "Single")
    _layout_opts = ["Single", "Split", "Dual"]
    _layout_idx = _layout_opts.index(_layout_saved) if _layout_saved in _layout_opts else 0

    col1, col2, col3 = st.columns([1.8, 1.2, 1.0])
    with col1:
        chart_symbol = st.selectbox("Symbol", watchlist, key="chart_sym")
    with col2:
        chart_tf = st.radio(
            "Timeframe",
            _tf_options,
            index=_tf_options.index(bar_timeframe) if bar_timeframe in _tf_options else 0,
            key="chart_tf",
            horizontal=True,
        )
    with col3:
        chart_layout = st.selectbox("Layout", _layout_opts, index=_layout_idx, key="chart_layout_pick")
        if chart_layout != _layout_saved:
            settings_store.save({"chart_layout": chart_layout})

    compare_symbol = None
    if chart_layout == "Dual":
        _compare_candidates = [s for s in watchlist if s != chart_symbol]
        compare_symbol = st.selectbox(
            "Compare symbol",
            _compare_candidates if _compare_candidates else [chart_symbol],
            key="chart_compare_sym",
        )
        overlay_compare = False
        overlay_symbol = None
    else:
        overlay_compare = st.toggle("Overlay comparison", value=False, key="chart_overlay_toggle")
        overlay_symbol = None
        if overlay_compare:
            _overlay_candidates = [s for s in watchlist if s != chart_symbol]
            overlay_symbol = st.selectbox(
                "Overlay symbol",
                _overlay_candidates if _overlay_candidates else [chart_symbol],
                key="chart_overlay_sym",
            )

    _skeleton = loading_skeleton(5)
    with st.spinner(f"Loading {chart_symbol} bars..."):
        try:
            bars = broker.get_bars(chart_symbol, timeframe=chart_tf)
            sig = strategy.compute_signals(bars, timeframe=chart_tf)
            fig = charts.candlestick(bars, chart_symbol, sig)
            if overlay_compare and overlay_symbol and overlay_symbol != chart_symbol:
                _overlay_bars = broker.get_bars(overlay_symbol, timeframe=chart_tf)
                if _overlay_bars:
                    _base = float(_overlay_bars[0]["c"]) if float(_overlay_bars[0]["c"]) != 0 else 1.0
                    _x = [b["t"] for b in _overlay_bars]
                    _y = [float(b["c"]) / _base * 100 for b in _overlay_bars]
                    fig.add_trace(
                        go.Scatter(
                            x=_x,
                            y=_y,
                            mode="lines",
                            name=f"{overlay_symbol} %idx",
                            line=dict(color="#f59e0b", width=1.8, dash="dot"),
                            yaxis="y2",
                        )
                    )
                    fig.update_layout(
                        yaxis2=dict(
                            title=f"{overlay_symbol} %",
                            overlaying="y",
                            side="right",
                            showgrid=False,
                            color="#f59e0b",
                        )
                    )
            fig.update_layout(height=440, margin=dict(l=16, r=16, t=40, b=18))
            _skeleton.empty()

            if chart_layout == "Single":
                st.plotly_chart(fig, use_container_width=True)
            elif chart_layout == "Split":
                st.plotly_chart(fig, use_container_width=True)
                if _live_fig:
                    _split_eq = go.Figure(_live_fig)
                    _split_eq.update_layout(height=260, margin=dict(l=16, r=16, t=30, b=12))
                    st.plotly_chart(_split_eq, use_container_width=True)
                else:
                    st.caption("Portfolio equity curve unavailable.")
            else:
                c_left, c_right = st.columns(2)
                with c_left:
                    st.plotly_chart(fig, use_container_width=True)
                with c_right:
                    _cmp_bars = broker.get_bars(compare_symbol, timeframe=chart_tf)
                    _cmp_sig = strategy.compute_signals(_cmp_bars, timeframe=chart_tf)
                    _cmp_fig = charts.candlestick(_cmp_bars, compare_symbol, _cmp_sig)
                    _cmp_fig.update_layout(height=440, margin=dict(l=16, r=16, t=40, b=18))
                    st.plotly_chart(_cmp_fig, use_container_width=True)

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
            _skeleton.empty()
            alert("danger", f"Chart error: {e}")

    if _live_fig:
        with st.expander("Portfolio Equity Curve", expanded=False):
            _chart_fig = go.Figure(_live_fig)
            _chart_fig.update_layout(height=260, margin=dict(l=16, r=16, t=30, b=12))
            st.plotly_chart(_chart_fig, use_container_width=True)


def render_positions_panel():
    module_stamp("Positions")
    section("Open Positions", "#38bdf8")
    render_panel_quick_actions("positions")
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
            html_table(rows, max_height=460, table_key="positions_open")
        else:
            alert("neutral", "No open positions.")
    except Exception as e:
        st.error(f"Failed to load positions: {e}")


def render_orders_panel():
    module_stamp("Orders")
    section("Orders & Fills", "#f59e0b")
    render_panel_quick_actions("orders")
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
                html_table(rows, max_height=260, table_key="orders_shadow_closed")
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
                    html_table(rows, max_height=340, table_key="orders_shadow_intents")
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
                html_table(realized, max_height=240, table_key="orders_realized")

            section("All Orders", "#64748b")
            for o in orders:
                o["side"] = o["side"].upper()
                o["filled_avg"] = f"${o['filled_avg']:,.2f}" if o["filled_avg"] else "—"
                o["value"] = f"${o['value']:,.2f}" if o["value"] else "—"
            html_table(orders, max_height=380, table_key="orders_all")
    except Exception as e:
        st.error(f"Failed to load orders: {e}")


def render_events_panel():
    if not watchlist:
        alert("neutral", "No symbols in watchlist.")
        return
    module_stamp("Events")
    section("News & Event Flow", "#f59e0b")
    render_panel_quick_actions("events")
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
            html_table(_news_rows, max_height=280, table_key="events_news")
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

    section("LLM Event Analysis", "#7dd3fc")
    if not config.USE_AGENT:
        alert("info", "Set AGENT_PROVIDER=claude or openai in .env to enable LLM event analysis.")
    else:
        if st.button(f"Analyse with {provider_label}", key="events_agent", type="primary"):
            with st.spinner(f"{provider_label} scoring headlines..."):
                ev_result = events.get_event_score(event_symbol, run_earnings=run_earnings, run_geo=run_geo, run_macro=run_macro)
            try:
                _event_bars = broker.get_bars(event_symbol, timeframe=bar_timeframe)
                quant = strategy.compute_signals(_event_bars, timeframe=bar_timeframe)
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
    module_stamp("Backtest")
    section("Backtest Studio", "#38bdf8")
    render_panel_quick_actions("backtest")
    bl, bm, bn, br = st.columns([2, 1, 1, 1])
    with bl:
        bt_symbol = st.selectbox("Symbol", watchlist, key="bt_sym", label_visibility="collapsed")
    with bm:
        bt_tf = st.selectbox("Timeframe", ["1Min", "5Min", "15Min", "1Hour", "1Day"], index=4, key="bt_tf", label_visibility="collapsed")
    with bn:
        _bt_lookback_opts = {"5d": 5, "20d": 20, "60d": 60, "180d": 180, "1y": 365, "2y": 730}
        _bt_min_lookback = {"1Min": 20, "5Min": 20, "15Min": 60, "1Hour": 180, "1Day": 365}
        _bt_lb_keys = list(_bt_lookback_opts.keys())
        _bt_min_days = _bt_min_lookback.get(bt_tf, 20)
        _bt_valid_keys = [k for k, v in _bt_lookback_opts.items() if v >= _bt_min_days]
        bt_lookback_label = st.selectbox("Lookback", _bt_valid_keys, key="bt_lookback2", label_visibility="collapsed")
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
                html_table(_display_trades, max_height=320, table_key="backtest_trades")

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
                html_table([{k: v for k, v in f.items() if k != "folds"} for f in wf["folds"]], max_height=260, table_key="backtest_wf")

    with st.expander("Expanding Walk-Forward Validation", expanded=False):
        st.caption("Training window grows with each fold — mirrors live deployment more realistically than fixed folds.")
        ewf_c1, ewf_c2, ewf_c3 = st.columns([2, 1, 1])
        with ewf_c1:
            ewf_sym = st.selectbox("Symbol", watchlist, key="ewf_sym", label_visibility="collapsed")
        with ewf_c2:
            ewf_tf = st.selectbox("Timeframe", ["1Day", "1Hour"], key="ewf_tf", label_visibility="collapsed")
        with ewf_c3:
            run_ewf = st.button("Expanding WF", type="primary", use_container_width=True)
        if run_ewf:
            with st.spinner(f"Running expanding walk-forward on {ewf_sym}..."):
                ewf = backtest.walk_forward_expanding(ewf_sym, timeframe=ewf_tf)
            if "error" in ewf:
                alert("danger", ewf["error"])
            else:
                ewf_m1, ewf_m2, ewf_m3, ewf_m4 = st.columns(4)
                ewf_m1.metric("Avg OOS Return", f"{ewf['avg_return_pct']:+.2f}%")
                ewf_m2.metric("Avg Sharpe", ewf["avg_sharpe"])
                ewf_m3.metric("Avg Win Rate", f"{ewf['avg_win_rate']:.1f}%")
                ewf_m4.metric("Profitable Folds", ewf["profitable_folds"])
                html_table(
                    [{k: v for k, v in f.items() if k not in ("folds",)} for f in ewf["folds"]],
                    max_height=260,
                    table_key="backtest_expanding_wf",
                )

    with st.expander("Parameter Optimisation", expanded=False):
        st.caption("Searches threshold, stop loss, and take profit combinations ranked by Sharpe ratio.")
        opt_c1, opt_c2, opt_c3, opt_c4 = st.columns([2, 1, 1, 1])
        with opt_c1:
            opt_sym = st.selectbox("Symbol", watchlist, key="opt_sym", label_visibility="collapsed")
        with opt_c2:
            opt_tf = st.selectbox("Timeframe", ["1Min", "5Min", "15Min", "1Hour", "1Day"], index=4, key="opt_tf2", label_visibility="collapsed")
        with opt_c3:
            _opt_lb_opts = {"5d": 5, "20d": 20, "60d": 60, "180d": 180, "1y": 365, "2y": 730}
            _opt_min_lookback = {"1Min": 20, "5Min": 20, "15Min": 60, "1Hour": 180, "1Day": 365}
            _opt_min_days = _opt_min_lookback.get(opt_tf, 20)
            _opt_valid_keys = [k for k, v in _opt_lb_opts.items() if v >= _opt_min_days]
            opt_lb_label = st.selectbox("Lookback", _opt_valid_keys, key="opt_lb2", label_visibility="collapsed")
            opt_lb_days = _opt_lb_opts[opt_lb_label]
        with opt_c4:
            run_opt = st.button("Optimise", type="primary", use_container_width=True)
        if run_opt:
            with st.spinner(f"Grid searching {opt_sym} · {opt_tf} · {opt_lb_label}..."):
                opt = backtest.optimize(opt_sym, timeframe=opt_tf, lookback_days=opt_lb_days)
            if "error" in opt:
                alert("danger", opt["error"])
                st.caption("Tip: Try a shorter lookback or lower timeframe — optimizer needs enough trades to evaluate.")
            else:
                best = opt["best"]
                alert("success", f"Best: threshold={best['threshold']} · SL={best['sl_mult']} · TP={best['tp_mult']} · Sharpe {best['sharpe']} · {best['trades']} trades")
                html_table(opt["results"], max_height=320, table_key="backtest_opt_results")


def render_watchlist_panel():
    module_stamp("Watchlist")
    section("Watchlist Manager", "#34d399")
    render_panel_quick_actions("watchlist")
    _wl_all = watchlist_store.load()
    if _wl_all:
        html_table([{"Symbol": s} for s in _wl_all], max_height=320, table_key="watchlist_symbols")
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
    module_stamp("Alerts")
    section("Alert Configuration", "#f87171")
    render_panel_quick_actions("alerts")
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
    module_stamp("Journal")
    section("Trade Journal", "#67e8f9")
    render_panel_quick_actions("journal")
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
            html_table(dec_rows, max_height=380, table_key="journal_decisions")

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
            html_table(out_rows, max_height=340, table_key="journal_outcomes")
        elif decisions:
            alert("neutral", "No closed-trade outcomes yet — will appear after first stop-loss or take-profit.")

    except Exception as _je:
        st.error(f"Journal error: {_je}")


def render_log_panel():
    module_stamp("Log")
    section("Trade Log", "#64748b")
    render_panel_quick_actions("log")
    try:
        log_lc, log_rc = st.columns([3, 1])
        with log_lc:
            log_filter = st.selectbox("Level", ["ALL", "ERROR", "WARNING", "INFO"], label_visibility="collapsed", key="log_level")
        with log_rc:
            log_lines = st.slider("Lines", 20, 200, 60, key="log_lines_n")

        with open("trade.log") as f:
            lines = list(deque(f, maxlen=max(400, log_lines * 8)))

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
