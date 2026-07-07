"""Plotly chart helpers — themed to match the dashboard glass system."""
import plotly.graph_objects as go
from plotly.subplots import make_subplots
import pandas as pd
import numpy as np

# Palette mirrors dashboard.py :root tokens. Backgrounds are transparent so
# charts inherit the glass pane behind [data-testid="stPlotlyChart"] instead
# of rendering as opaque slate rectangles.
_BG      = "rgba(0,0,0,0)"
_GRID    = "rgba(129, 161, 202, 0.13)"       # --glass-border, faded
_TEXT    = "#b9c9df"                          # --text-soft
_TICK    = "#7f95b3"                          # --text-dim
_ACCENT  = "#22d3ee"                          # --accent
_ACCENT2 = "#38bdf8"                          # --accent-2
_UP      = "#34d399"                          # --success
_DOWN    = "#fb7185"                          # --danger
_FONT    = {"color": _TEXT, "family": "Manrope, sans-serif", "size": 11}


def _base_layout(**kwargs) -> dict:
    base = {
        "paper_bgcolor": _BG,
        "plot_bgcolor":  _BG,
        "font":          _FONT,
        "legend":        {"bgcolor": "rgba(0,0,0,0)", "font": {"size": 10, "color": _TICK}},
        "margin":        {"l": 0, "r": 0, "t": 30, "b": 0},
        "hoverlabel": {
            "bgcolor": "rgba(10, 23, 44, 0.94)",
            "bordercolor": "rgba(129, 161, 202, 0.35)",
            "font": {"family": "JetBrains Mono, monospace", "size": 11, "color": "#e8eef9"},
        },
    }
    base.update(kwargs)
    return base


def _axis_style() -> dict:
    return {"gridcolor": _GRID, "zerolinecolor": _GRID, "tickfont": {"color": _TICK}}


def candlestick(bars: list[dict], symbol: str, signals: dict | None = None) -> go.Figure:
    if not bars:
        return go.Figure()

    df = pd.DataFrame(bars)
    df["t"] = pd.to_datetime(df["t"])

    fig = make_subplots(
        rows=3, cols=1, shared_xaxes=True,
        row_heights=[0.6, 0.2, 0.2], vertical_spacing=0.03,
    )

    # Candlestick
    fig.add_trace(go.Candlestick(
        x=df["t"], open=df["o"], high=df["h"], low=df["l"], close=df["c"],
        name=symbol,
        increasing_line_color=_UP, decreasing_line_color=_DOWN,
        increasing_fillcolor=_UP,  decreasing_fillcolor=_DOWN,
    ), row=1, col=1)

    # EMAs
    close  = df["c"].astype(float)
    ema20  = close.ewm(span=20,  adjust=False).mean()
    ema50  = close.ewm(span=50,  adjust=False).mean()
    ema200 = close.ewm(span=200, adjust=False).mean()
    fig.add_trace(go.Scatter(x=df["t"], y=ema20,  name="EMA20",  line={"color": _ACCENT2, "width": 1.2}, opacity=0.8), row=1, col=1)
    fig.add_trace(go.Scatter(x=df["t"], y=ema50,  name="EMA50",  line={"color": "#f59e0b", "width": 1.2}, opacity=0.8), row=1, col=1)
    fig.add_trace(go.Scatter(x=df["t"], y=ema200, name="EMA200", line={"color": _TICK, "width": 1.0, "dash": "dot"}, opacity=0.6), row=1, col=1)

    # Signal markers
    if signals:
        sig      = signals.get("signal", "hold")
        last_bar = df.iloc[-1]
        if sig == "buy":
            fig.add_trace(go.Scatter(
                x=[last_bar["t"]], y=[float(last_bar["l"]) * 0.998],
                mode="markers+text", name="BUY",
                marker={"symbol": "triangle-up", "size": 16, "color": _UP},
                text=["BUY"], textposition="bottom center",
                textfont={"color": _UP, "size": 11},
            ), row=1, col=1)
        elif sig == "sell":
            fig.add_trace(go.Scatter(
                x=[last_bar["t"]], y=[float(last_bar["h"]) * 1.002],
                mode="markers+text", name="SELL",
                marker={"symbol": "triangle-down", "size": 16, "color": _DOWN},
                text=["SELL"], textposition="top center",
                textfont={"color": _DOWN, "size": 11},
            ), row=1, col=1)

    # RSI
    delta = close.diff()
    gain  = delta.clip(lower=0).ewm(com=13, min_periods=14).mean()
    loss  = (-delta.clip(upper=0)).ewm(com=13, min_periods=14).mean()
    rsi   = 100 - (100 / (1 + gain / loss.replace(0, np.nan)))
    fig.add_trace(go.Scatter(x=df["t"], y=rsi, name="RSI", line={"color": "#a78bfa", "width": 1.5}), row=2, col=1)
    fig.add_hline(y=70, line_dash="dot", line_color=_DOWN, opacity=0.5, row=2, col=1)
    fig.add_hline(y=30, line_dash="dot", line_color=_UP, opacity=0.5, row=2, col=1)
    fig.add_hrect(y0=70, y1=100, fillcolor=_DOWN, opacity=0.05, row=2, col=1)
    fig.add_hrect(y0=0,  y1=30,  fillcolor=_UP, opacity=0.05, row=2, col=1)

    # Volume
    colors = [_UP if c >= o else _DOWN
              for c, o in zip(df["c"].astype(float), df["o"].astype(float))]
    fig.add_trace(go.Bar(x=df["t"], y=df["v"].astype(float),
        name="Volume", marker_color=colors, opacity=0.7), row=3, col=1)

    ax = _axis_style()
    fig.update_layout(
        height=580, xaxis_rangeslider_visible=False,
        title={"text": symbol, "font": {"color": "#e8eef9", "size": 14, "family": "Manrope, sans-serif"}, "x": 0.01},
        **_base_layout(),
    )
    for axis in ["xaxis", "xaxis2", "xaxis3", "yaxis", "yaxis2", "yaxis3"]:
        fig.update_layout(**{axis: ax})
    fig.update_yaxes(title_text="RSI", row=2, col=1, range=[0, 100])
    fig.update_yaxes(title_text="Vol", row=3, col=1)
    return fig


