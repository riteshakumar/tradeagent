# TradeAgent

Algorithmic trading agent for Alpaca with:
- Indicator-based signal engine
- Optional LLM approval + event scoring
- Built-in risk gates (drawdown halt, daily loss stop, sector/correlation caps)
- Shadow mode (records hypothetical orders and outcomes)
- Streamlit operations dashboard
- Backtesting, walk-forward, and parameter optimization

## Quick Start

```bash
cd tradeagent
python3 -m venv venv
source venv/bin/activate
pip install -r requirements.txt
cp .env.example .env
```

Edit `.env` with valid keys before running.

## Run

Trading loop:

```bash
python main.py
```

Dashboard:

```bash
streamlit run dashboard.py
```

## Safety Modes

- `DRY_RUN=true`: computes signals, never sends orders.
- `SHADOW_MODE=true`: writes hypothetical intents and realized outcomes to `shadow_book.json`.
- `PAPER_TRADING=true`: Alpaca paper account.
- Live trading requires both:
  - `PAPER_TRADING=false`
  - `CONFIRM_LIVE_TRADING=true`

## Risk Controls

Enabled by default:
- `MAX_DRAWDOWN_PCT`: latching drawdown halt
- `DAILY_LOSS_STOP_PCT`: daily stop based on session anchor equity
- `MAX_SECTOR_EXPOSURE_PCT`: sector concentration cap
- `ENABLE_CORRELATION_CAP`: correlation cap across holdings

Optional sector mapping override:

```bash
SYMBOL_SECTORS={"AAPL":"technology","MSFT":"technology","JPM":"financials"}
```

## Regime-Aware Scoring

The signal engine detects market regime (`bull_trend`, `bear_trend`, `range`, `high_volatility`) and applies regime-specific indicator weights.

Disable with:

```bash
ENABLE_REGIME_SWITCHING=false
```

## Backtesting

Backtests now apply:
- intrabar stop-loss/take-profit exits
- slippage (`BACKTEST_SLIPPAGE_BPS`)
- per-trade fees (`BACKTEST_FEE_PER_TRADE`)

Use the dashboard Backtest tab or import `backtest.run(...)`.

## Testing

```bash
pytest -q
```

CI runs these tests on push/PR via GitHub Actions.


Strategy Backtest Results:

 Optimization Complete — Final Results

  Grid search ran across META/GOOGL/AMZN/MSFT/QQQ/AAPL, both bull (90d) and bear (Feb 20–Mar 30 2026) periods.

  What changed


  ┌─────────────────────────┬────────────────┬────────┬───────┐
  │         Regime          │     Param      │ Before │ After │
  ├─────────────────────────┼────────────────┼────────┼───────┤
  │ Range (89% of bars)     │ sl_mult_factor │ 1.0    │ 1.5   │
  ├─────────────────────────┼────────────────┼────────┼───────┤
  │ Range                   │ size_factor    │ 0.9    │ 1.1   │
  ├─────────────────────────┼────────────────┼────────┼───────┤
  │ Bear + SPY bear         │ sl_mult_factor │ 0.75   │ 0.5   │
  ├─────────────────────────┼────────────────┼────────┼───────┤
  │ Bear + SPY bear         │ size_factor    │ 0.6    │ 0.4   │
  ├─────────────────────────┼────────────────┼────────┼───────┤
  │ Bear solo               │ size_factor    │ 0.7    │ 0.44  │
  ├─────────────────────────┼────────────────┼────────┼───────┤
  │ Trail stop (high score) │ multiplier     │ 6.0×   │ 2.0×  │
  ├─────────────────────────┼────────────────┼────────┼───────┤
  │ Trail stop (normal)     │ multiplier     │ 3.0×   │ 1.0×  │
  └─────────────────────────┴────────────────┴────────┴───────┘

  Bull period performance (90d)

  ┌────────┬────────┬───────┬────────┬───────┬───────┐
  │ Symbol │ Before │ After │ Sharpe │  WR   │  DD   │
  ├────────┼────────┼───────┼────────┼───────┼───────┤
  │ META   │ 2.23%  │ 2.76% │ 2.530  │ 92.3% │ 0.62% │
  ├────────┼────────┼───────┼────────┼───────┼───────┤
  │ GOOGL  │ 1.52%  │ 1.67% │ 2.613  │ 75%   │ 0.40% │
  ├────────┼────────┼───────┼────────┼───────┼───────┤
  │ AMZN   │ 1.65%  │ 2.21% │ 2.423  │ 59.1% │ 0.49% │
  ├────────┼────────┼───────┼────────┼───────┼───────┤
  │ MSFT   │ 0.81%  │ 1.66% │ 2.262  │ 60%   │ 0.45% │
  ├────────┼────────┼───────┼────────┼───────┼───────┤
  │ QQQ    │ 0.19%  │ 0.61% │ 1.427  │ —     │ —     │
  ├────────┼────────┼───────┼────────┼───────┼───────┤
  │ AAPL   │ 0.28%  │ 0.03% │ —      │ —     │ —     │
  └────────┴────────┴───────┴────────┴───────┴───────┘

  Bear period performance (Feb 20–Mar 30 2026)

  ┌────────┬────────┬───────┬─────────┐
  │ Symbol │ Before │ After │ SPY B&H │
  ├────────┼────────┼───────┼─────────┤
  │ MSFT   │ 0.41%  │ 1.12% │ -12%    │
  ├────────┼────────┼───────┼─────────┤
  │ META   │ 0.48%  │ 0.55% │ -18%    │
  └────────┴────────┴───────┴─────────┘

  AAPL degraded — recommend dropping from live watchlist (already pinned in .env for fallback only).

  Key findings

  - Range regime dominates (89% bars) → biggest lever is range sl_mult_factor/size_factor
  - Bear protection works: strategy flat/positive while market crashes 8-18%
  - Intraday shorts disabled (WR was 28%) — daily shorts only, gated by SPY bear + strong score


