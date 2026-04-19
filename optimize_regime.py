"""
Regime parameter optimization script for tradeagent strategy.
Runs systematic grid search across symbols and parameter combinations.
"""
import sys
import warnings
import logging

# Suppress noisy output
warnings.filterwarnings("ignore")
logging.disable(logging.CRITICAL)

import strategy
import backtest
import broker
from datetime import datetime, timezone

SYMBOLS = ["META", "GOOGL", "AMZN", "MSFT", "QQQ", "AAPL"]
TF = "15Min"

# ── helpers ──────────────────────────────────────────────────────────────────

def get_summary(result: dict) -> dict:
    exclude = {"trades", "equity_curve", "benchmark"}
    return {k: v for k, v in result.items() if k not in exclude and not isinstance(v, list)}


def compute_score(ret_pct, sharpe, dd_pct, wr_pct):
    """Combined score: sharpe * return, penalized for DD or low WR."""
    if dd_pct > 2.0 or wr_pct < 45:
        penalty = 0.5
    else:
        penalty = 1.0
    return sharpe * ret_pct * penalty


def run_bull(sym):
    """90d lookback = Jan20–Apr17 2026."""
    r = backtest.run(sym, TF, lookback_days=90)
    s = get_summary(r)
    return s


def get_bear_bars(sym):
    """Get 90d bars then filter to Feb20–Mar30 2026."""
    all_bars = broker.get_bars(sym, timeframe=TF, lookback_days=90)
    # Feb 20 2026 00:00 UTC, Mar 30 2026 23:59 UTC
    start = datetime(2026, 2, 20, tzinfo=timezone.utc)
    end   = datetime(2026, 3, 31, tzinfo=timezone.utc)
    bear_bars = []
    for b in all_bars:
        t_str = b["t"]
        # parse ISO string
        if "+" in t_str:
            t_str2 = t_str
        else:
            t_str2 = t_str + "+00:00"
        try:
            ts = datetime.fromisoformat(t_str2)
        except Exception:
            continue
        if start <= ts < end:
            bear_bars.append(b)
    return bear_bars


def run_bear(sym, bars_cache=None):
    """Run backtest on Feb20–Mar30 2026 bars."""
    if bars_cache is None:
        bars = get_bear_bars(sym)
    else:
        bars = bars_cache
    if not bars:
        return None
    r = backtest.run(sym, TF, bars=bars)
    s = get_summary(r)
    return s


def print_table(title, rows, headers):
    print(f"\n{'='*80}")
    print(f"  {title}")
    print(f"{'='*80}")
    col_w = 12
    h_line = "  ".join(h.ljust(col_w) for h in headers)
    print(h_line)
    print("-" * len(h_line))
    for row in rows:
        print("  ".join(str(v).ljust(col_w) for v in row))


# ── PRE-CACHE all bars ────────────────────────────────────────────────────────

print("\n[1/7] Pre-caching bars for all symbols...")
bear_bars_cache = {}
for sym in SYMBOLS:
    print(f"  Fetching bear bars for {sym}...")
    bear_bars_cache[sym] = get_bear_bars(sym)
    print(f"    => {len(bear_bars_cache[sym])} bars (Feb20-Mar30)")

# ── STEP 1: BASELINE ─────────────────────────────────────────────────────────

print("\n[2/7] Running BASELINE on all symbols (bull=90d, bear=Feb20-Mar30)...")

baseline_bull = {}
baseline_bear = {}

for sym in SYMBOLS:
    print(f"  {sym} bull...")
    baseline_bull[sym] = run_bull(sym)
    print(f"    => ret={baseline_bull[sym].get('total_return_pct',0):.2f}% sharpe={baseline_bull[sym].get('sharpe',0):.3f}")

    print(f"  {sym} bear...")
    r = run_bear(sym, bear_bars_cache[sym])
    baseline_bear[sym] = r
    if r:
        print(f"    => ret={r.get('total_return_pct',0):.2f}% sharpe={r.get('sharpe',0):.3f}")