def _add_trade_markers(fig: go.Figure, trades: list[dict], eq_lookup: dict, dates: list[str]):
    for t in trades:
        entry_date = _nearest_date(dates, t.get("entry_date", ""))
        exit_date  = _nearest_date(dates, t.get("exit_date", ""))
        color = _UP if t["pnl"] >= 0 else _DOWN
        if entry_date and entry_date in eq_lookup:
            fig.add_trace(go.Scatter(
                x=[entry_date], y=[eq_lookup[entry_date]],
                mode="markers", showlegend=False,
                marker={"symbol": "triangle-up", "size": 10, "color": _UP},
                hovertemplate=f"Entry ${t['entry']}<br>",
            ))
        if exit_date and exit_date in eq_lookup:
            fig.add_trace(go.Scatter(
                x=[exit_date], y=[eq_lookup[exit_date]],
                mode="markers", showlegend=False,
                marker={"symbol": "triangle-down", "size": 10, "color": color},
                hovertemplate=f"Exit ${t['exit']}  P&L ${t['pnl']:+,.2f}<br>",
            ))


def equity_curve(
    pnl_records: list[dict],
    benchmark_records: list[dict] | None = None,
    trades: list[dict] | None = None,
) -> go.Figure:
    """Equity curve with optional SPY benchmark overlay and trade annotations."""
    if not pnl_records:
        return go.Figure()

    df  = pd.DataFrame(pnl_records)
    fig = go.Figure()

    fig.add_trace(go.Scatter(
        x=df["date"], y=df["equity"],
        fill="tozeroy", fillcolor="rgba(34, 211, 238, 0.10)",
        line={"color": _ACCENT, "width": 2},
        name="Strategy",
    ))

    if benchmark_records:
        bdf = pd.DataFrame(benchmark_records)
        fig.add_trace(go.Scatter(
            x=bdf["date"], y=bdf["equity"],
            line={"color": _TICK, "width": 1.5, "dash": "dot"},
            name="SPY (buy & hold)", opacity=0.7,
        ))

    if trades:
        eq_lookup = {r["date"]: r["equity"] for r in pnl_records}
        dates     = [r["date"] for r in pnl_records]
        _add_trade_markers(fig, trades, eq_lookup, dates)

    ax = _axis_style()
    fig.update_layout(
        height=320,
        xaxis=ax, yaxis=ax,
        **_base_layout(margin={"l": 0, "r": 0, "t": 10, "b": 0}),
    )
    return fig


def live_equity_curve(orders: list[dict], initial_cash: float = 100_000) -> go.Figure | None:
    """Build a live P&L curve from order history (matched buy/sell pairs)."""
    filled = [o for o in orders if o.get("status") == "FILLED"]
    if not filled:
        return None

    buys: dict    = {}
    points: list  = []
    running       = initial_cash

    for o in reversed(filled):
        if o["side"] == "BUY":
            buys[o["symbol"]] = o
        elif o["side"] == "SELL" and o["symbol"] in buys:
            b = buys.pop(o["symbol"])
            fa, bfa = o.get("filled_avg"), b.get("filled_avg")
            if fa and bfa:
                pnl      = (fa - bfa) * (o.get("filled_qty") or 1)
                running += pnl
                points.append({"time": o["time"], "equity": round(running, 2), "pnl": round(pnl, 2)})

    if not points:
        return None

    df = pd.DataFrame(points)
    fig = go.Figure()
    fig.add_trace(go.Scatter(
        x=df["time"], y=df["equity"],
        mode="lines+markers",
        fill="tozeroy", fillcolor="rgba(52, 211, 153, 0.10)",
        line={"color": _UP, "width": 2},
        marker={"size": 6, "color": [_UP if p >= 0 else _DOWN for p in df["pnl"]]},
        name="Live Equity",
        hovertemplate="<b>%{x}</b><br>Equity: $%{y:,.2f}<extra></extra>",
    ))
    ax = _axis_style()
    fig.update_layout(
        height=220, xaxis=ax, yaxis=ax,
        **_base_layout(margin={"l": 0, "r": 0, "t": 10, "b": 0}),
    )
    return fig


def _nearest_date(dates: list[str], target: str) -> str | None:
    if not target or not dates:
        return None
    if target in dates:
        return target
    prefix  = target[:10]
    matches = [d for d in dates if d.startswith(prefix)]
    return matches[0] if matches else None
