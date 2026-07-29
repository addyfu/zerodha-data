"""EXHUMATION SWEEP -- the strategy zoo re-tested on the widest honest panel.

FROZEN SPEC (read this first, do not deviate without a spec amendment):
    docs/superpowers/specs/2026-07-29-exhumation-sweep-design.md
    Status: APPROVED & FROZEN (user, 2026-07-29).

WHAT THIS IS
------------
The FINAL audit of the existing 67-strategy clean zoo on the 3,204-symbol NSE
bhavcopy panel (2019-10 .. 2026-07), under wide-universe costs. It is NOT a
new-idea hunt. Stated prior (before any result): 137-0 stands; the sweep's
value is decisive closure either way.

MODES
-----
    python -W ignore kite/research/exhumation_sweep.py --prepare
        One-off: loads the whole panel, HALT-checks corporate actions and the
        clip guard, builds the eligible universe + the EW eligible-universe
        daily return series, writes them to the work dir. Cheap (~2-4 min).
        The 10 workers share these artifacts READ-ONLY.

    python -W ignore kite/research/exhumation_sweep.py --shard I --of N
        Worker: computes all 67 strategies over shard I's symbols, appends
        one JSON object per trade to <work>/shard_I_of_N.ndjson, then writes
        <work>/shard_I_of_N.done. Re-running a completed shard is a no-op.
        A crashed shard resumes at the last completed symbol (byte-exact
        truncation of the partial, see _resume_partial).
        Optional --symbols-limit K restricts the shard to its first K symbols
        (SMOKE ONLY -- it poisons the merge coverage assert on purpose).

    python -W ignore kite/research/exhumation_sweep.py --merge --of N
        Single-threaded: streams every partial, asserts full symbol coverage
        and zero duplicate (strategy, symbol, entry_date), aggregates to
        <work>/merged_stats.json.

    python -W ignore kite/research/exhumation_sweep.py --verdict
        Applies the frozen criteria to merged_stats.json and writes
        kite/research/exhumation_sweep_results.txt.

    Add --smoke to --merge/--verdict for a plumbing check on partial data:
    coverage/shard-completeness asserts are downgraded to printed warnings,
    every page is stamped SMOKE, and the verdict goes to
    kite/research/exhumation_sweep_results_smoke.txt. A SMOKE verdict is not
    evidence of anything and says so on every screen.

CONVENTIONS REUSED (not reinvented)
-----------------------------------
- Panel loading, corporate-action back-adjustment (+ NaN-factor HALT), the
  +/-25% return clip guard (+ >0.1% HALT), the eligibility gate and the
  equal-weight daily-rebalanced eligible-universe benchmark:
  delivery_factor_study.py, verbatim conventions.
- Strategy zoo + signal path: consensus_probe.py / zoo_silence_confirmation.py
  -- STRATEGY_REGISTRY as-is, BaseStrategy.generate_signals(df)['signal']
  (the ~20x optimization over get_trade_signals(); bit-identical 'signal'
  column, no strategy in the package overrides get_trade_signals()).
- Clean set: the SAME 67 strategies (78 registered - 9 leak-suspects -
  2 erroring). The list is hard-coded below from zoo_silence_confirmation.py
  and ASSERTED byte-identical against a live recomputation of leak_flags();
  any drift kills the run.
- SL/TP semantics + gap-aware fills: retest_all.py -- SL/TP computed by the
  strategy's own calculate_stop_loss/calculate_take_profit at the SIGNAL bar
  off that bar's close (exactly what BaseStrategy.get_trade_signals does),
  checked against daily high/low, gap-through fills at the WORSE of
  (stop, open), SL wins same-bar ties.
- Costs: zerodha_charges.calculate_charges(buy_v, sell_v, is_intraday=False)
  ['total'] -- the KEY, never sum(.values()) (that double-counts) -- on a
  Rs 20,000 delivery position, plus 0.2%/side slippage (wide-universe tier).

THREE IMPLEMENTATION CHOICES THE SPEC DOES NOT FULLY PIN DOWN
--------------------------------------------------------------
Flagged here, restated in the results header, and NOT silently buried.

(1) TIME-STOP ARITHMETIC. "10-trading-day time stop" is read as: the position
    is open for at most 10 trading bars INCLUDING the entry bar, i.e. entry at
    OPEN[p+1] and, absent an SL/TP hit, exit at CLOSE[p+10]. The alternative
    reading ("10 bars AFTER entry" -> CLOSE[p+11]) is one bar longer. One
    convention is applied to the whole zoo; no variant is computed, because
    computing both would double the declared test count.

(2) BENCHMARK WINDOW ALIGNMENT. Per-trade abnormal return = net trade return
    minus the EW eligible-universe return compounded over market days
    [entry_date .. exit_date] INCLUSIVE. The EW series is close-to-close, so
    its day-e return runs from close(e-1) while the trade's day-e return runs
    from open(e): the benchmark leg therefore includes one extra overnight
    gap that the trade does not. That is the CONSERVATIVE side of the
    ambiguity (Indian equity overnight drift is positive on average, so this
    slightly understates abnormal returns). Starting the compounding one day
    later would have been the anti-conservative choice, so it was not taken.

(2b) BENCHMARK MEMBERSHIP IS LAGGED BY ONE DAY. The spec's eligibility gate is
    same-day ("adjusted close >= Rs 20 AT SIGNAL TIME"), which is correct and
    leak-free for SIGNALS -- a signal on day t is only actionable at t+1's
    open. Applying that same-day flag to BENCHMARK membership, however, is
    not implementable and is badly biased: the Rs 20 floor admits a stock to
    the index on the very day it jumps over the line and drops it on the day
    it falls back. MEASURED ON THIS PANEL, same-day membership yields a mean
    EW daily return of +0.2962% (cumulative +12,337% over the panel) against
    +0.0902% (+296%) for membership decided by the symbol's PREVIOUS bar --
    with both series averaging the same ~945 names/day, so the 0.206%/day gap
    is pure selection, not coverage. This sweep uses LAGGED membership. Note
    the direction: the lagged benchmark is the LOWER bar, so this choice makes
    abnormal returns LARGER and the sweep HARDER to fail. Taking the inflated
    benchmark would have handed the stated prior ("137-0 stands") a free win,
    which is exactly what a pre-registered audit must not do. Both numbers are
    printed by --prepare so the size of the correction is on the record.

(3) TRADEABLE UNIVERSE vs BENCHMARK UNIVERSE. The BENCHMARK is the eligible
    universe exactly as the spec defines it (every (symbol, day) passing the
    three gates -- no other filter). The TRADEABLE universe additionally
    requires >= 300 EQ bars of panel history for the symbol -- the universe
    convention every prior study in this repo used (retest_all.load_data,
    consensus_probe, zoo_silence). It is a data-sufficiency rule (indicators
    cannot warm up otherwise), not a performance filter, and the symbols it
    removes are counted, listed to <work>/excluded_short_history.txt, and
    reported. It is mildly survivorship-flavoured and is declared as such.

OTHER STATED DEVIATIONS / EXTENSIONS
------------------------------------
- VOLUME IS CORPORATE-ACTION ADJUSTED (adj_volume = volume / adj_mult).
  delivery_factor_study.py adjusted OPEN/CLOSE only because it never fed
  volume to anything. This sweep feeds volume to strategies, and an
  unadjusted volume series has a spurious 2x step at every 1:1 bonus, which
  would fire volume-breakout strategies on an accounting artifact. The
  adjustment is the mirror of the price adjustment (share count scales by
  1/factor), and it is applied to volume ONLY, never to turnover (turnover
  is a rupee quantity and needs no share-count adjustment).
- NO SIGNAL-BASED EXIT. retest_all.py closes a long on the strategy's -1
  signal; the frozen spec's execution model lists only SL / TP / 10-day time
  stop, so a -1 signal does NOT close a position here. This is part of the
  spec's own declared HARMONIZATION caveat (survivors must be re-validated
  under their exact native exits before candidacy).
- NO ARTIFICIAL WARM-UP FLOOR. consensus_probe dropped each symbol's first
  252 bars; this spec does not ask for that and it is not applied. Indicators
  warm up naturally (they emit NaN -> no signal) inside each symbol's own
  history.
- The 2 a-priori-excluded erroring strategies (pivot_point, vwap_pullback)
  are excluded BY NAME, as in zoo_silence_confirmation.py. They are not
  re-probed on this panel: the frozen spec says the clean set is the same 67.

Usage examples
--------------
    python -W ignore kite/research/exhumation_sweep.py --prepare
    python -W ignore kite/research/exhumation_sweep.py --shard 0 --of 10
    python -W ignore kite/research/exhumation_sweep.py --merge --of 10
    python -W ignore kite/research/exhumation_sweep.py --verdict
"""
import argparse
import json
import os
import re
import sys
import time
from pathlib import Path

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))
from kite.config import zerodha_charges          # noqa: E402  (['total'] only)
from kite.strategies import STRATEGY_REGISTRY    # noqa: E402
from kite.strategies.base_strategy import Signal  # noqa: E402

SPEC = 'docs/superpowers/specs/2026-07-29-exhumation-sweep-design.md'
DATA_DIR = ROOT / 'data' / 'bhavcopy_full'
CORP_ACTIONS_PATH = ROOT / 'data' / 'corp_actions_adjustments.csv'
AUDIT_CSV = ROOT / 'kite' / 'reports' / 'walkforward_audit.csv'
DEFAULT_WORK_DIR = ROOT / 'data' / 'exhumation'
OUT_DIR = ROOT / 'kite' / 'research'
OUT_FILE = OUT_DIR / 'exhumation_sweep_results.txt'
OUT_FILE_SMOKE = OUT_DIR / 'exhumation_sweep_results_smoke.txt'

# ---------------------------------------------------------------------------
# Frozen constants
# ---------------------------------------------------------------------------
MIN_TURNOVER_LACS = 200.0     # Rs 2 crore  (delivery_factor_study.py)
MIN_PRICE = 20.0              # Rs 20 adjusted close at signal time
CLIP = 0.25                   # +/-25% daily return clip (benchmark construction)
CLIP_HALT_FRAC = 0.001        # >0.1% of eligible stock-days -> HALT
MIN_BARS = 300                # tradeable-universe history floor (repo convention)

SLIP = 0.002                  # 0.2% per side, wide-universe tier
POSITION_RS = 20_000          # delivery; flat Rs 13.5 DP charge makes size matter
TIME_STOP_BARS = 10           # bars held INCLUDING the entry bar -> exit CLOSE[p+10]