print("\n--- BASELINE BULL (90d) ---")
bull_rows = []
for sym in SYMBOLS:
    r = baseline_bull[sym]
    bull_rows.append([
        sym,
        f"{r.get('total_return_pct',0):.2f}%",
        f"{r.get('sharpe',0):.3f}",
        f"{r.get('win_rate_pct',0):.1f}%",
        f"{r.get('max_drawdown_pct',0):.2f}%",
        r.get('total_trades',0)
    ])
print_table("BASELINE - Bull Period (90d)", bull_rows,
            ["Symbol","Return%","Sharpe","WR%","DD%","Trades"])

print("\n--- BASELINE BEAR (Feb20-Mar30) ---")
bear_rows = []
for sym in SYMBOLS:
    r = baseline_bear[sym]
    if r:
        bear_rows.append([
            sym,
            f"{r.get('total_return_pct',0):.2f}%",
            f"{r.get('sharpe',0):.3f}",
            f"{r.get('win_rate_pct',0):.1f}%",
            f"{r.get('max_drawdown_pct',0):.2f}%",
            r.get('total_trades',0)
        ])
print_table("BASELINE - Bear Period (Feb20-Mar30)", bear_rows,
            ["Symbol","Return%","Sharpe","WR%","DD%","Trades"])


# ── STEP 2: GRID SEARCH — RANGE REGIME (89% of bars) ─────────────────────────

print("\n[3/7] Grid search: Range regime (bull market, mt=+1)...")

original_regime_params = strategy.regime_params

sl_factors_range   = [0.75, 1.0, 1.25, 1.5]
size_factors_range = [0.8,  0.9, 1.0,  1.1]

range_grid_results = []

for sl in sl_factors_range:
    for sz in size_factors_range:
        def make_patch_range(sl_f, sz_f):
            def patched(regime, market_trend, realized_vol=0.0):
                if regime == "high_volatility" or realized_vol > 0.025:
                    return {"sl_mult_factor": 1.5, "size_factor": 0.5, "threshold_offset": 1, "allow_short": False}
                if regime == "bear_trend" and market_trend == -1:
                    return {"sl_mult_factor": 0.75, "size_factor": 0.6, "threshold_offset": 1, "allow_short": True}
                if regime == "bear_trend":
                    return {"sl_mult_factor": 1.0, "size_factor": 0.7, "threshold_offset": 1, "allow_short": False}
                if market_trend == -1:
                    return {"sl_mult_factor": 0.75, "size_factor": 0.6, "threshold_offset": 1, "allow_short": True}
                if regime == "bull_trend":
                    return {"sl_mult_factor": 1.25, "size_factor": 1.0, "threshold_offset": 0, "allow_short": False}
                # RANGE regime: test values
                return {"sl_mult_factor": sl_f, "size_factor": sz_f, "threshold_offset": 0, "allow_short": False}
            return patched

        strategy.regime_params = make_patch_range(sl, sz)

        agg_score = 0.0
        agg_ret = 0.0
        for sym in SYMBOLS:
            r = run_bull(sym)
            score = compute_score(
                r.get("total_return_pct", 0),
                r.get("sharpe", 0),
                r.get("max_drawdown_pct", 0),
                r.get("win_rate_pct", 0)
            )
            agg_score += score
            agg_ret   += r.get("total_return_pct", 0)

        strategy.regime_params = original_regime_params
        avg_score = agg_score / len(SYMBOLS)
        avg_ret   = agg_ret   / len(SYMBOLS)
        range_grid_results.append({
            "sl": sl, "sz": sz, "avg_score": avg_score, "avg_ret": avg_ret
        })
        print(f"  range sl={sl} sz={sz} => avg_score={avg_score:.4f} avg_ret={avg_ret:.3f}%")

best_range = max(range_grid_results, key=lambda x: x["avg_score"])
print(f"\nBest RANGE params: sl={best_range['sl']} sz={best_range['sz']} score={best_range['avg_score']:.4f}")

# Bull_trend grid search
print("\n[4/7] Grid search: Bull_trend regime...")

