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