TRAIN_START = pd.Timestamp('2019-10-01')
TRAIN_END = pd.Timestamp('2023-12-31')
VAL_START = pd.Timestamp('2024-01-01')
VAL_END = pd.Timestamp('2026-07-31')

# --- verdict thresholds (frozen) -------------------------------------------
MIN_VAL_TRADES = 100          # else NODATA (underpowered), never a pass
T_THRESHOLD = 3.2             # Bonferroni bar: 0.05/67 -> one-sided z ~ 3.2
DECLARED_TESTS = 67
ERROR_SKIP_FRAC = 0.50        # errors on >50% of symbols -> NODATA (skipped)

FNAME_DATE_RE = re.compile(r'sec_bhavdata_full_(\d{2})(\d{2})(\d{4})\.csv$', re.IGNORECASE)
NEEDED_COLS = ['SYMBOL', 'SERIES', 'DATE1', 'OPEN_PRICE', 'HIGH_PRICE', 'LOW_PRICE',
               'CLOSE_PRICE', 'TTL_TRD_QNTY', 'TURNOVER_LACS']

# ---------------------------------------------------------------------------
# The clean 67. Transcribed from zoo_silence_confirmation.py (which transcribed
# it from consensus_probe_results.txt). Recomputed at runtime and ASSERTED
# equal, name for name -- registry drift, audit-CSV drift or a changed error
# set kills the run instead of silently redefining the test.
# ---------------------------------------------------------------------------
PROBE_REGISTRY_N = 78
PROBE_EXCLUDED_LEAK = [
    'double_vwap_ha', 'ema_21_55', 'ema_scalping_1min', 'fib_3wave',
    'london_breakout', 'obv_strategy', 'volume_oscillator', 'vwap_scalping',
    'vwap_sd_bands',
]
PROBE_EXCLUDED_ERROR = ['pivot_point', 'vwap_pullback']
PROBE_CLEAN_N = 67
CLEAN_67 = [
    'adx_dmi_obv', 'adx_filter', 'alligator', 'ascending_triangle', 'atr_breakout',
    'atr_trailing_stop', 'bb_mean_reversion', 'bb_squeeze', 'candlestick_patterns',
    'cci_divergence', 'cci_zero_cross', 'chandelier_exit', 'choppiness_breakout',
    'choppiness_filter', 'choppiness_volume', 'cmf_ichimoku', 'cmf_strategy', 'cpr',
    'donchian_turtle', 'double_bb', 'elliott_abc', 'elliott_wave3', 'ema_3_scalping',
    'fib_confluence', 'fib_pivot', 'fib_retracement', 'gmma', 'golden_ratio', 'ha_rsi',
    'ha_trend', 'hidden_divergence', 'hull_slope', 'ichimoku_ha', 'ichimoku_trend',
    'kumo_breakout', 'ma_crossover_swing', 'ma_envelopes', 'macd_divergence',
    'macd_ma_filter', 'macd_zero_line', 'market_swing', 'mcginley_dynamic',
    'mfi_divergence', 'momentum_zero', 'multi_timeframe', 'psar_ichimoku',
    'regular_divergence', 'renko_sma_obv', 'renko_sr', 'roc_divergence', 'roc_ma',
    'rsi_centerline', 'rsi_divergence', 'rsi_trend_confirmation',
    'stochastic_confluence', 'stochastic_divergence', 'stochrsi_macd', 'supply_demand',
    'swing_pivot', 'tdi', 'trix_divergence', 'trix_zero_line', 'ttm_squeeze',
    'ttm_squeeze_trend', 'vwma_sma', 'wyckoff_accumulation', 'wyckoff_distribution',
]

_LINES = []


def log(msg=''):
    print(msg, flush=True)
    _LINES.append(str(msg))


def flush_out(path):
    path.write_text('\n'.join(_LINES) + '\n', encoding='utf-8')


# ===========================================================================
# PANEL  (delivery_factor_study.py conventions, + high/low/volume, + symbols=)
# ===========================================================================
def load_panel(data_dir=DATA_DIR, symbols=None, quiet=False):
    """Long panel of EQ stock-days.

    `symbols` (a set/iterable) filters AT LOAD so a worker never materialises
    rows for symbols outside its shard -- the 16GB / 10-worker constraint.
    Trading day comes from the FILENAME (robust); DATE1 is still read, per the
    delivery study, so a hand-inspection mismatch would be visible.
    """
    sym_filter = set(symbols) if symbols is not None else None
    files = sorted(data_dir.glob('sec_bhavdata_full_*.csv'))
    frames, n_skipped = [], 0
    for f in files:
        m = FNAME_DATE_RE.search(f.name)
        if not m:
            if not quiet:
                log(f'  WARN: {f.name} does not match expected filename pattern, skipping')
            n_skipped += 1
            continue
        file_date = pd.Timestamp(year=int(m.group(3)), month=int(m.group(2)), day=int(m.group(1)))
        try:
            df = pd.read_csv(f, dtype=str, encoding='utf-8')
        except Exception as e:
            if not quiet:
                log(f'  WARN: failed to read {f.name}: {type(e).__name__}: {e}, skipping')
            n_skipped += 1
            continue
        df.columns = df.columns.str.strip()
        missing = [c for c in NEEDED_COLS if c not in df.columns]
        if missing:
            if not quiet:
                log(f'  WARN: {f.name} missing columns {missing}, skipping file')
            n_skipped += 1
            continue
        df = df[NEEDED_COLS].copy()
        for c in NEEDED_COLS:
            df[c] = df[c].astype(str).str.strip()
        df = df[df['SERIES'] == 'EQ']
        if sym_filter is not None:
            df = df[df['SYMBOL'].isin(sym_filter)]
        if df.empty:
            continue
        df = df.copy()
        df['date'] = file_date
        for c in ['OPEN_PRICE', 'HIGH_PRICE', 'LOW_PRICE', 'CLOSE_PRICE',
                  'TTL_TRD_QNTY', 'TURNOVER_LACS']:
            df[c] = pd.to_numeric(df[c], errors='coerce')
        frames.append(df.rename(columns={
            'SYMBOL': 'symbol', 'OPEN_PRICE': 'open', 'HIGH_PRICE': 'high',
            'LOW_PRICE': 'low', 'CLOSE_PRICE': 'close', 'TTL_TRD_QNTY': 'volume',
            'TURNOVER_LACS': 'turnover_lacs',
        })[['symbol', 'date', 'open', 'high', 'low', 'close', 'volume', 'turnover_lacs']])
    if not frames:
        sys.exit(f'HALTED: no usable files found under {data_dir}. Run fetch_bhavcopy_full.py first.')
    panel = pd.concat(frames, ignore_index=True)
    panel = panel.drop_duplicates(subset=['symbol', 'date'], keep='last')
    panel = panel.sort_values(['symbol', 'date']).reset_index(drop=True)
    if not quiet:
        log(f'Loaded {len(files)} files ({n_skipped} skipped), {len(panel):,} EQ stock-day rows, '
            f'{panel.symbol.nunique():,} symbols, {panel.date.min().date()} -> {panel.date.max().date()}')
    return panel, len(files), n_skipped


def load_corp_actions(path=CORP_ACTIONS_PATH):
    if not path.exists():
        sys.exit(f'HALTED: {path} not found. Run build_corp_actions.py first.')
    df = pd.read_csv(path)
    df['ex_date'] = pd.to_datetime(df['ex_date'])
    return df


def halt_on_unresolved_nan_factors(panel, corp_actions):
    """delivery_factor_study.py verbatim: HALT if a NaN-factor action's symbol
    has panel rows dated before that action's ex_date."""
    nan_rows = corp_actions[corp_actions['factor'].isna()]
    if nan_rows.empty:
        return 0
    panel_symbols = set(panel['symbol'].unique())
    offenders = []
    for _, row in nan_rows.iterrows():
        sym, ex = row['symbol'], row['ex_date']
        if sym not in panel_symbols:
            continue
        if (panel.loc[panel['symbol'] == sym, 'date'] < ex).any():
            offenders.append((sym, ex.date().isoformat(), row.get('subject', '')))
    if offenders:
        log('')
        log('HALT: unresolved (factor=NaN) corporate action(s) touch dates in the loaded panel:')
        for sym, ex, subj in offenders:
            log(f'  {sym}  ex_date={ex}  subject={subj!r}')
        sys.exit(f'HALTED: {len(offenders)} unresolved corp-action factor(s) affect the loaded panel.')
    return len(nan_rows)


def apply_corp_action_adjustments(panel, corp_actions, quiet=False):
    """Back-adjust OHLC by the cumulative product of every factor whose ex_date
    is STRICTLY AFTER the row's date (delivery_factor_study.py verbatim), and
    -- STATED EXTENSION -- back-adjust VOLUME by the reciprocal."""
    valid = corp_actions.dropna(subset=['factor']).copy()
    panel = panel.sort_values(['symbol', 'date']).reset_index(drop=True)
    mult = np.ones(len(panel))
    symbols_arr = panel['symbol'].to_numpy()
    dates_arr = panel['date'].to_numpy()

    for sym, g in valid.groupby('symbol'):
        idxs = np.where(symbols_arr == sym)[0]
        if len(idxs) == 0:
            continue
        g = g.sort_values('ex_date')
        ex_dates = g['ex_date'].to_numpy()
        factors = g['factor'].to_numpy(dtype=float)
        suffix = np.ones(len(factors) + 1)
        for i in range(len(factors) - 1, -1, -1):
            suffix[i] = suffix[i + 1] * factors[i]
        j = np.searchsorted(ex_dates, dates_arr[idxs], side='right')
        mult[idxs] = suffix[j]

    panel['adj_mult'] = mult
    for c in ('open', 'high', 'low', 'close'):
        panel['adj_' + c] = panel[c] * panel['adj_mult']
    # STATED EXTENSION (see module docstring): share count scales by 1/factor.
    panel['adj_volume'] = panel['volume'] / panel['adj_mult']
    n_adjusted = int((mult != 1.0).sum())
    if not quiet:
        log(f'Corporate-action adjustment applied: {n_adjusted:,} stock-day rows scaled '
            f'(factor != 1.0), {valid["symbol"].nunique()} symbols with >=1 valid action. '
            f'OHLC x factor, VOLUME / factor (stated extension), turnover untouched.')
    return panel