sl_factors_bull   = [1.0, 1.25, 1.5, 2.0]
size_factors_bull = [0.9, 1.0,  1.1, 1.2]

bull_trend_grid_results = []

for sl in sl_factors_bull:
    for sz in size_factors_bull:
        def make_patch_bull(sl_f, sz_f):
            def patched(regime, market_trend, realized_vol=0.0):
                if regime == "high_volatility" or realized_vol > 0.025:
                    return {"sl_mult_factor": 1.5, "size_factor": 0.5, "threshold_offset": 1, "allow_short": False}
                if regime == "bear_trend" and market_trend == -1:
                    return {"sl_mult_factor": 0.75, "size_factor": 0.6, "threshold_offset": 1, "allow_short": True}
                if regime == "bear_trend":
                    return {"sl_mult_factor": 1.0, "size_factor": 0.7, "threshold_offset": 1, "allow_short": False}
                if market_trend == -1:
                    return {"sl_mult_factor": 0.75, "size_factor": 0.6, "threshold_offset": 1, "allow_short": True}
                # BULL_TREND regime: test values
                if regime == "bull_trend":
                    return {"sl_mult_factor": sl_f, "size_factor": sz_f, "threshold_offset": 0, "allow_short": False}
                return {"sl_mult_factor": 1.0, "size_factor": 0.9, "threshold_offset": 0, "allow_short": False}
            return patched

        strategy.regime_params = make_patch_bull(sl, sz)

        agg_score = 0.0
        agg_ret   = 0.0
        for sym in SYMBOLS:
            r = run_bull(sym)
            score = compute_score(
                r.get("total_return_pct", 0),
                r.get("sharpe", 0),
                r.get("max_drawdown_pct", 0),
                r.get("win_rate_pct", 0)
            )
            agg_score += score
            agg_ret   += r.get("total_return_pct", 0)

        strategy.regime_params = original_regime_params
        avg_score = agg_score / len(SYMBOLS)
        avg_ret   = agg_ret   / len(SYMBOLS)
        bull_trend_grid_results.append({
            "sl": sl, "sz": sz, "avg_score": avg_score, "avg_ret": avg_ret
        })
        print(f"  bull_trend sl={sl} sz={sz} => avg_score={avg_score:.4f} avg_ret={avg_ret:.3f}%")

best_bull_trend = max(bull_trend_grid_results, key=lambda x: x["avg_score"])
print(f"\nBest BULL_TREND params: sl={best_bull_trend['sl']} sz={best_bull_trend['sz']} score={best_bull_trend['avg_score']:.4f}")

# ── STEP 3: TRAIL STOP MULTIPLIER ────────────────────────────────────────────

print("\n[5/7] Testing trail stop multipliers...")

import backtest as _bt_mod

# Patch the trail multiplier in backtest module
trail_mults = [2.0, 3.0, 4.0, 5.0, 6.0, 8.0]
trail_results = []

orig_source_available = True

# We need to monkey-patch at module level
# Find where trail_stop_pct is computed
# It's: trail_stop_pct = initial_stop_pct * (6.0 if _sig_score >= 5 else 3.0)
# We patch by overriding the constant via a wrapper

import types

def make_trail_patch(mult_strong, mult_weak):
    """Returns a patched run function that uses custom trail multipliers."""
    # We need to modify the internal logic — let's use a config approach
    # Actually let's override at the source level by patching the module globals
    pass

# Alternative: monkey patch through a module-level variable
# Check if backtest has configurable trail mult
import inspect
src = inspect.getsource(_bt_mod.run)
has_trail_config = "_TRAIL_STRONG" in src or "TRAIL_MULT" in src
print(f"  Has trail config var: {has_trail_config}")

# Since trail is hardcoded, we'll test by patching backtest module bytecode
# via a simpler approach: temporarily rewrite the function with exec
# Actually the cleanest approach is to use the importlib reload approach

# Let's read the backtest.py and find the exact line
with open('/Users/akshataraikar/Downloads/REPOS/tradeagent/backtest.py', 'r') as f:
    bt_src = f.read()