def compute_returns_and_eligibility(panel):
    """Clip-guarded adjusted returns + the frozen three-gate eligibility flag.

    `eligible` is SAME-DAY and gates SIGNALS -- that is exactly what the spec
    says ("adjusted close >= Rs 20 AT SIGNAL TIME") and it is not leaky,
    because a signal on day t is only actionable at day t+1's open.

    `bench_member` is the LAGGED flag and gates BENCHMARK membership. See the
    module docstring, implementation choice (2b): a benchmark that admits a
    stock on the same day it earns the return is not implementable and is
    measurably biased upward (the Rs-20 floor admits a stock the day it jumps
    over the line and drops it the day it falls back).
    """
    panel = panel.sort_values(['symbol', 'date']).reset_index(drop=True)
    panel['prev_adj_close'] = panel.groupby('symbol')['adj_close'].shift(1)
    panel['raw_ret'] = panel['adj_close'] / panel['prev_adj_close'] - 1
    panel['ret'] = panel['raw_ret'].clip(-CLIP, CLIP)
    # SERIES == 'EQ' is already enforced at load.
    panel['eligible'] = ((panel['turnover_lacs'] >= MIN_TURNOVER_LACS)
                         & (panel['adj_close'] >= MIN_PRICE))
    panel['bench_member'] = panel.groupby('symbol')['eligible'].shift(1).fillna(False)
    return panel


def halt_on_clip_guard(panel):
    """delivery_factor_study.py verbatim: >0.1% of ELIGIBLE stock-days with a
    raw |return| > 25% is a data-integrity HALT, not a tunable."""
    sub = panel.loc[panel['eligible'] & panel['raw_ret'].notna(), ['symbol', 'date', 'raw_ret']]
    n_valid = len(sub)
    offenders = sub[sub['raw_ret'].abs() > CLIP]
    frac = (len(offenders) / n_valid) if n_valid else 0.0
    log('')
    log(f'Clip guard: {len(offenders):,}/{n_valid:,} eligible stock-days ({frac * 100:.4f}%) had '
        f'|raw return| > {CLIP * 100:.0f}% (frozen HALT bar: {CLIP_HALT_FRAC * 100:.2f}%).')
    if frac > CLIP_HALT_FRAC:
        log('')
        log('HALT: clip guard fired on more than 0.1% of eligible stock-days. Offenders:')
        for _, row in offenders.sort_values('date').iterrows():
            log(f'  {row.symbol}  {row.date.date()}  raw_return={row.raw_ret * 100:+.1f}%')
        sys.exit(f'HALTED: clip guard exceeded frozen bar ({frac * 100:.4f}% > '
                 f'{CLIP_HALT_FRAC * 100:.2f}%). Inspect the offenders above (brief rule R9).')
    return len(offenders), n_valid, frac


# ===========================================================================
# PREPARE  (run once; the 10 workers then share these artifacts READ-ONLY)
# ===========================================================================
def prep_paths(work_dir):
    return {
        'meta': work_dir / 'prep_meta.json',
        'ew': work_dir / 'ew_returns.csv',
        'universe': work_dir / 'universe.txt',
        'elig_universe': work_dir / 'eligible_universe.txt',
        'excluded': work_dir / 'excluded_short_history.txt',
        'lock': work_dir / '.prep.lock',
    }


def run_prepare(work_dir):
    t0 = time.time()
    work_dir.mkdir(parents=True, exist_ok=True)
    p = prep_paths(work_dir)
    log('=' * 100)
    log('EXHUMATION SWEEP -- PREPARE (panel integrity checks + shared benchmark)')
    log('=' * 100)

    panel, n_files, n_skipped = load_panel()
    corp = load_corp_actions()
    n_nan_factor = halt_on_unresolved_nan_factors(panel, corp)
    panel = apply_corp_action_adjustments(panel, corp)
    panel = compute_returns_and_eligibility(panel)
    n_clip, n_clip_base, clip_frac = halt_on_clip_guard(panel)

    n_elig = int(panel['eligible'].sum())
    log(f'Eligible stock-days: {n_elig:,} ({100 * n_elig / max(len(panel), 1):.2f}% of EQ stock-days) '
        f'under the frozen gate (EQ, turnover >= Rs {MIN_TURNOVER_LACS / 100:.0f}cr, '
        f'adj close >= Rs {MIN_PRICE:.0f}).')

    # --- EW eligible-universe daily return series (delivery_factor_study) ---
    calendar = pd.DatetimeIndex(sorted(panel['date'].unique()))
    tmp = panel.copy()

    def _ew(flag):
        tmp['r'] = tmp['ret'].where(tmp[flag])
        wide = tmp.pivot(index='date', columns='symbol', values='r')
        s = wide.mean(axis=1, skipna=True).reindex(calendar)
        n_nan = int(s.isna().sum())
        return s.fillna(0.0), n_nan, float(wide.notna().sum(axis=1).mean())

    ew, n_ew_nan, mean_names = _ew('bench_member')
    ew_sameday, _, _ = _ew('eligible')
    del tmp
    log('')
    log(f'EW eligible-universe daily return series built over {len(calendar):,} trading days '
        f'({n_ew_nan} days with no member -> return 0.0), mean {mean_names:.0f} names/day.')
    log(f'  BENCHMARK (used)     lagged membership : mean daily {ew.mean() * 100:+.4f}%, '
        f'cumulative {((1 + ew).prod() - 1) * 100:+.2f}%')
    log(f'  DIAGNOSTIC (NOT used) same-day member. : mean daily {ew_sameday.mean() * 100:+.4f}%, '
        f'cumulative {((1 + ew_sameday).prod() - 1) * 100:+.2f}%')
    log('  The gap is the look-ahead premium of admitting a stock to the benchmark on the SAME day')
    log('  it earns the return: the Rs 20 floor admits a name the day it jumps over the line and')
    log('  drops it the day it falls back. Both series average the same ~945 names/day, so the gap')
    log('  is pure selection, not coverage. The lagged series is the one that could actually be')
    log('  held, so it is the one used. It is also the LOWER bar, i.e. the choice that makes this')
    log('  sweep HARDER to fail -- see module docstring, implementation choice (2b).')

    # --- universes ----------------------------------------------------------
    elig_syms = sorted(panel.loc[panel['eligible'], 'symbol'].unique())
    bars = panel.groupby('symbol').size()
    sweep_syms = sorted(s for s in elig_syms if int(bars.get(s, 0)) >= MIN_BARS)
    excluded = sorted(set(elig_syms) - set(sweep_syms))
    bad = [s for s in sweep_syms if ('"' in s or '\\' in s)]
    assert not bad, f'symbols need JSON escaping, refusing to write raw ndjson: {bad}'
    log('')
    log(f'BENCHMARK universe (>=1 eligible day, no other filter) : {len(elig_syms):,} symbols')
    log(f'TRADEABLE universe (also >= {MIN_BARS} EQ bars of history) : {len(sweep_syms):,} symbols')
    log(f'  removed by the {MIN_BARS}-bar history floor              : {len(excluded):,} symbols  '
        f'(listed in {p["excluded"].name}; they REMAIN in the benchmark)')
    lost_days = int(panel.loc[panel['eligible'] & panel['symbol'].isin(excluded)].shape[0])
    log(f'  eligible stock-days those symbols hold               : {lost_days:,} '
        f'({100 * lost_days / max(n_elig, 1):.2f}% of eligible stock-days)')

    # --- write atomically ---------------------------------------------------
    ew_df = pd.DataFrame({'date': calendar, 'ew_ret': ew.to_numpy()})
    _atomic_write(p['ew'], ew_df.to_csv(index=False))
    _atomic_write(p['universe'], '\n'.join(sweep_syms) + '\n')
    _atomic_write(p['elig_universe'], '\n'.join(elig_syms) + '\n')
    _atomic_write(p['excluded'], '\n'.join(excluded) + '\n')
    meta = {
        'spec': SPEC,
        'built_utc': pd.Timestamp.utcnow().isoformat(),
        'n_files': n_files, 'n_files_skipped': n_skipped,
        'panel_rows': int(len(panel)),
        'panel_symbols': int(panel['symbol'].nunique()),
        'panel_first': str(panel['date'].min().date()),
        'panel_last': str(panel['date'].max().date()),
        'n_trading_days': int(len(calendar)),
        'n_eligible_stock_days': n_elig,
        'n_benchmark_symbols': len(elig_syms),
        'n_sweep_symbols': len(sweep_syms),
        'n_excluded_short_history': len(excluded),
        'clip_offenders': int(n_clip), 'clip_base': int(n_clip_base), 'clip_frac': float(clip_frac),
        'corp_action_nan_rows': int(n_nan_factor),
        'ew_days_with_no_eligible_name': n_ew_nan,
        'ew_mean_names_per_day': round(mean_names, 1),
        'ew_mean_daily_ret_lagged': float(ew.mean()),
        'ew_cum_lagged': float((1 + ew).prod() - 1),
        'ew_mean_daily_ret_sameday_DIAGNOSTIC': float(ew_sameday.mean()),
        'ew_cum_sameday_DIAGNOSTIC': float((1 + ew_sameday).prod() - 1),
        'gates': {'min_turnover_lacs': MIN_TURNOVER_LACS, 'min_price': MIN_PRICE,
                  'clip': CLIP, 'min_bars': MIN_BARS},
        'exec': {'slip': SLIP, 'position_rs': POSITION_RS, 'time_stop_bars': TIME_STOP_BARS},
    }
    _atomic_write(p['meta'], json.dumps(meta, indent=2))
    log('')
    log(f'prep artifacts written to {work_dir}')
    for k in ('meta', 'ew', 'universe', 'elig_universe', 'excluded'):
        log(f'  {p[k].name}')
    log(f'prepare runtime: {time.time() - t0:.1f}s')
    return meta


def _atomic_write(path, text):
    tmp = path.with_suffix(path.suffix + f'.tmp{os.getpid()}')
    tmp.write_text(text, encoding='utf-8')
    os.replace(tmp, path)


def ensure_prep(work_dir, quiet=False):
    """Load prep artifacts; build them if missing.

    Race-safe for 10 concurrently launched workers: the first to create the
    lock directory builds, the rest poll for the artifacts. If the builder
    dies the pollers give up after LOCK_TIMEOUT and build for themselves
    (correct either way -- the build is deterministic and writes atomically).
    """
    p = prep_paths(work_dir)
    if not p['meta'].exists():
        work_dir.mkdir(parents=True, exist_ok=True)
        LOCK_TIMEOUT = 3600
        got_lock = False
        try:
            os.mkdir(p['lock'])
            got_lock = True
        except FileExistsError:
            waited = 0
            while not p['meta'].exists() and waited < LOCK_TIMEOUT:
                time.sleep(5)
                waited += 5
        if got_lock:
            try:
                run_prepare(work_dir)
            finally:
                try:
                    os.rmdir(p['lock'])
                except OSError:
                    pass
        elif not p['meta'].exists():
            log('WARN: prep lock holder appears dead; building prep artifacts locally.')
            run_prepare(work_dir)
    meta = json.loads(p['meta'].read_text(encoding='utf-8'))
    ew = pd.read_csv(p['ew'], parse_dates=['date'])
    universe = [s for s in p['universe'].read_text(encoding='utf-8').split('\n') if s]
    if not quiet:
        log(f'prep loaded: {len(universe):,} tradeable symbols, {len(ew):,} trading days, '
            f'panel {meta["panel_first"]} -> {meta["panel_last"]}')
    return meta, ew, universe


# ===========================================================================
# STRATEGY SET  (drift guard)
# ===========================================================================
def leak_flags():
    """retest_all.leak_flags() verbatim (via consensus_probe / zoo_silence)."""
    try:
        a = pd.read_csv(AUDIT_CSV)
        flags = {}
        for _, row in a.iterrows():
            v, wf = row.get('v_trades', 0), row.get('wf_trades', 0)
            if v == 0 and wf == 0:
                flags[row['strategy']] = 'no-data'
            elif v > 0 and abs(wf - v) / max(v, 1) > 0.2:
                flags[row['strategy']] = 'LEAK-SUSPECT'
            else:
                flags[row['strategy']] = 'clean'
        return flags
    except Exception:
        return {}


def assert_clean_set(quiet=False):
    """HARD GATE. The 67-set must be byte-identical to consensus_probe's /
    zoo_silence's. Any registry, audit-CSV or exclusion drift kills the run."""
    flags = leak_flags()
    assert flags, f'HALT: could not read {AUDIT_CSV} -- leak flags are not optional here'
    leak = sorted(n for n in STRATEGY_REGISTRY if flags.get(n) == 'LEAK-SUSPECT')
    assert len(STRATEGY_REGISTRY) == PROBE_REGISTRY_N, (
        f'REGISTRY DRIFT: {len(STRATEGY_REGISTRY)} strategies, probe saw {PROBE_REGISTRY_N}')
    assert leak == PROBE_EXCLUDED_LEAK, (
        f'LEAK-EXCLUSION DRIFT: got {leak}, probe had {PROBE_EXCLUDED_LEAK}')
    missing = [n for n in PROBE_EXCLUDED_ERROR if n not in STRATEGY_REGISTRY]
    assert not missing, f'ERROR-EXCLUSION DRIFT: {missing} no longer in the registry'
    computed = sorted(set(STRATEGY_REGISTRY) - set(leak) - set(PROBE_EXCLUDED_ERROR))
    assert len(computed) == PROBE_CLEAN_N, (
        f'CLEAN-SET DRIFT: {len(computed)} clean, probe had {PROBE_CLEAN_N}')
    assert computed == sorted(CLEAN_67), (
        'CLEAN-SET DRIFT: recomputed clean set != the hard-coded CLEAN_67 list.\n'
        f'  only in recomputed: {sorted(set(computed) - set(CLEAN_67))}\n'
        f'  only in CLEAN_67  : {sorted(set(CLEAN_67) - set(computed))}')
    if not quiet:
        log(f'ASSERT OK: registry {len(STRATEGY_REGISTRY)} - {len(leak)} leak-suspect - '
            f'{len(PROBE_EXCLUDED_ERROR)} a-priori-erroring = {len(computed)} clean, '
            'byte-identical to consensus_probe / zoo_silence.')
    return computed


# ===========================================================================
# TRADE SIMULATION  (retest_all.py fill conventions, one symbol at a time)
# ===========================================================================
def _trade_economics(entry_raw, exit_raw):
    """Rs 20k delivery round trip. Returns (gross, net) or (nan, nan) if the
    position cannot be taken (share price above the whole position size)."""
    buy_px = entry_raw * (1 + SLIP)
    sell_px = exit_raw * (1 - SLIP)
    qty = int(POSITION_RS / buy_px)
    if qty <= 0:
        return np.nan, np.nan
    buy_v, sell_v = qty * buy_px, qty * sell_px
    fees = zerodha_charges.calculate_charges(buy_v, sell_v, is_intraday=False)['total']
    return exit_raw / entry_raw - 1.0, (sell_v - buy_v - fees) / buy_v


class StrategyError(Exception):
    """Raised when the STRATEGY's own code (generate_signals / calculate_stop_loss
    / calculate_take_profit) blows up on wide-universe data. Counted and
    reported per the spec. Anything else propagates and kills the worker --
    a bug in this file must never be laundered into an 'erroring strategy'."""


def simulate_symbol_strategy(strat, sig_df, o, h, l, c, elig, dates, cal_idx, ew_cum, drops):
    """All trades for ONE (strategy, symbol). Returns a list of dicts.

    Entry  : OPEN[p+1] after a LONG signal on an ELIGIBLE bar p.
    Exit   : the strategy's own SL/TP (gap-aware, SL wins same-bar ties,
             fill at the WORSE of stop/open) checked on bars p+1 .. p+10,
             else CLOSE[p+10] -- the universal 10-bar time stop.
    Guard  : one open trade per (strategy, symbol); a signal is ignored while
             a position is open (a signal ON the exit bar is allowed, since
             its entry would be the following bar).

    `cal_idx[i]` is bar i's position in the GLOBAL market calendar, so the
    benchmark compounds over every market day the position was open -- not
    just over the bars this symbol happens to have.
    """
    n = len(o)
    sig = pd.to_numeric(pd.Series(sig_df['signal'].to_numpy()), errors='coerce').fillna(0).to_numpy()
    if len(sig) != n:
        raise StrategyError(f'signal length {len(sig)} != frame length {n}')
    cand = np.flatnonzero((sig == 1) & elig)
    out = []
    blocked_until = -1          # no new entry until candidate pos >= this
    idx_labels = sig_df.index
    for p in cand:
        if p < blocked_until:
            drops['overlap'] += 1
            continue
        e = p + 1
        last = e + TIME_STOP_BARS - 1
        if last > n - 1:
            drops['incomplete_window'] += int((cand >= p).sum())
            break                                   # every later candidate is worse
        entry_raw = o[e]
        if not np.isfinite(entry_raw) or entry_raw <= 0:
            drops['bad_entry_price'] += 1
            continue
        lbl = idx_labels[p]
        try:
            sl = strat.calculate_stop_loss(sig_df, lbl, Signal.BUY)
            ep = sig_df.at[lbl, 'close']
            tp = strat.calculate_take_profit(sig_df, lbl, Signal.BUY, ep, sl)
        except Exception as e_:                      # strategy's own code
            raise StrategyError(f'SL/TP raised: {type(e_).__name__}: {e_}') from e_
        sl = float(sl) if (sl is not None and np.isfinite(sl) and sl > 0) else np.nan
        tp = float(tp) if (tp is not None and np.isfinite(tp) and tp > 0) else np.nan
        sl_ok, tp_ok = np.isfinite(sl), np.isfinite(tp)

        x, exit_raw, reason = last, c[last], 'time'
        for j in range(e, last + 1):
            if sl_ok and l[j] <= sl:                # SL wins same-bar ties (retest_all)
                x, exit_raw, reason = j, min(o[j], sl), 'sl'
                break
            if tp_ok and h[j] >= tp:
                x, exit_raw, reason = j, max(o[j], tp), 'tp'
                break
        blocked_until = x                            # position occupied through bar x

        if not np.isfinite(exit_raw) or exit_raw <= 0:
            drops['bad_exit_price'] += 1
            continue
        gross, net = _trade_economics(entry_raw, exit_raw)
        if not np.isfinite(net):
            drops['qty_zero'] += 1
            blocked_until = -1                       # no position was ever taken
            continue
        ie, ix = cal_idx[e], cal_idx[x]
        bench = ew_cum[ix + 1] / ew_cum[ie] - 1.0    # inclusive [entry_date .. exit_date]
        out.append({'entry_date': dates[e], 'exit_date': dates[x], 'exit_reason': reason,
                    'gross': gross, 'net': net, 'abnormal': net - bench})
    return out


# ===========================================================================
# WORKER
# ===========================================================================
def shard_paths(work_dir, shard, of):
    return (work_dir / f'shard_{shard}_of_{of}.ndjson',
            work_dir / f'shard_{shard}_of_{of}.done',
            work_dir / f'shard_{shard}_of_{of}.progress')


_SYM_TAG = b'"symbol":"'


def _resume_partial(nd_path, my_syms):
    """Crash resume, derived from the PARTIAL FILE ITSELF -- never from a
    recorded byte offset.

    Symbols are processed in a fixed order and each symbol's whole block is
    written, flushed and fsynced before the next one starts. So: scan the
    partial, find where the LAST symbol's block begins, truncate there, and
    declare every symbol EARLIER in the shard order done. The last symbol is
    always re-done (it may have been half-written), which is idempotent
    because its rows were just truncated away.

    Deriving the state this way is deliberate. An earlier version trusted an
    offset written into a progress file, which a torn final write can leave
    plausible-but-wrong (e.g. '...\\t172' when '...\\t1728027' was intended) --
    silently discarding a completed symbol's rows while still marking it done.
    The partial file cannot lie about its own contents.

    Symbols that legitimately produced ZERO trades leave no trace; they are
    simply re-run, which writes nothing and costs only time.
    """
    if not nd_path.exists() or nd_path.stat().st_size == 0:
        return set(), 0
    order = {s: i for i, s in enumerate(my_syms)}
    last_sym, last_start, pos = None, 0, 0
    with open(nd_path, 'rb') as fh:
        for raw in fh:
            if not raw.endswith(b'\n'):
                break                              # torn final line: ignore it
            i = raw.find(_SYM_TAG)
            if i < 0:
                break                              # unparseable: stop trusting here
            j = raw.index(b'"', i + len(_SYM_TAG))
            s = raw[i + len(_SYM_TAG):j].decode('utf-8')
            if s != last_sym:
                if s not in order or (last_sym is not None and order[s] <= order[last_sym]):
                    break                          # out-of-order/foreign symbol: stop here
                last_sym, last_start = s, pos
            pos += len(raw)
    with open(nd_path, 'r+b') as fh:
        fh.truncate(last_start)
    done = set(my_syms[:order[last_sym]]) if last_sym is not None else set()
    return done, last_start