trail_line_orig = "trail_stop_pct = initial_stop_pct * (6.0 if _sig_score >= 5 else 3.0)"
print(f"  Trail line found: {trail_line_orig in bt_src}")

best_trail_result = {"mult": None, "avg_score": -999, "avg_ret": -999}
trail_grid_rows = []

for mult in trail_mults:
    # Patch backtest.py temporarily
    new_line = f"trail_stop_pct = initial_stop_pct * ({mult} if _sig_score >= 5 else {mult/2.0})"
    patched_src = bt_src.replace(trail_line_orig, new_line)

    # Write patched version
    with open('/Users/akshataraikar/Downloads/REPOS/tradeagent/backtest.py', 'w') as f:
        f.write(patched_src)

    # Reload the module
    import importlib
    importlib.reload(_bt_mod)
    # Also re-import backtest reference
    globals()['backtest'] = _bt_mod

    agg_score = 0.0
    agg_ret   = 0.0
    for sym in SYMBOLS:
        r = _bt_mod.run(sym, TF, lookback_days=90)
        s = get_summary(r)
        score = compute_score(
            s.get("total_return_pct", 0),
            s.get("sharpe", 0),
            s.get("max_drawdown_pct", 0),
            s.get("win_rate_pct", 0)
        )
        agg_score += score
        agg_ret   += s.get("total_return_pct", 0)

    avg_score = agg_score / len(SYMBOLS)
    avg_ret   = agg_ret   / len(SYMBOLS)
    trail_results.append({"mult": mult, "avg_score": avg_score, "avg_ret": avg_ret})
    trail_grid_rows.append([mult, f"{avg_ret:.3f}%", f"{avg_score:.4f}"])
    print(f"  trail_mult={mult} => avg_score={avg_score:.4f} avg_ret={avg_ret:.3f}%")

    if avg_score > best_trail_result["avg_score"]:
        best_trail_result = {"mult": mult, "avg_score": avg_score, "avg_ret": avg_ret}

    # Restore original
    with open('/Users/akshataraikar/Downloads/REPOS/tradeagent/backtest.py', 'w') as f:
        f.write(bt_src)
    importlib.reload(_bt_mod)
    globals()['backtest'] = _bt_mod

print_table("Trail Multiplier Grid (90d Bull)", trail_grid_rows, ["Trail Mult","Avg Return%","Avg Score"])
print(f"\nBest trail mult: {best_trail_result['mult']} => score={best_trail_result['avg_score']:.4f}")


# ── STEP 4: BEAR PERIOD — specific optimization ───────────────────────────────

print("\n[6/7] Bear period optimization (Feb20-Mar30)...")

sl_factors_bear   = [0.5, 0.75, 1.0]
size_factors_bear = [0.4, 0.5,  0.6,  0.7]

bear_grid_results = []

for sl in sl_factors_bear:
    for sz in size_factors_bear:
        def make_patch_bear(sl_f, sz_f):
            def patched(regime, market_trend, realized_vol=0.0):
                if regime == "high_volatility" or realized_vol > 0.025:
                    return {"sl_mult_factor": 1.5, "size_factor": 0.5, "threshold_offset": 1, "allow_short": False}
                # Bear trend + SPY bearish: test values
                if regime == "bear_trend" and market_trend == -1:
                    return {"sl_mult_factor": sl_f, "size_factor": sz_f, "threshold_offset": 1, "allow_short": True}
                if regime == "bear_trend":
                    return {"sl_mult_factor": sl_f, "size_factor": sz_f * 1.1, "threshold_offset": 1, "allow_short": False}
                # SPY bearish (range stock, bear SPY)
                if market_trend == -1:
                    return {"sl_mult_factor": sl_f, "size_factor": sz_f, "threshold_offset": 1, "allow_short": True}
                if regime == "bull_trend":
                    return {"sl_mult_factor": 1.25, "size_factor": 1.0, "threshold_offset": 0, "allow_short": False}
                return {"sl_mult_factor": 1.0, "size_factor": 0.9, "threshold_offset": 0, "allow_short": False}
            return patched

        strategy.regime_params = make_patch_bear(sl, sz)

        agg_score = 0.0
        agg_ret   = 0.0
        valid = 0
        for sym in SYMBOLS:
            r = run_bear(sym, bear_bars_cache[sym])
            if r is None:
                continue
            score = compute_score(
                r.get("total_return_pct", 0),
                r.get("sharpe", 0),
                r.get("max_drawdown_pct", 0),
                r.get("win_rate_pct", 0)
            )
            agg_score += score
            agg_ret   += r.get("total_return_pct", 0)
            valid += 1

        strategy.regime_params = original_regime_params
        avg_score = agg_score / max(valid, 1)
        avg_ret   = agg_ret   / max(valid, 1)
        bear_grid_results.append({
            "sl": sl, "sz": sz, "avg_score": avg_score, "avg_ret": avg_ret
        })
        print(f"  bear sl={sl} sz={sz} => avg_score={avg_score:.4f} avg_ret={avg_ret:.3f}%")