def run_shard(work_dir, shard, of, symbols_limit=None, force=False):
    t0 = time.time()
    work_dir.mkdir(parents=True, exist_ok=True)
    nd_path, done_path, prog_path = shard_paths(work_dir, shard, of)
    if done_path.exists() and not force:
        print(f'shard {shard}/{of}: .done marker present -> nothing to do '
              f'({done_path.name}). Pass --force to recompute.', flush=True)
        return json.loads(done_path.read_text(encoding='utf-8'))

    clean = assert_clean_set()
    meta, ew_df, universe = ensure_prep(work_dir)

    # day numbers (days since epoch) sidestep every datetime64-resolution trap
    cal_days = pd.DatetimeIndex(ew_df['date']).to_numpy().astype('datetime64[D]').astype(np.int64)
    ew_cum = np.empty(len(ew_df) + 1)
    ew_cum[0] = 1.0
    np.cumprod(1.0 + ew_df['ew_ret'].to_numpy(float), out=ew_cum[1:])

    my_syms = universe[shard::of]
    if symbols_limit is not None:
        my_syms = my_syms[:symbols_limit]
    assert my_syms, f'shard {shard} of {of} is empty'

    done_syms, offset = _resume_partial(nd_path, my_syms)
    todo = [s for s in my_syms if s not in done_syms]
    print(f'shard {shard}/{of}: {len(my_syms)} symbols'
          + (f' (--symbols-limit {symbols_limit}: SMOKE)' if symbols_limit else '')
          + (f', resuming with {len(done_syms)} already done' if done_syms else ''), flush=True)

    by_sym = {}
    if todo:
        panel, _, _ = load_panel(symbols=todo, quiet=True)
        corp = load_corp_actions()
        panel = apply_corp_action_adjustments(panel, corp, quiet=True)
        panel = compute_returns_and_eligibility(panel)
        by_sym = {s: g for s, g in panel.groupby('symbol', sort=False)}
        del panel
    print(f'shard {shard}/{of}: panel loaded for {len(by_sym)} symbols in {time.time() - t0:.1f}s',
          flush=True)

    errors = {k: 0 for k in clean}
    drops_total = {k: 0 for k in
                   ('overlap', 'incomplete_window', 'bad_entry_price', 'bad_exit_price', 'qty_zero')}
    reasons_total = {'sl': 0, 'tp': 0, 'time': 0}
    n_trades, n_sym_done, per_sym_secs = 0, 0, []
    # the partial has already been truncated to a symbol boundary -> plain append.
    # the progress file is a human-readable LOG only; resume never reads it.
    prog_path.write_text(''.join(f'{s}\t(resumed)\n' for s in my_syms if s in done_syms),
                         encoding='utf-8')
    fh = open(nd_path, 'a', encoding='utf-8', newline='\n')
    ph = open(prog_path, 'a', encoding='utf-8', newline='\n')
    try:
        for sym in todo:
            ts = time.time()
            g = by_sym.get(sym)
            if g is None or len(g) < MIN_BARS:
                # symbol vanished from the panel between prepare and now
                fh.flush()
                os.fsync(fh.fileno())
                ph.write(f'{sym}\t{fh.tell()}\n')
                ph.flush()
                n_sym_done += 1
                continue
            g = g.sort_values('date')
            df = pd.DataFrame({'open': g['adj_open'].to_numpy(float),
                               'high': g['adj_high'].to_numpy(float),
                               'low': g['adj_low'].to_numpy(float),
                               'close': g['adj_close'].to_numpy(float),
                               'volume': g['adj_volume'].to_numpy(float)},
                              index=pd.DatetimeIndex(g['date'].to_numpy(), name='date'))
            o = df['open'].to_numpy(); h = df['high'].to_numpy()
            l = df['low'].to_numpy(); c = df['close'].to_numpy()
            elig = g['eligible'].to_numpy(bool)
            dates = df.index.to_numpy()
            sym_days = dates.astype('datetime64[D]').astype(np.int64)
            cal_idx = np.searchsorted(cal_days, sym_days)
            assert cal_idx.max() < len(cal_days) and (cal_days[cal_idx] == sym_days).all(), (
                f'{sym}: bar dates missing from the global market calendar')
            lines, sym_trades = [], 0
            for name in clean:
                drops = {k: 0 for k in drops_total}
                try:
                    strat = STRATEGY_REGISTRY[name]()
                    try:
                        sig_df = strat.generate_signals(df.copy())
                    except Exception as e_:
                        raise StrategyError(
                            f'generate_signals raised: {type(e_).__name__}: {e_}') from e_
                    trades = simulate_symbol_strategy(strat, sig_df, o, h, l, c, elig,
                                                      dates, cal_idx, ew_cum, drops)
                except StrategyError as e_:
                    errors[name] += 1
                    if errors[name] <= 1:
                        print(f'      STRATEGY ERROR {name} on {sym}: {e_}', flush=True)
                    continue
                for k, v in drops.items():
                    drops_total[k] += v
                for tr in trades:
                    reasons_total[tr['exit_reason']] += 1
                    lines.append(
                        '{"strategy":"%s","symbol":"%s","entry_date":"%s","exit_date":"%s",'
                        '"exit_reason":"%s","gross":%.8f,"net":%.8f,"abnormal":%.8f}\n'
                        % (name, sym, str(tr['entry_date'])[:10], str(tr['exit_date'])[:10],
                           tr['exit_reason'], tr['gross'], tr['net'], tr['abnormal']))
                sym_trades += len(trades)
            fh.writelines(lines)
            fh.flush()
            os.fsync(fh.fileno())
            ph.write(f'{sym}\t{fh.tell()}\n')
            ph.flush()
            n_trades += sym_trades
            n_sym_done += 1
            per_sym_secs.append(time.time() - ts)
            print(f'  [{n_sym_done}/{len(todo)}] {sym:<16} bars={len(df):>5} '
                  f'trades={sym_trades:>6} {time.time() - ts:6.1f}s '
                  f'(avg {np.mean(per_sym_secs):.1f}s/sym, elapsed {time.time() - t0:.0f}s)',
                  flush=True)
    finally:
        fh.close()
        ph.close()

    elapsed = time.time() - t0
    marker = {
        'shard': shard, 'of': of, 'symbols_limit': symbols_limit,
        'smoke': symbols_limit is not None,
        'symbols': my_syms, 'n_symbols': len(my_syms),
        'n_trades_this_run': n_trades,
        'ndjson_bytes': nd_path.stat().st_size if nd_path.exists() else 0,
        'errors_per_strategy': {k: v for k, v in errors.items() if v},
        'n_strategies': len(clean),
        'drops': drops_total, 'exit_reasons': reasons_total,
        'elapsed_s': round(elapsed, 1),
        'sec_per_symbol_mean': round(float(np.mean(per_sym_secs)), 2) if per_sym_secs else None,
        'prep_panel_last': meta['panel_last'],
        'finished_utc': pd.Timestamp.utcnow().isoformat(),
    }
    _atomic_write(done_path, json.dumps(marker, indent=2))
    print(f'shard {shard}/{of}: DONE {len(my_syms)} symbols, {n_trades:,} trades this run, '
          f'{elapsed:.1f}s ({marker["sec_per_symbol_mean"]}s/symbol) -> {nd_path.name}', flush=True)
    return marker


# ===========================================================================
# MERGE
# ===========================================================================
def _iter_ndjson(path, batch=200_000):
    buf = []
    with open(path, 'r', encoding='utf-8') as fh:
        for line in fh:
            if not line.strip():
                continue
            buf.append(json.loads(line))
            if len(buf) >= batch:
                yield buf
                buf = []
    if buf:
        yield buf


def run_merge(work_dir, of, smoke=False):
    t0 = time.time()
    log('=' * 100)
    log('EXHUMATION SWEEP -- MERGE' + ('   *** SMOKE ***' if smoke else ''))
    log('=' * 100)
    clean = assert_clean_set()
    meta, ew_df, universe = ensure_prep(work_dir)
    strat_idx = {s: i for i, s in enumerate(clean)}
    sym_idx = {s: i for i, s in enumerate(universe)}
    calendar = pd.DatetimeIndex(ew_df['date'])
    day_idx = {str(d.date()): i for i, d in enumerate(calendar)}
    n_days = len(calendar)

    markers, missing = [], []
    for i in range(of):
        _, done_path, _ = shard_paths(work_dir, i, of)
        if done_path.exists():
            markers.append(json.loads(done_path.read_text(encoding='utf-8')))
        else:
            missing.append(i)
    if missing:
        msg = f'{len(missing)} shard(s) have no .done marker: {missing}'
        if smoke:
            log(f'SMOKE: {msg} -- completeness assert DOWNGRADED to a warning.')
        else:
            sys.exit(f'HALTED: {msg}. Re-run those workers before merging.')
    assert markers, 'HALTED: no completed shards found'

    smoky = [m['shard'] for m in markers if m.get('symbols_limit') is not None]
    if smoky and not smoke:
        sys.exit(f'HALTED: shard(s) {smoky} were run with --symbols-limit (a SMOKE restriction). '
                 f'Recompute them without the limit, or pass --smoke to merge partial data.')

    # --- coverage -----------------------------------------------------------
    covered, overlap = set(), set()
    for m in markers:
        s = set(m['symbols'])
        overlap |= (covered & s)
        covered |= s
    log(f'shards found            : {len(markers)} of {of}')
    log(f'symbols covered         : {len(covered):,}')
    log(f'tradeable universe size : {len(universe):,}')
    if overlap:
        sys.exit(f'HALTED: {len(overlap)} symbol(s) appear in more than one shard: '
                 f'{sorted(overlap)[:10]}')
    log('ASSERT OK: shard symbol sets are pairwise DISJOINT '
        '(so no (strategy, symbol, entry_date) key can straddle two shards).')
    uncovered = set(universe) - covered
    extra = covered - set(universe)
    if extra:
        sys.exit(f'HALTED: {len(extra)} shard symbol(s) are not in the tradeable universe: '
                 f'{sorted(extra)[:10]}')
    if uncovered:
        msg = f'{len(uncovered)} universe symbol(s) not covered by any shard'
        if smoke:
            log(f'SMOKE: {msg} -- coverage assert DOWNGRADED to a warning '
                f'(expected: --symbols-limit was used).')
        else:
            sys.exit(f'HALTED: {msg}, e.g. {sorted(uncovered)[:10]}')
    else:
        log('ASSERT OK: union of shard symbol sets == the tradeable universe, exactly.')

    # --- stream the partials ------------------------------------------------
    agg = {}          # strategy -> era -> counters
    weeks = {}        # strategy -> era -> iso_week -> [n, sum_abnormal]
    keys_all = []     # exact 64-bit-safe integer encoding of the dedupe key
    n_rows, n_bad_era = 0, 0
    for m in markers:
        nd_path, _, _ = shard_paths(work_dir, m['shard'], of)
        if not nd_path.exists():
            log(f'  WARN: {nd_path.name} missing though its .done marker exists')
            continue
        for batch in _iter_ndjson(nd_path):
            df = pd.DataFrame(batch)
            n_rows += len(df)
            si = df['strategy'].map(strat_idx).to_numpy()
            yi = df['symbol'].map(sym_idx).to_numpy()
            di = df['entry_date'].map(day_idx).to_numpy()
            if pd.isna(si).any() or pd.isna(yi).any() or pd.isna(di).any():
                sys.exit('HALTED: a partial row references an unknown strategy / symbol / date.')
            keys_all.append((si.astype(np.int64) * len(universe) + yi.astype(np.int64))
                            * n_days + di.astype(np.int64))
            ed = pd.to_datetime(df['entry_date'], format='%Y-%m-%d')
            era = np.where(ed <= TRAIN_END, 'train',
                           np.where(ed >= VAL_START, 'validation', 'none'))
            n_bad_era += int((era == 'none').sum())
            iso = ed.dt.isocalendar()
            wk = (iso['year'].astype(int).astype(str) + '-W'
                  + iso['week'].astype(int).astype(str).str.zfill(2)).to_numpy()
            df['era'] = era
            df['iso_week'] = wk
            for (name, e), g in df.groupby(['strategy', 'era'], sort=False):
                if e == 'none':
                    continue
                a = agg.setdefault(name, {}).setdefault(e, {
                    'n': 0, 'sum_net': 0.0, 'sum_gross': 0.0, 'sum_abn': 0.0,
                    'n_net_pos': 0, 'n_abn_pos': 0, 'sl': 0, 'tp': 0, 'time': 0})
                a['n'] += len(g)
                a['sum_net'] += float(g['net'].sum())
                a['sum_gross'] += float(g['gross'].sum())
                a['sum_abn'] += float(g['abnormal'].sum())
                a['n_net_pos'] += int((g['net'] > 0).sum())
                a['n_abn_pos'] += int((g['abnormal'] > 0).sum())
                for r, k in g['exit_reason'].value_counts().items():
                    a[r] += int(k)
                wmap = weeks.setdefault(name, {}).setdefault(e, {})
                for w, gw in g.groupby('iso_week', sort=False):
                    slot = wmap.setdefault(w, [0, 0.0])
                    slot[0] += len(gw)
                    slot[1] += float(gw['abnormal'].sum())

    # --- dedupe assert (EXACT: the key is a bijective integer encoding) -----
    keys = np.concatenate(keys_all) if keys_all else np.zeros(0, dtype=np.int64)
    n_unique = int(np.unique(keys).size)
    log('')
    log(f'trade rows read         : {n_rows:,}')
    log(f'distinct (strategy, symbol, entry_date) keys: {n_unique:,}')
    if n_unique != n_rows:
        sys.exit(f'HALTED: {n_rows - n_unique:,} DUPLICATE (strategy, symbol, entry_date) rows.')
    log('ASSERT OK: zero duplicate (strategy, symbol, entry_date) trades. The key is encoded '
        'as strategy_idx*n_sym*n_day + symbol_idx*n_day + day_idx -- a bijection, not a hash, '
        'so this is exact.')
    if n_bad_era:
        log(f'  NOTE: {n_bad_era:,} trades fell outside both eras (entry between '
            f'{TRAIN_END.date()} and {VAL_START.date()}) -- impossible by construction; investigate.')

    errors_per_strategy = {}
    for m in markers:
        for k, v in m.get('errors_per_strategy', {}).items():
            errors_per_strategy[k] = errors_per_strategy.get(k, 0) + v
    drops = {}
    reasons = {}
    for m in markers:
        for k, v in m.get('drops', {}).items():
            drops[k] = drops.get(k, 0) + v
        for k, v in m.get('exit_reasons', {}).items():
            reasons[k] = reasons.get(k, 0) + v

    stats = {
        'spec': SPEC, 'smoke': smoke, 'of': of,
        'merged_utc': pd.Timestamp.utcnow().isoformat(),
        'n_shards_found': len(markers), 'n_shards_expected': of,
        'n_symbols_covered': len(covered), 'n_universe': len(universe),
        'n_uncovered': len(uncovered), 'n_rows': n_rows,
        'n_symbols_attempted': len(covered),
        'errors_per_strategy': errors_per_strategy,
        'drops': drops, 'exit_reasons': reasons,
        'agg': agg, 'weeks': weeks,
        'prep_meta': meta,
        'shard_elapsed_s': {str(m['shard']): m.get('elapsed_s') for m in markers},
    }
    out = work_dir / 'merged_stats.json'
    _atomic_write(out, json.dumps(stats))
    log('')
    log(f'strategies with >=1 trade: {len(agg)} of {len(clean)}')
    log(f'strategies that errored on >=1 symbol: {len(errors_per_strategy)}')
    log(f'dropped-signal accounting (whole sweep): {drops}')
    log(f'exit-reason mix (whole sweep)          : {reasons}')
    log(f'merged stats -> {out}   ({out.stat().st_size / 1e6:.1f} MB)')
    log(f'merge runtime: {time.time() - t0:.1f}s')
    return stats


# ===========================================================================
# VERDICT
# ===========================================================================
def cluster_t_from_weeks(wmap):
    """Cluster-robust t by ISO week of the ENTRY date -- FROZEN FORMULA, copied
    verbatim from announcement_drift_confirmation.py::cluster_robust_t (and
    reused by zoo_silence_confirmation.py). A one-sample t on the WEEKLY
    CLUSTER MEANS, not on raw trades. Here the weekly means are reconstructed
    exactly from the merged (count, sum) pairs -- identical arithmetic."""
    means = np.array([s / n for n, s in wmap.values() if n > 0], dtype=float)
    n_weeks = len(means)
    if n_weeks < 2:
        return np.nan, n_weeks
    pooled_mean = means.mean()
    pooled_std = means.std(ddof=1)
    if not np.isfinite(pooled_std) or pooled_std == 0:
        return np.nan, n_weeks
    return pooled_mean / (pooled_std / np.sqrt(n_weeks)), n_weeks


def _banner(lines, width=118, ch='*'):
    log(ch * width)
    for s in lines:
        log(f'{ch * 3} {s:<{width - 8}} {ch * 3}')
    log(ch * width)