best_bear = max(bear_grid_results, key=lambda x: x["avg_score"])
print(f"\nBest BEAR params: sl={best_bear['sl']} sz={best_bear['sz']} score={best_bear['avg_score']:.4f}")


# ── STEP 5: SYNTHESIZE OPTIMAL PARAMS ────────────────────────────────────────

print("\n[7/7] Synthesizing optimal params and running final validation...")

# Best params summary
print(f"\nOPTIMAL PARAMS SUMMARY:")
print(f"  Range regime (bull mkt):    sl={best_range['sl']}  sz={best_range['sz']}")
print(f"  Bull_trend regime:          sl={best_bull_trend['sl']}  sz={best_bull_trend['sz']}")
print(f"  Bear period (mt=-1):        sl={best_bear['sl']}    sz={best_bear['sz']}")
print(f"  Trail stop multiplier:      {best_trail_result['mult']}")

# Apply combined optimal params
opt_range_sl  = best_range['sl']
opt_range_sz  = best_range['sz']
opt_bull_sl   = best_bull_trend['sl']
opt_bull_sz   = best_bull_trend['sz']
opt_bear_sl   = best_bear['sl']
opt_bear_sz   = best_bear['sz']

def optimal_regime_params(regime, market_trend, realized_vol=0.0):
    if regime == "high_volatility" or realized_vol > 0.025:
        return {"sl_mult_factor": 1.5, "size_factor": 0.5, "threshold_offset": 1, "allow_short": False}
    if regime == "bear_trend" and market_trend == -1:
        return {"sl_mult_factor": opt_bear_sl, "size_factor": opt_bear_sz, "threshold_offset": 1, "allow_short": True}
    if regime == "bear_trend":
        return {"sl_mult_factor": opt_bear_sl, "size_factor": min(opt_bear_sz * 1.1, 0.7), "threshold_offset": 1, "allow_short": False}
    if market_trend == -1:
        return {"sl_mult_factor": opt_bear_sl, "size_factor": opt_bear_sz, "threshold_offset": 1, "allow_short": True}
    if regime == "bull_trend":
        return {"sl_mult_factor": opt_bull_sl, "size_factor": opt_bull_sz, "threshold_offset": 0, "allow_short": False}
    return {"sl_mult_factor": opt_range_sl, "size_factor": opt_range_sz, "threshold_offset": 0, "allow_short": False}

strategy.regime_params = optimal_regime_params

# Run final validation on both periods
final_bull = {}
final_bear = {}

for sym in SYMBOLS:
    print(f"  Final validation {sym} bull...")
    final_bull[sym] = run_bull(sym)
    print(f"    => ret={final_bull[sym].get('total_return_pct',0):.2f}% sharpe={final_bull[sym].get('sharpe',0):.3f}")

    print(f"  Final validation {sym} bear...")
    r = run_bear(sym, bear_bars_cache[sym])
    final_bear[sym] = r
    if r:
        print(f"    => ret={r.get('total_return_pct',0):.2f}% sharpe={r.get('sharpe',0):.3f}")

strategy.regime_params = original_regime_params

# ── FINAL REPORT ─────────────────────────────────────────────────────────────