def print_frozen_header(smoke):
    log('=' * 118)
    log('EXHUMATION SWEEP -- FINAL AUDIT OF THE STRATEGY ZOO ON THE WIDE NSE PANEL')
    log('PRE-REGISTERED, FROZEN SPEC. Every rule below was fixed before this script ran.')
    log('=' * 118)
    log(f'Spec        : {SPEC}   (APPROVED & FROZEN 2026-07-29)')
    log('Origin      : user proposal -- "backtest the dead strategies on the widest data and see if')
    log('              anything is worthy". NOT a new-idea hunt: the FINAL audit of the existing zoo.')
    log('              One shot, then the book on price-pattern strategies closes.')
    log('STATED PRIOR (recorded before any result): the zoo died on 48 liquid large caps at 0.05%/side.')
    log('              The wide universe RAISES the cost bar (0.2%/side, smallcap spreads), and the two')
    log('              prior wide-universe tests (breadth momentum, delivery factor) both failed hard on')
    log('              this exact panel. Expected outcome: 137-0 stands.')
    log('')
    log('--- FROZEN DATA RULES ---')
    log('  PANEL     : data/bhavcopy_full/ -- 3,204 NSE stocks, 2019-10-01 .. 2026-07, series EQ.')
    log('  CORP ACTS : back-adjusted via data/corp_actions_adjustments.csv; HALT if any NaN-factor')
    log('              action touches a date the study uses. delivery_factor_study.py convention.')
    log(f'  CLIP GUARD: adjusted daily returns clipped +/-{CLIP * 100:.0f}%; HALT if that fires on more than')
    log(f'              {CLIP_HALT_FRAC * 100:.1f}% of eligible stock-days (brief rule R9, not a tunable).')
    log(f'  ELIGIBLE  : series EQ, turnover >= Rs {MIN_TURNOVER_LACS / 100:.0f} crore, adjusted close >= '
        f'Rs {MIN_PRICE:.0f} -- at SIGNAL time.')
    log(f'  ZOO       : the SAME {PROBE_CLEAN_N}-strategy clean set as consensus_probe / zoo_silence')
    log(f'              ({PROBE_REGISTRY_N} registered - {len(PROBE_EXCLUDED_LEAK)} leak-suspects - '
        f'{len(PROBE_EXCLUDED_ERROR)} erroring). Asserted byte-identical.')
    log('')
    log('--- FROZEN EXECUTION MODEL ---')
    log("  SIGNALS   : each strategy's own vectorised generate_signals() per symbol; LONG signals only")
    log('              (multi-day shorts untradeable), counted only on ELIGIBLE stock-days.')
    log('  ENTRY     : next trading day OPEN.')
    log("  EXIT      : the strategy's own SL/TP where defined, gap-aware (fill at the WORSE of stop and")
    log(f'              open when the bar gaps through; SL wins same-bar ties), else/until the universal')
    log(f'              {TIME_STOP_BARS}-trading-day time stop -- whichever comes first. ONE convention for the whole zoo.')
    log('  OVERLAP   : one open trade per (strategy, symbol); re-signals ignored while a position is open.')
    log(f'  COSTS     : Rs {POSITION_RS:,} delivery position; zerodha_charges.calculate_charges(...)["total"]')
    log(f'              -- the KEY, never sum(.values()) -- plus {SLIP * 100:.1f}%/side slippage.')
    log('  BENCHMARK : per-trade ABNORMAL return = net trade return MINUS the equal-weight')
    log('              eligible-universe return compounded over the identical holding window')
    log('              (frictionless, daily rebalanced; membership lagged one day -- see (2b)).')
    log('')
    log('--- FROZEN SPLIT AND VERDICT (declared test count: 67) ---')
    log(f'  TRAIN      {TRAIN_START.date()} .. {TRAIN_END.date()}  -- reported, informational.')
    log(f'  VALIDATION {VAL_START.date()} .. {VAL_END.date()}  -- the verdict era.')
    log('  A strategy is a SURVIVOR only if ALL FOUR hold:')
    log(f'    1. >= {MIN_VAL_TRADES} validation trades          (else NODATA: underpowered, recorded, NOT a pass)')
    log('    2. validation mean net ABNORMAL return > 0')
    log(f'    3. cluster-robust t >= +{T_THRESHOLD:.1f}, clustered by ISO week of the ENTRY date -- the')
    log(f'       Bonferroni bar for {DECLARED_TESTS} simultaneous tests at alpha=0.05 (0.05/{DECLARED_TESTS} -> one-sided')
    log(f'       z ~ {T_THRESHOLD:.1f}). This is the resurrection-lottery guard: {DECLARED_TESTS} dead strategies WILL')
    log('       throw ~3 nominal t>=2 passes by chance; the bar is set so chance survivors are')
    log('       expected ~0.05 across the WHOLE sweep.')
    log('    4. train-era mean net abnormal return also > 0 (no sign flip).')
    log('  No per-strategy parameter variation, no timeframe variation, no post-hoc subgroups.')
    log('  "Worked on smallcaps only" = FAIL, recorded at most as an unregistered observation.')
    log('  Survivors (if any): incubator-candidacy DISCUSSION with a fresh phase-2 spec. Never money.')
    log('  Non-survivors: the graveyard verdict becomes FINAL on the widest data available.')
    log('')
    log('--- CAVEATS (stated before results, per spec) ---')
    log(f'  - The universal {TIME_STOP_BARS}-day time-stop backstop means strategies whose native exits differ are')
    log('    tested in a HARMONIZED form; a survivor must be re-validated under its own exact exit')
    log('    before candidacy. A -1 signal does NOT close a position here (spec lists SL/TP/time only).')
    log('  - Smallcap slippage of 0.2%/side remains an INFERENCE, not a measurement.')
    log('  - A strategy whose generate_signals() raises on wide-universe data quirks is skipped for')
    log(f'    that symbol and COUNTED; a strategy that errors on more than {ERROR_SKIP_FRAC * 100:.0f}% of symbols is')
    log('    reported as NODATA (skipped), never as a pass or a fail.')
    log('')
    log('--- IMPLEMENTATION CHOICES THE SPEC DOES NOT FULLY PIN DOWN (flagged, not buried) ---')
    log(f'  (1) TIME STOP ARITHMETIC: "{TIME_STOP_BARS}-trading-day time stop" is read as at most {TIME_STOP_BARS} bars')
    log('      INCLUDING the entry bar -> entry OPEN[p+1], time-stop exit CLOSE[p+10]. The "10 bars')
    log('      AFTER entry" reading (CLOSE[p+11]) is one bar longer and is NOT also computed --')
    log('      computing both would double the declared test count.')
    log('  (2) BENCHMARK WINDOW: the EW leg is compounded over market days [entry_date .. exit_date]')
    log('      inclusive. The EW series is close-to-close, so its first day starts at close(e-1)')
    log('      while the trade starts at open(e): the benchmark carries one extra overnight gap the')
    log('      trade does not. That is the CONSERVATIVE side (overnight drift is positive on average,')
    log('      so abnormal returns are if anything understated). The anti-conservative alignment was')
    log('      available and was not taken.')
    log('  (2b) BENCHMARK MEMBERSHIP IS LAGGED ONE DAY. The spec\'s same-day eligibility gate is')
    log('      correct for SIGNALS (a day-t signal is only actionable at t+1 open) but is not')
    log('      implementable as index membership: the Rs 20 floor would admit a stock on the very')
    log('      day it jumps over the line and drop it on the day it falls back. MEASURED ON THIS')
    log('      PANEL: same-day membership gives mean EW daily +0.2962% (cum +12,337%); membership')
    log('      decided by the symbol\'s PREVIOUS bar gives +0.0902% (cum +296%) -- both averaging')
    log('      ~945 names/day, so the gap is pure selection, not coverage. The LAGGED series is')
    log('      used. Note the direction: it is the LOWER benchmark, so it makes abnormal returns')
    log('      LARGER and this sweep HARDER to fail. The inflated benchmark would have handed the')
    log('      stated prior a free win, which a pre-registered audit must not do.')
    log(f'  (3) TRADEABLE vs BENCHMARK UNIVERSE: the BENCHMARK is the eligible universe exactly as')
    log(f'      specified. The TRADEABLE universe additionally requires >= {MIN_BARS} EQ bars of history --')
    log('      the universe convention of retest_all / consensus_probe / zoo_silence. It is a')
    log('      data-sufficiency rule, not a performance filter, it is mildly survivorship-flavoured,')
    log('      and the symbols it removes are counted below and listed in the work dir.')
    log('  (4) VOLUME IS CORP-ACTION ADJUSTED (volume / factor), unlike delivery_factor_study which')
    log('      never consumed volume. Without it every 1:1 bonus looks like a 2x volume spike to the')
    log('      volume-breakout strategies. Turnover (a rupee quantity) is untouched.')
    log('  (5) NO artificial warm-up floor is applied (consensus_probe dropped 252 bars; this spec')
    log('      does not ask for it). Indicators warm up naturally inside each symbol\'s own history.')
    log('')
    if smoke:
        _banner([
            'SMOKE MODE. The numbers below come from a DELIBERATELY INCOMPLETE shard subset run',
            'with --symbols-limit. They are an end-to-end PLUMBING CHECK and nothing else.',
            'No PASS, FAIL, SURVIVOR or NODATA line printed below is evidence about any strategy.',
            f'The real verdict is written by a full 10-shard run to {OUT_FILE.name}.',
        ])
        log('')