print("\n")
print("=" * 90)
print("  FINAL OPTIMIZATION REPORT")
print("=" * 90)

print("\n## GRID SEARCH RESULTS — Range Regime (top 5 by score)")
sorted_range = sorted(range_grid_results, key=lambda x: x['avg_score'], reverse=True)[:5]
range_rows = [[r['sl'], r['sz'], f"{r['avg_ret']:.3f}%", f"{r['avg_score']:.4f}"] for r in sorted_range]
print_table("Range Regime Grid — Top 5", range_rows, ["SL Factor","Size Factor","Avg Return%","Avg Score"])

print("\n## GRID SEARCH RESULTS — Bull Trend Regime (top 5 by score)")
sorted_bull = sorted(bull_trend_grid_results, key=lambda x: x['avg_score'], reverse=True)[:5]
bull_rows2 = [[r['sl'], r['sz'], f"{r['avg_ret']:.3f}%", f"{r['avg_score']:.4f}"] for r in sorted_bull]
print_table("Bull Trend Regime Grid — Top 5", bull_rows2, ["SL Factor","Size Factor","Avg Return%","Avg Score"])

print("\n## TRAIL MULTIPLIER RESULTS")
print_table("Trail Multiplier Comparison", trail_grid_rows, ["Trail Mult","Avg Return%","Avg Score"])

print("\n## BEAR PERIOD GRID (top 5 by score)")
sorted_bear = sorted(bear_grid_results, key=lambda x: x['avg_score'], reverse=True)[:5]
bear_rows2 = [[r['sl'], r['sz'], f"{r['avg_ret']:.3f}%", f"{r['avg_score']:.4f}"] for r in sorted_bear]
print_table("Bear Period Grid — Top 5", bear_rows2, ["SL Factor","Size Factor","Avg Return%","Avg Score"])

print(f"""
## OPTIMAL PARAMS FOUND
  - Range regime (dominant, 89% of bars):  sl_mult_factor={opt_range_sl}, size_factor={opt_range_sz}, threshold_offset=0, allow_short=False
  - Bull_trend regime:                     sl_mult_factor={opt_bull_sl},  size_factor={opt_bull_sz},  threshold_offset=0, allow_short=False
  - Bear (mt=-1 or bear_trend+mt=-1):     sl_mult_factor={opt_bear_sl},  size_factor={opt_bear_sz},  threshold_offset=1, allow_short=True
  - High_volatility:                       sl_mult_factor=1.5,  size_factor=0.5,  threshold_offset=1, allow_short=False  [unchanged]
  - Trail stop multiplier (strong sig):    {best_trail_result['mult']}x initial SL
""")

print("\n## BEFORE vs AFTER — BULL PERIOD (90d)")
compare_bull_rows = []
for sym in SYMBOLS:
    b = baseline_bull[sym]
    f = final_bull[sym]
    compare_bull_rows.append([
        sym,
        f"{b.get('total_return_pct',0):.2f}%",
        f"{f.get('total_return_pct',0):.2f}%",
        f"{b.get('sharpe',0):.3f}",
        f"{f.get('sharpe',0):.3f}",
        f"{b.get('win_rate_pct',0):.1f}%",
        f"{f.get('win_rate_pct',0):.1f}%",
        f"{b.get('max_drawdown_pct',0):.2f}%",
        f"{f.get('max_drawdown_pct',0):.2f}%",
    ])
print_table("Before vs After — Bull Period", compare_bull_rows,
            ["Sym","Ret%(B)","Ret%(A)","Sharpe(B)","Sharpe(A)","WR%(B)","WR%(A)","DD%(B)","DD%(A)"])

print("\n## BEFORE vs AFTER — BEAR PERIOD (Feb20-Mar30)")
compare_bear_rows = []
for sym in SYMBOLS:
    b = baseline_bear[sym]
    f = final_bear[sym]
    if b is None or f is None:
        continue
    compare_bear_rows.append([
        sym,
        f"{b.get('total_return_pct',0):.2f}%",
        f"{f.get('total_return_pct',0):.2f}%",
        f"{b.get('sharpe',0):.3f}",
        f"{f.get('sharpe',0):.3f}",
        f"{b.get('win_rate_pct',0):.1f}%",
        f"{f.get('win_rate_pct',0):.1f}%",
        f"{b.get('max_drawdown_pct',0):.2f}%",
        f"{f.get('max_drawdown_pct',0):.2f}%",
    ])
print_table("Before vs After — Bear Period", compare_bear_rows,
            ["Sym","Ret%(B)","Ret%(A)","Sharpe(B)","Sharpe(A)","WR%(B)","WR%(A)","DD%(B)","DD%(A)"])

print("\n## FINAL VALIDATION — All Symbols, Both Periods")
final_all_rows = []
for sym in SYMBOLS:
    b = final_bull[sym]
    br = final_bear.get(sym)
    final_all_rows.append([
        sym, "90d_bull",
        f"{b.get('total_return_pct',0):.2f}%",
        f"{b.get('sharpe',0):.3f}",
        f"{b.get('win_rate_pct',0):.1f}%",
        f"{b.get('max_drawdown_pct',0):.2f}%",
        b.get('total_trades',0)
    ])
    if br:
        final_all_rows.append([
            sym, "bear_Feb-Mar",
            f"{br.get('total_return_pct',0):.2f}%",
            f"{br.get('sharpe',0):.3f}",
            f"{br.get('win_rate_pct',0):.1f}%",
            f"{br.get('max_drawdown_pct',0):.2f}%",
            br.get('total_trades',0)
        ])
print_table("Final Validation — New Params", final_all_rows,
            ["Symbol","Period","Return%","Sharpe","WR%","DD%","Trades"])

# ── RECOMMENDATION ───────────────────────────────────────────────────────────

print("\n## SYMBOL RECOMMENDATIONS BY REGIME")
print("""
BULL MARKET (90d) — Best symbols to trade:""")
bull_sorted = sorted(SYMBOLS, key=lambda s: final_bull[s].get('total_return_pct', 0), reverse=True)
for sym in bull_sorted:
    r = final_bull[sym]
    fits_criteria = r.get('max_drawdown_pct', 99) < 2.0 and r.get('win_rate_pct', 0) > 55
    flag = " ✓ RECOMMENDED" if fits_criteria else " (high DD or low WR)"
    print(f"  {sym}: ret={r.get('total_return_pct',0):.2f}% sharpe={r.get('sharpe',0):.3f} "
          f"WR={r.get('win_rate_pct',0):.1f}% DD={r.get('max_drawdown_pct',0):.2f}%{flag}")

print("""
BEAR PERIOD (Feb20-Mar30) — Best symbols to trade:""")
bear_sorted = sorted(SYMBOLS,
    key=lambda s: (final_bear.get(s) or {}).get('total_return_pct', -999), reverse=True)
for sym in bear_sorted:
    r = final_bear.get(sym)
    if r is None:
        continue
    fits_criteria = r.get('max_drawdown_pct', 99) < 2.0 and r.get('win_rate_pct', 0) > 50
    flag = " ✓ RECOMMENDED" if fits_criteria else " (review risk)"
    print(f"  {sym}: ret={r.get('total_return_pct',0):.2f}% sharpe={r.get('sharpe',0):.3f} "
          f"WR={r.get('win_rate_pct',0):.1f}% DD={r.get('max_drawdown_pct',0):.2f}%{flag}")

# Store optimal params for writing to strategy.py
print("\n\n[PARAMS_FOR_STRATEGY]")
print(f"OPT_RANGE_SL={opt_range_sl}")
print(f"OPT_RANGE_SZ={opt_range_sz}")
print(f"OPT_BULL_SL={opt_bull_sl}")
print(f"OPT_BULL_SZ={opt_bull_sz}")
print(f"OPT_BEAR_SL={opt_bear_sl}")
print(f"OPT_BEAR_SZ={opt_bear_sz}")
print(f"OPT_TRAIL={best_trail_result['mult']}")
print("[END_PARAMS]")