def run_verdict(work_dir, smoke=False):
    t0 = time.time()
    stats_path = work_dir / 'merged_stats.json'
    if not stats_path.exists():
        sys.exit(f'HALTED: {stats_path} not found. Run --merge first.')
    stats = json.loads(stats_path.read_text(encoding='utf-8'))
    if stats.get('smoke') and not smoke:
        sys.exit('HALTED: merged_stats.json was produced by a SMOKE merge. Re-merge a complete '
                 'sweep, or pass --smoke to render a plumbing-check verdict.')
    clean = assert_clean_set(quiet=True)
    _LINES.clear()
    print_frozen_header(smoke or bool(stats.get('smoke')))

    meta = stats['prep_meta']
    log('--- DATA ACTUALLY USED ---')
    log(f'  panel               : {meta["panel_rows"]:,} EQ stock-days, {meta["panel_symbols"]:,} symbols, '
        f'{meta["panel_first"]} -> {meta["panel_last"]} ({meta["n_trading_days"]:,} trading days)')
    log(f'  eligible stock-days : {meta["n_eligible_stock_days"]:,}')
    log(f'  benchmark universe  : {meta["n_benchmark_symbols"]:,} symbols (>=1 eligible day)')
    log(f'  tradeable universe  : {meta["n_sweep_symbols"]:,} symbols '
        f'(also >= {meta["gates"]["min_bars"]} bars); '
        f'{meta["n_excluded_short_history"]:,} removed by the history floor')
    log(f'  clip guard          : {meta["clip_offenders"]:,}/{meta["clip_base"]:,} eligible stock-days '
        f'({meta["clip_frac"] * 100:.4f}%) -- under the {CLIP_HALT_FRAC * 100:.1f}% HALT bar')
    log(f'  EW benchmark (used) : mean daily {meta.get("ew_mean_daily_ret_lagged", float("nan")) * 100:+.4f}%, '
        f'cumulative {meta.get("ew_cum_lagged", float("nan")) * 100:+.2f}% over the panel, '
        f'{meta.get("ew_mean_names_per_day")} names/day (lagged membership)')
    log(f'  [diagnostic, unused]: same-day membership would have been mean daily '
        f'{meta.get("ew_mean_daily_ret_sameday_DIAGNOSTIC", float("nan")) * 100:+.4f}% '
        f'({meta.get("ew_cum_sameday_DIAGNOSTIC", float("nan")) * 100:+.0f}%) -- see choice (2b)')
    log(f'  symbols swept       : {stats["n_symbols_covered"]:,} of {stats["n_universe"]:,} '
        f'({stats["n_shards_found"]} of {stats["n_shards_expected"]} shards)')
    log(f'  trades recorded     : {stats["n_rows"]:,}')
    log(f'  exit-reason mix     : {stats["exit_reasons"]}')
    log(f'  dropped signals     : {stats["drops"]}')
    log('      overlap           = re-signal while a position was already open (by design)')
    log(f'      incomplete_window = signal too close to the symbol\'s last bar for a full '
        f'{TIME_STOP_BARS}-bar hold')
    log('      qty_zero          = share price above the whole Rs 20,000 position -> no trade possible')
    log('      bad_entry/exit    = non-finite or non-positive adjusted price at the fill bar')
    log('')

    n_sym = stats['n_symbols_covered']
    errs = stats.get('errors_per_strategy', {})
    agg, weeks = stats['agg'], stats['weeks']

    rows = []
    for name in clean:
        a_tr = agg.get(name, {}).get('train')
        a_va = agg.get(name, {}).get('validation')
        w_va = weeks.get(name, {}).get('validation', {})
        n_err = errs.get(name, 0)
        err_frac = n_err / n_sym if n_sym else 0.0
        t, n_weeks = cluster_t_from_weeks(w_va) if w_va else (np.nan, 0)
        r = {
            'name': name,
            'n_err': n_err, 'err_frac': err_frac,
            'tr_n': a_tr['n'] if a_tr else 0,
            'tr_net': (a_tr['sum_net'] / a_tr['n']) if a_tr and a_tr['n'] else np.nan,
            'tr_abn': (a_tr['sum_abn'] / a_tr['n']) if a_tr and a_tr['n'] else np.nan,
            'va_n': a_va['n'] if a_va else 0,
            'va_net': (a_va['sum_net'] / a_va['n']) if a_va and a_va['n'] else np.nan,
            'va_gross': (a_va['sum_gross'] / a_va['n']) if a_va and a_va['n'] else np.nan,
            'va_abn': (a_va['sum_abn'] / a_va['n']) if a_va and a_va['n'] else np.nan,
            'va_win': (a_va['n_net_pos'] / a_va['n']) if a_va and a_va['n'] else np.nan,
            't': t, 'n_weeks': n_weeks,
        }
        # frozen criteria
        r['skipped'] = err_frac > ERROR_SKIP_FRAC
        r['c1'] = (not r['skipped']) and r['va_n'] >= MIN_VAL_TRADES
        r['c2'] = bool(r['c1'] and np.isfinite(r['va_abn']) and r['va_abn'] > 0)
        r['c3'] = bool(r['c1'] and np.isfinite(r['t']) and r['t'] >= T_THRESHOLD)
        r['c4'] = bool(r['c1'] and np.isfinite(r['tr_abn']) and r['tr_abn'] > 0)
        r['survivor'] = bool(r['c1'] and r['c2'] and r['c3'] and r['c4'])
        if r['skipped']:
            r['nodata'] = f'errored on {n_err}/{n_sym} symbols (>{ERROR_SKIP_FRAC * 100:.0f}%)'
        elif r['tr_n'] == 0 and r['va_n'] == 0:
            r['nodata'] = 'SILENT -- 0 trades in either era (emits no LONG signal on daily bars)'
        elif r['va_n'] < MIN_VAL_TRADES:
            r['nodata'] = f'{r["va_n"]} validation trades < {MIN_VAL_TRADES}'
        else:
            r['nodata'] = None
        r['silent'] = (r['tr_n'] == 0 and r['va_n'] == 0)
        rows.append(r)

    rows.sort(key=lambda r: (-(r['t'] if np.isfinite(r['t']) else -1e9), r['name']))

    log('=' * 118)
    log('PER-STRATEGY RESULTS -- sorted by validation cluster-robust t (best first)')
    log('=' * 118)
    log('mean_net / mean_abn are PER-TRADE means in percent. abn = net minus the EW eligible-universe')
    log('return over the identical window. t = one-sample t on ISO-WEEK CLUSTER MEANS of validation')
    log('abnormal returns (frozen formula, announcement_drift_confirmation.py::cluster_robust_t).')
    log('')
    log(f'{"strategy":<26} {"tr_N":>7} {"tr_net%":>8} {"tr_abn%":>8} | '
        f'{"val_N":>7} {"val_net%":>9} {"val_abn%":>9} {"win%":>6} {"wks":>5} {"t":>8}  '
        f'{"1":>1}{"2":>1}{"3":>1}{"4":>1}  {"verdict":<9} {"err":>5}')
    log('-' * 118)

    def f(x, w, p=4):
        return f'{100 * x:>{w}.{p}f}' if np.isfinite(x) else f'{"--":>{w}}'

    for r in rows:
        flags = ''.join('Y' if r[k] else '.' for k in ('c1', 'c2', 'c3', 'c4'))
        verdict = 'SURVIVOR' if r['survivor'] else ('NODATA' if r['nodata'] else 'FAIL')
        tstr = f'{r["t"]:>8.3f}' if np.isfinite(r['t']) else f'{"--":>8}'
        log(f'{r["name"]:<26} {r["tr_n"]:>7,} {f(r["tr_net"], 8)} {f(r["tr_abn"], 8)} | '
            f'{r["va_n"]:>7,} {f(r["va_net"], 9)} {f(r["va_abn"], 9)} '
            f'{f(r["va_win"], 6, 1)} {r["n_weeks"]:>5} {tstr}  {flags}  {verdict:<9} '
            f'{r["n_err"]:>5}')
    log('-' * 118)
    log('flag columns: 1 = >=100 validation trades, 2 = val mean abnormal > 0, '
        f'3 = cluster t >= +{T_THRESHOLD:.1f}, 4 = train mean abnormal > 0')

    survivors = [r for r in rows if r['survivor']]
    nodata = [r for r in rows if r['nodata']]
    tested = [r for r in rows if not r['nodata']]
    log('')
    log('=' * 118)
    log('SURVIVORS')
    log('=' * 118)
    if survivors:
        for r in survivors:
            log(f'  {r["name"]:<26} val_N={r["va_n"]:,}  val_abn={100 * r["va_abn"]:+.4f}%  '
                f't={r["t"]:+.3f} over {r["n_weeks"]} ISO weeks  train_abn={100 * r["tr_abn"]:+.4f}%')
        log('')
        log(f'  {len(survivors)} strategy(ies) cleared ALL FOUR frozen criteria including the')
        log(f'  Bonferroni bar of t >= +{T_THRESHOLD:.1f} for {DECLARED_TESTS} simultaneous tests.')
        log('  Per the frozen spec this earns an INCUBATOR-CANDIDACY DISCUSSION and a fresh phase-2')
        log('  spec -- never money, never a deployment, and never a skip of the October Contract.')
        log('  Mandatory before any candidacy: re-validate under the strategy\'s OWN native exit')
        log(f'  (the universal {TIME_STOP_BARS}-day time stop harmonised it here) -- spec caveat 1.')
    else:
        log('  (empty)')
        log('')
        log('  NO strategy cleared all four frozen criteria. The stated prior held.')
    log('')
    log('=' * 118)
    log('NODATA (recorded, NOT a pass and NOT a fail)')
    log('=' * 118)
    if nodata:
        for r in sorted(nodata, key=lambda r: (-r['va_n'], r['name'])):
            log(f'  {r["name"]:<26} {r["nodata"]}')
        silent = [r['name'] for r in nodata if r.get('silent')]
        if silent:
            log('')
            log(f'  {len(silent)} of the above are SILENT -- they emit no long signal on daily bars at all,')
            log('  so they cannot be tested and are not a failure of anything measured here. This is a')
            log('  PRE-EXISTING property of the zoo, not a wide-panel artifact: consensus_probe.py')
            log('  recorded 0 long-cells for exactly these names on the 48 NIFTY symbols too')
            log('  (consensus_probe_results.txt, "least-firing strategies"). They are almost certainly')
            log('  intraday-intended strategies whose conditions never fire on daily bars.')
            log(f'  Effective number of testable strategies is therefore {len(clean) - len(silent)}, not {len(clean)}. The')
            log(f'  Bonferroni bar was pre-registered at {DECLARED_TESTS} tests and is NOT relaxed to match --')
            log('  moving a frozen threshold after seeing which strategies were testable is exactly the')
            log('  move this spec exists to prevent. The bar stays where it was declared (stricter).')

    n_nom2 = sum(1 for r in tested if np.isfinite(r['t']) and r['t'] >= 2.0)
    n_pos = sum(1 for r in tested if np.isfinite(r['va_abn']) and r['va_abn'] > 0)
    log('')
    log('=' * 118)
    log('SWEEP SUMMARY')
    log('=' * 118)
    log(f'  strategies in the clean set            : {len(clean)}')
    log(f'  strategies carrying a verdict          : {len(tested)}')
    log(f'  strategies recorded NODATA             : {len(nodata)}')
    log(f'  positive validation mean abnormal      : {n_pos} of {len(tested)}')
    log(f'  nominal t >= +2.0 (NOT the bar)        : {n_nom2} of {len(tested)}   '
        f'[~{0.05 * len(tested):.1f} expected by chance alone]')
    log(f'  cleared the Bonferroni bar t >= +{T_THRESHOLD:.1f}    : {len(survivors)} of {len(tested)}   '
        f'[~{0.05:.2f} expected by chance across the whole sweep]')
    if tested:
        best = max(tested, key=lambda r: r['t'] if np.isfinite(r['t']) else -1e9)
        log(f'  best validation t                      : {best["name"]} at t={best["t"]:+.3f} '
            f'(val_abn={100 * best["va_abn"]:+.4f}%, N={best["va_n"]:,})')
    log('')
    if smoke or stats.get('smoke'):
        _banner([
            'SMOKE RUN -- NOT THE VERDICT. Partial symbol coverage by construction.',
            'Nothing above is evidence about any strategy; this file exists only to prove the',
            'plumbing runs end to end (prepare -> shard -> partial -> merge -> verdict).',
        ])
    else:
        log('=' * 118)
        log(f'FINAL RECORDED OUTCOME: {len(survivors)} SURVIVOR(S) out of {DECLARED_TESTS} declared tests.')
        if not survivors:
            log('The zoo\'s graveyard verdict is FINAL on the widest data this project will hold.')
            log('The price-pattern-strategy family is closed. No "but what if wider" asterisk remains.')
        log('No threshold was moved, no alternate cut was shopped, no subgroup was mined. The declared')
        log(f'test count was {DECLARED_TESTS} and {len(tested)} of them carried a verdict.')
        log('=' * 118)
    log(f'verdict runtime: {time.time() - t0:.1f}s')

    out = OUT_FILE_SMOKE if (smoke or stats.get('smoke')) else OUT_FILE
    flush_out(out)
    print(f'\nFull output saved to {out}')
    return rows


# ===========================================================================
def parse_args():
    p = argparse.ArgumentParser(description=__doc__,
                                formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument('--prepare', action='store_true', help='build the shared prep artifacts, then exit')
    p.add_argument('--shard', type=int, default=None, help='worker: shard index (0-based)')
    p.add_argument('--of', type=int, default=None, help='total number of shards')
    p.add_argument('--symbols-limit', type=int, default=None,
                   help='SMOKE ONLY: use only the first K symbols of this shard')
    p.add_argument('--merge', action='store_true', help='merge partials -> merged_stats.json')
    p.add_argument('--verdict', action='store_true', help='apply the frozen criteria, write results')
    p.add_argument('--smoke', action='store_true',
                   help='merge/verdict on deliberately partial data; downgrades coverage asserts '
                        'to warnings and stamps every page SMOKE')
    p.add_argument('--force', action='store_true', help='recompute a shard even if .done exists')
    p.add_argument('--work-dir', type=Path, default=DEFAULT_WORK_DIR,
                   help=f'partials + merged stats live here (default {DEFAULT_WORK_DIR})')
    p.add_argument('--prep-dir', type=Path, default=None,
                   help='read/build the shared prep artifacts here (default: --work-dir)')
    return p.parse_args()


def main():
    a = parse_args()
    work = a.work_dir
    if a.prepare:
        work.mkdir(parents=True, exist_ok=True)
        run_prepare(work)
        return
    if a.shard is not None:
        if a.of is None:
            sys.exit('--shard requires --of')
        if not (0 <= a.shard < a.of):
            sys.exit(f'--shard must be in [0, {a.of})')
        if a.prep_dir and a.prep_dir != work:
            _link_prep(a.prep_dir, work)
        run_shard(work, a.shard, a.of, symbols_limit=a.symbols_limit, force=a.force)
        return
    if a.merge:
        if a.of is None:
            sys.exit('--merge requires --of')
        if a.prep_dir and a.prep_dir != work:
            _link_prep(a.prep_dir, work)
        run_merge(work, a.of, smoke=a.smoke)
        return
    if a.verdict:
        run_verdict(work, smoke=a.smoke)
        return
    sys.exit('nothing to do -- pass one of --prepare / --shard I --of N / --merge --of N / --verdict')


def _link_prep(prep_dir, work):
    """Copy the (small) shared prep artifacts into the work dir so a smoke run
    in a scratch directory does not have to rebuild the whole panel."""
    import shutil
    work.mkdir(parents=True, exist_ok=True)
    src, dst = prep_paths(prep_dir), prep_paths(work)
    for k in ('meta', 'ew', 'universe', 'elig_universe', 'excluded'):
        if src[k].exists() and not dst[k].exists():
            shutil.copyfile(src[k], dst[k])


if __name__ == '__main__':
    main()
