"""Zoo-Silence Reversal -- TRUE OUT-OF-SAMPLE CONFIRMATION (pre-registered, FROZEN).

Frozen spec:
docs/superpowers/specs/2026-07-29-zoo-silence-reversal-design.md
Status: APPROVED & FROZEN (user, 2026-07-29). No deviations from the spec.

ORIGIN
------
kite/research/consensus_probe.py (2026-07-28, exploratory, TRAIN era only,
committed 26aa553) measured K-of-N agreement depth D across the zoo. Its one
positive-after-costs cell was D = 0 -- (symbol, day) cells where NONE of the 67
clean zoo strategies emitted a long signal -- with mean 10-day forward NET of
+0.3000% and mean prior-3d move -1.084%. Hypothesis under test: the zoo's
silence marks recent small losers that drift up, i.e. the strategy zoo is a
contrarian silence detector.

The probe never loaded a post-2023-12-31 bar (asserted at load). This script
tests the same cell on 2024-01-01 onward. That makes this a genuine
out-of-sample confirmation, not a re-run.

WHAT IS REUSED FROM THE PROBE (signal-path identity is the reviewer's check)
---------------------------------------------------------------------------
- Universe + loader: data/daily/*_day_2000d.csv, tz-naive normalised date
  index, keep symbols with > 300 bars.  Same 48 NIFTY names.
- Strategy zoo: kite.strategies.STRATEGY_REGISTRY, as-is, no subsetting by
  performance, no parameter changes.
- Signal path: BaseStrategy.generate_signals(df)['signal'], the probe's ~20x
  optimization over get_trade_signals() (bit-identical 'signal' column; no
  strategy in the package overrides get_trade_signals()).
- Leak flags: retest_all.py's leak_flags() verbatim, reading
  kite/reports/walkforward_audit.csv.
- Exclusions: the probe's 9 leak-suspects + 2 erroring strategies. The list is
  hard-coded below from the probe's own output and ASSERTED equal to what this
  run recomputes -- if the recomputed set differs by one name the script dies.
- Costs: zerodha_charges.calculate_charges(buy_v, sell_v, is_intraday=False)
  ['total'] -- the KEY, never sum(.values()). Rs 20,000 delivery position.
- Slippage: 0.0005 (0.05%/side), NIFTY tier.
- Warm-up: the probe's first-252-bars drop is retained as a floor (it is
  subsumed by the 2024-01-01 era wall, which sits ~860 bars in).

ERA WALLS (spec section "Data", enforced by asserts, not by convention)
----------------------------------------------------------------------
- Indicator warm-up MAY see train-era bars: strategies need lookback, so the
  price frames are loaded in full from 2020-07-14. This is explicitly
  permitted by the spec.
- NO CELL dated before 2024-01-01 enters any statistic. Asserted.
- Every forward window must END on or before the panel's last bar. Cells whose
  H=10 window is incomplete are DROPPED and COUNTED. Asserted.

HORIZON DEFINITION -- ONE SPEC AMBIGUITY, RESOLVED IN FAVOUR OF THE PROBE
------------------------------------------------------------------------
The spec says "exit at close of the 10th trading day after entry (H=10, THE
PROBE'S BEST HORIZON)". Those two clauses are not the same bar:
  - the probe's H=10   = close of signal_bar + 10  (entry is signal_bar + 1,
                         so the hold is 9 trading days from entry);
  - "10th day after entry" = close of signal_bar + 11.
The spec's Signal section is headed "frozen -- exactly the probe's cell, zero
new conditions", and H=10 is named as the probe's horizon. PRIMARY, and the
only verdict-bearing horizon, is therefore the PROBE-IDENTICAL one:
    entry = OPEN[signal_bar + 1], exit = CLOSE[signal_bar + 10].
The literal-wording variant (exit at CLOSE[signal_bar + 11]) is computed and
printed in a clearly fenced APPENDIX so the reviewer can adjudicate without a
17-minute re-run. It is NOT the verdict. H=5 (probe-identical,
CLOSE[signal_bar + 5]) is secondary information, also never verdict-bearing.

VERDICT (frozen, ALL THREE must hold; declared test count = 1)
--------------------------------------------------------------
C1  Validation D=0 mean NET at H=10 > 0.
C2  Cluster-robust t >= +2.0, clustered by ISO week of the ENTRY date.
    Formula copied verbatim from
    kite/research/announcement_drift_confirmation.py::cluster_robust_t
    (one-sample t on WEEKLY CLUSTER MEANS, not on raw cells).
C3  MOMENTUM/REVERSAL CONTROL. Quintiles of prior-3d return, breakpoints
    computed over ALL validation cells with D POOLED. Within each quintile:
    mean net H=10 of D=0 cells minus mean net H=10 of D>=1 cells. Passes iff
    the pooled cell-count-weighted difference > 0 AND the difference is
    positive in >= 3 of the 5 quintiles.
    If C1 and C2 pass but C3 fails, the recorded verdict is "short-term
    reversal re-discovered, zoo-silence decorative" -- a FAIL for this spec.

CAVEATS (stated before results, per spec)
-----------------------------------------
- Train-era exploration found this cell among ~15 bucket cells examined: a
  mild selection effect, which is exactly what this true-OOS design disciplines.
- The reversal family has graveyard cousins. C3 exists to stop a re-labelled
  short-term-reversal from passing as novel.
- 48 large-cap symbols only. Any pass generalizes to nothing wider without its
  own test.
- Overlapping 10-day windows within an ISO week share a cluster; residual
  overlap ACROSS weeks is a stated limitation and is not patched post hoc.
- On a pass: phase-2 spec (portfolio construction, incubator candidacy) needs
  separate approval. Never straight to live.

Usage:
    python -W ignore kite/research/zoo_silence_confirmation.py           # full study
    python -W ignore kite/research/zoo_silence_confirmation.py --smoke   # 2024-01 cells only
"""
import sys
import time
import traceback
from pathlib import Path

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / 'kite'))
from config import zerodha_charges            # noqa: E402
from kite.strategies import STRATEGY_REGISTRY  # noqa: E402

DATA_DIR = ROOT / 'data' / 'daily'
AUDIT_CSV = ROOT / 'kite' / 'reports' / 'walkforward_audit.csv'
SPEC = 'docs/superpowers/specs/2026-07-29-zoo-silence-reversal-design.md'
OUT_FILE = ROOT / 'kite' / 'research' / 'zoo_silence_results.txt'
OUT_FILE_SMOKE = ROOT / 'kite' / 'research' / 'zoo_silence_results_smoke.txt'

# --- era walls (frozen) ----------------------------------------------------
VALIDATION_START = pd.Timestamp('2024-01-01')   # no CELL before this enters any statistic
SMOKE_END = pd.Timestamp('2024-01-31')          # --smoke: one validation month of cells

# --- conventions inherited from consensus_probe.py (frozen) ----------------
WARMUP_BARS = 252            # probe convention, retained as a floor; era wall subsumes it
SLIPPAGE = 0.0005            # 0.05% per side, NIFTY tier
POSITION_RS = 20_000         # delivery; flat Rs 13.5 DP charge makes size matter
PRIOR_DAYS = 3               # prior-3d return, strictly backward-looking from the signal bar

# --- horizons, as EXIT OFFSETS FROM THE SIGNAL BAR (entry is always +1) ----
H10_PRIMARY = 10             # probe-identical H=10. VERDICT-BEARING.
H5_SECONDARY = 5             # probe-identical H=5.  information only.
H11_LITERAL = 11             # "10th trading day after entry". APPENDIX only.
EXIT_OFFSETS = (H5_SECONDARY, H10_PRIMARY, H11_LITERAL)
CELL_OFFSET = H10_PRIMARY    # a cell exists iff its PRIMARY window fits in the panel

# --- verdict thresholds (frozen) -------------------------------------------
C2_T_THRESH = 2.0
C3_N_QUINTILES = 5
C3_MIN_POSITIVE_QUINTILES = 3

# --- the probe's exclusion list, transcribed from consensus_probe_results.txt
# lines 37-54. Recomputed at runtime and ASSERTED equal to these.
PROBE_REGISTRY_N = 78
PROBE_EXCLUDED_LEAK = [
    'double_vwap_ha',
    'ema_21_55',
    'ema_scalping_1min',
    'fib_3wave',
    'london_breakout',
    'obv_strategy',
    'volume_oscillator',
    'vwap_scalping',
    'vwap_sd_bands',
]
PROBE_EXCLUDED_ERROR = [
    'pivot_point',
    'vwap_pullback',
]
PROBE_CLEAN_N = 67

_LINES = []


def log(s=''):
    print(s, flush=True)
    _LINES.append(str(s))


def flush_out(path):
    path.write_text('\n'.join(_LINES) + '\n', encoding='utf-8')


# ---------------------------------------------------------------------------
# Loader -- consensus_probe.load_data() with the TRAIN truncation REMOVED.
# The whole frame is loaded on purpose: indicator warm-up is allowed to see
# train-era bars (spec, section Data). The era wall is applied later, to CELLS.
# ---------------------------------------------------------------------------
def load_data():
    data = {}
    for f in sorted(DATA_DIR.glob('*_day_2000d.csv')):
        sym = f.name.split('_day_')[0]
        df = pd.read_csv(f, parse_dates=['datetime'])
        df['date'] = df.datetime.dt.tz_localize(None).dt.normalize()
        df = df.set_index('date')[['open', 'high', 'low', 'close', 'volume']]
        df = df[~df.index.duplicated(keep='last')].sort_index()
        if len(df) > 300:
            data[sym] = df
    return data


def leak_flags():
    """retest_all.leak_flags() verbatim, via consensus_probe.py: trade-count
    blowup between the vectorised and walkforward runs of the audit."""
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


# ---------------------------------------------------------------------------
# Cost model -- consensus_probe.net_return() verbatim.
# ---------------------------------------------------------------------------
def net_return(entry_open, exit_close):
    """Per-trade net return on invested value for one Rs 20k delivery round trip."""
    if not np.isfinite(entry_open) or not np.isfinite(exit_close) or entry_open <= 0:
        return np.nan
    buy_px = entry_open * (1 + SLIPPAGE)
    sell_px = exit_close * (1 - SLIPPAGE)
    qty = int(POSITION_RS / buy_px)
    if qty <= 0:
        return np.nan
    buy_v, sell_v = qty * buy_px, qty * sell_px
    fees = zerodha_charges.calculate_charges(buy_v, sell_v, is_intraday=False)['total']
    return (sell_v - buy_v - fees) / buy_v


# ---------------------------------------------------------------------------
# Signal generation over the whole zoo -- consensus_probe.build_signal_book().
# ---------------------------------------------------------------------------
def build_signal_book(data, flags):
    """Returns (long_book, short_counts, used, skipped_leak, errored)."""
    long_book, short_counts = {}, {}
    used, skipped_leak, errored = [], [], []
    names = sorted(STRATEGY_REGISTRY)
    for i, name in enumerate(names, 1):
        if flags.get(name) == 'LEAK-SUSPECT':
            skipped_leak.append(name)
            print(f'[{i}/{len(names)}] {name}: SKIPPED (leak-suspect)', flush=True)
            continue
        try:
            per_sym, n_long, n_short = {}, 0, 0
            for sym, df in data.items():
                s = STRATEGY_REGISTRY[name]()
                sig = s.generate_signals(df.copy())['signal'].to_numpy()
                sig = pd.to_numeric(pd.Series(sig), errors='coerce').fillna(0).to_numpy()
                assert len(sig) == len(df), f'{name}/{sym}: signal length {len(sig)} != {len(df)}'
                per_sym[sym] = (sig == 1)
                n_long += int((sig == 1).sum())
                n_short += int((sig == -1).sum())
            long_book[name] = per_sym
            short_counts[name] = n_short
            used.append(name)
            print(f'[{i}/{len(names)}] {name}: long={n_long} short={n_short} '
                  f'({flags.get(name, "?")})', flush=True)
        except Exception as e:
            errored.append((name, repr(e)[:110]))
            print(f'[{i}/{len(names)}] {name}: ERROR {repr(e)[:110]}', flush=True)
            traceback.print_exc()
    return long_book, short_counts, used, skipped_leak, errored


def assert_exclusion_list(used, skipped_leak, errored):
    """HARD GATE (spec: 'the identical exclusion list ... must match the probe's,
    byte for byte'). Any drift in the registry, the audit CSV, or a strategy's
    error behaviour kills the run instead of silently changing the 67-set."""
    err_names = sorted(n for n, _ in errored)
    assert len(STRATEGY_REGISTRY) == PROBE_REGISTRY_N, (
        f'REGISTRY DRIFT: {len(STRATEGY_REGISTRY)} strategies, probe saw {PROBE_REGISTRY_N}')
    assert sorted(skipped_leak) == PROBE_EXCLUDED_LEAK, (
        f'LEAK-EXCLUSION DRIFT: got {sorted(skipped_leak)}, probe had {PROBE_EXCLUDED_LEAK}')
    assert err_names == PROBE_EXCLUDED_ERROR, (
        f'ERROR-EXCLUSION DRIFT: got {err_names}, probe had {PROBE_EXCLUDED_ERROR}')
    assert len(used) == PROBE_CLEAN_N, (
        f'CLEAN-SET DRIFT: {len(used)} used, probe had {PROBE_CLEAN_N}')
    expect_used = sorted(set(STRATEGY_REGISTRY) - set(PROBE_EXCLUDED_LEAK) - set(PROBE_EXCLUDED_ERROR))
    assert sorted(used) == expect_used, 'CLEAN-SET DRIFT: used names differ from registry minus exclusions'
    return err_names


# ---------------------------------------------------------------------------
# Validation-era cell construction + drop accounting.
# ---------------------------------------------------------------------------
def build_sample(data, smoke):
    """Per symbol, the analysable VALIDATION cells and their forward returns.

    A cell is a (symbol, signal-bar) pair that satisfies ALL of:
      (a) signal-bar date >= 2024-01-01                    [era wall]
      (b) signal-bar date <= 2024-01-31                    [--smoke only]
      (c) position >= 252                                  [probe warm-up floor]
      (d) entry bar (pos+1) exists in the panel
      (e) the PRIMARY H=10 exit bar (pos+10) exists        [complete window]
    Cells failing (e) but passing (a)-(d) are DROPPED and COUNTED.
    """
    sample = {}
    acc = {'panel_bars': 0, 'pre_era': 0, 'post_smoke_end': 0, 'warmup': 0,
           'no_entry_bar': 0, 'incomplete_h10': 0, 'kept': 0}
    for sym, df in data.items():
        n = len(df)
        idx = df.index
        acc['panel_bars'] += n
        o = df.open.to_numpy(float)
        c = df.close.to_numpy(float)
        allpos = np.arange(n)

        pre = idx < VALIDATION_START
        acc['pre_era'] += int(pre.sum())
        cand = allpos[~pre]
        if smoke:
            too_late = idx[cand] > SMOKE_END
            acc['post_smoke_end'] += int(too_late.sum())
            cand = cand[~too_late]

        m = cand >= WARMUP_BARS
        acc['warmup'] += int((~m).sum())
        cand = cand[m]

        m = (cand + 1) <= (n - 1)
        acc['no_entry_bar'] += int((~m).sum())
        cand = cand[m]

        m = (cand + CELL_OFFSET) <= (n - 1)
        acc['incomplete_h10'] += int((~m).sum())
        pos = cand[m]

        acc['kept'] += len(pos)
        if len(pos) == 0:
            continue

        entry = o[pos + 1]
        gross, net = {}, {}
        for k in EXIT_OFFSETS:
            fits = (pos + k) <= (n - 1)
            ex = np.full(len(pos), np.nan)
            ex[fits] = c[pos[fits] + k]
            gross[k] = ex / entry - 1.0
            net[k] = np.array([net_return(a, b) for a, b in zip(entry, ex)])
        prior = np.full(len(pos), np.nan)
        ok = pos >= PRIOR_DAYS
        prior[ok] = c[pos[ok]] / c[pos[ok] - PRIOR_DAYS] - 1.0

        entry_dates = idx[pos + 1]
        iso = entry_dates.isocalendar()
        wk = np.array([f'{int(y)}-W{int(w):02d}' for y, w in zip(iso['year'], iso['week'])])

        sample[sym] = {'pos': pos, 'gross': gross, 'net': net, 'prior': prior,
                       'week': wk, 'sig_dates': idx[pos].to_numpy(),
                       'entry_dates': entry_dates.to_numpy(), 'n': n}
    return sample, acc


def assert_era_walls(data, sample, panel_last):
    """Hard asserts, independent of how build_sample filtered.
      (1) no CELL (signal bar) dated before 2024-01-01;
      (2) no forward window (entry bar or PRIMARY exit bar) past the panel's last bar.
    Returns (first_cell, last_cell, worst_exit)."""
    first = pd.Timestamp('2999-01-01')
    last = pd.Timestamp('1900-01-01')
    worst = pd.Timestamp('1900-01-01')
    for sym, sd in sample.items():
        idx = data[sym].index
        first = min(first, idx[sd['pos']].min())
        last = max(last, idx[sd['pos']].max())
        worst = max(worst, idx[sd['pos'] + 1].max())
        worst = max(worst, idx[sd['pos'] + CELL_OFFSET].max())
    assert first >= VALIDATION_START, (
        f'ERA-WALL VIOLATION: cell dated {first.date()} < {VALIDATION_START.date()}')
    assert worst <= panel_last, (
        f'PANEL-WALL VIOLATION: forward window ends {worst.date()} > panel last {panel_last.date()}')
    return first, last, worst


# ---------------------------------------------------------------------------
# Agreement depth D over the clean 67 set -- consensus_probe.depth_from_book().
# ---------------------------------------------------------------------------
def depth_from_book(long_book, sample):
    depth = {}
    for sym, sd in sample.items():
        d = np.zeros(sd['n'], dtype=np.int32)
        for per_sym in long_book.values():
            d += per_sym[sym].astype(np.int32)
        depth[sym] = d
    return depth


def collect(depth, sample):
    """Flatten every validation cell into flat arrays."""
    D, prior, week, sig_d, ent_d, sym_a = [], [], [], [], [], []
    gross = {k: [] for k in EXIT_OFFSETS}
    net = {k: [] for k in EXIT_OFFSETS}
    for sym, sd in sorted(sample.items()):
        pos = sd['pos']
        D.append(depth[sym][pos])
        prior.append(sd['prior'])
        week.append(sd['week'])
        sig_d.append(sd['sig_dates'])
        ent_d.append(sd['entry_dates'])
        sym_a.append(np.full(len(pos), sym))
        for k in EXIT_OFFSETS:
            gross[k].append(sd['gross'][k])
            net[k].append(sd['net'][k])
    cat = np.concatenate
    return {'D': cat(D), 'prior': cat(prior), 'week': cat(week),
            'sig_date': cat(sig_d), 'entry_date': cat(ent_d), 'sym': cat(sym_a),
            'gross': {k: cat(v) for k, v in gross.items()},
            'net': {k: cat(v) for k, v in net.items()}}


# ---------------------------------------------------------------------------
# Inference
# ---------------------------------------------------------------------------
def cluster_robust_t(values, clusters):
    """Cluster-robust (by ISO calendar week) pooled t-stat -- FROZEN FORMULA,
    copied verbatim from
    kite/research/announcement_drift_confirmation.py::cluster_robust_t.

    Rationale: overlapping 10-day forward windows opened in the same calendar
    week are correlated -- they are NOT N independent draws. Treating each ISO
    week as one cluster and testing on the CLUSTER MEANS (not the raw cells)
    is the frozen fix.

    Formula:
        cluster_mean_w = mean(value) over cells whose ENTRY date falls in
                         ISO week w
        pooled_mean    = mean(cluster_mean_w) across all n_weeks weeks
        pooled_se      = std(cluster_mean_w, ddof=1) / sqrt(n_weeks)
        t              = pooled_mean / pooled_se

    i.e. a plain one-sample t-test where the unit of observation is the WEEKLY
    CLUSTER MEAN, not the individual cell. Returns (t, n_weeks); t is NaN if
    fewer than 2 clusters or zero cluster-mean variance.
    """
    v = np.asarray(values, dtype=float)
    ok = np.isfinite(v)
    if ok.sum() == 0:
        return np.nan, 0
    df = pd.DataFrame({'v': v[ok], 'iso_week': np.asarray(clusters)[ok]})
    wk_means = df.groupby('iso_week')['v'].mean()
    n_weeks = len(wk_means)
    if n_weeks < 2:
        return np.nan, n_weeks
    pooled_mean = wk_means.mean()
    pooled_std = wk_means.std(ddof=1)
    if not np.isfinite(pooled_std) or pooled_std == 0:
        return np.nan, n_weeks
    t = pooled_mean / (pooled_std / np.sqrt(n_weeks))
    return t, n_weeks


def mean_finite(a):
    a = np.asarray(a, dtype=float)
    a = a[np.isfinite(a)]
    return (float(a.mean()), len(a)) if len(a) else (np.nan, 0)


def momentum_control(cells, offset):
    """C3. Quintiles of prior-3d return over ALL validation cells (D POOLED),
    then within-quintile mean net(D=0) - mean net(D>=1).

    Returns (rows, pooled_diff, n_positive, pooled_diff_d0w).
    'rows' is one dict per quintile. The declared pooled weight is the
    quintile's TOTAL cell count (n_D0 + n_Dge1); the D=0-count-weighted
    variant is reported alongside as information, never as the criterion.
    """
    D = cells['D']
    prior = cells['prior']
    net = cells['net'][offset]
    usable = np.isfinite(prior) & np.isfinite(net)
    qs = np.quantile(prior[usable], np.linspace(0, 1, C3_N_QUINTILES + 1))
    qs[0], qs[-1] = -np.inf, np.inf
    rows = []
    for i in range(C3_N_QUINTILES):
        lo, hi = qs[i], qs[i + 1]
        inq = usable & (prior >= lo) & (prior < hi if i < C3_N_QUINTILES - 1 else prior <= hi)
        m0 = inq & (D == 0)
        m1 = inq & (D >= 1)
        mean0, n0 = mean_finite(net[m0])
        mean1, n1 = mean_finite(net[m1])
        diff = mean0 - mean1 if (n0 and n1) else np.nan
        rows.append({'q': i + 1, 'lo': lo, 'hi': hi, 'n_all': int(inq.sum()),
                     'n0': n0, 'n1': n1, 'mean0': mean0, 'mean1': mean1, 'diff': diff})
    valid = [r for r in rows if np.isfinite(r['diff'])]
    w_all = sum(r['n_all'] for r in valid)
    w_d0 = sum(r['n0'] for r in valid)
    pooled = sum(r['diff'] * r['n_all'] for r in valid) / w_all if w_all else np.nan
    pooled_d0w = sum(r['diff'] * r['n0'] for r in valid) / w_d0 if w_d0 else np.nan
    n_pos = sum(1 for r in valid if r['diff'] > 0)
    return rows, pooled, n_pos, pooled_d0w


def verdict_block(cells, offset, tag, verdict_bearing):
    """Print C1/C2/C3 for one exit offset. Returns (c1, c2, c3, overall)."""
    D = cells['D']
    net = cells['net'][offset]
    m0 = (D == 0)
    n0_cells = int(m0.sum())
    mean0, n0 = mean_finite(net[m0])
    t0, n_weeks = cluster_robust_t(net[m0], cells['week'][m0])

    log('')
    log('=' * 100)
    log(f'{tag}')
    log('=' * 100)
    log(f'D=0 validation cells                : {n0_cells:,}  '
        f'(finite net: {n0:,}, NaN net: {n0_cells - n0:,})')
    if n0 == 0:
        log('  NO USABLE D=0 CELLS -- every criterion fails by construction.')
        return False, False, False, False
    log(f'D=0 mean NET                        : {mean0:+.4%}')
    log(f'D=0 median NET                      : {np.median(net[m0][np.isfinite(net[m0])]):+.4%}')
    log(f'D=0 mean GROSS                      : {mean_finite(cells["gross"][offset][m0])[0]:+.4%}')
    log(f'D=0 net win rate                    : '
        f'{100 * (net[m0][np.isfinite(net[m0])] > 0).mean():.2f}%')

    c1 = mean0 > 0
    log('')
    log(f'C1  mean net > 0                    : {mean0:+.4%}   ->  {"PASS" if c1 else "FAIL"}')

    c2 = bool(np.isfinite(t0) and t0 >= C2_T_THRESH)
    if np.isfinite(t0):
        log(f'C2  cluster-robust t >= +{C2_T_THRESH:.1f}         : t={t0:+.3f}  '
            f'(n_weeks={n_weeks}, n_cells={n0})  ->  {"PASS" if c2 else "FAIL"}')
    else:
        log(f'C2  cluster-robust t >= +{C2_T_THRESH:.1f}         : t=N/A  '
            f'(n_weeks={n_weeks}, n_cells={n0})  ->  FAIL')

    rows, pooled, n_pos, pooled_d0w = momentum_control(cells, offset)
    log('')
    log('C3  MOMENTUM/REVERSAL CONTROL -- quintiles of prior-3d return, breakpoints over ALL')
    log('    validation cells with D POOLED. Within-quintile mean net(D=0) minus mean net(D>=1).')
    log('    Breakpoint basis: validation cells with BOTH a finite prior-3d return and a finite')
    log('    net at this offset. Cells with no measurable outcome cannot enter a mean, so letting')
    log('    them move the breakpoints would only shift the bins without adding information.')
    log(f'{"Q":>3} {"prior-3d range":>24} {"n_all":>8} {"n_D0":>8} {"n_D>=1":>8} '
        f'{"net_D0%":>10} {"net_D>=1%":>11} {"diff pts":>10}')
    for r in rows:
        lo = '-inf' if not np.isfinite(r['lo']) else f'{100 * r["lo"]:+.2f}%'
        hi = '+inf' if not np.isfinite(r['hi']) else f'{100 * r["hi"]:+.2f}%'
        d0 = f'{100 * r["mean0"]:.4f}' if np.isfinite(r['mean0']) else '--'
        d1 = f'{100 * r["mean1"]:.4f}' if np.isfinite(r['mean1']) else '--'
        dd = f'{100 * r["diff"]:+.4f}' if np.isfinite(r['diff']) else '--'
        log(f'{r["q"]:>3} {lo + " .. " + hi:>24} {r["n_all"]:>8,} {r["n0"]:>8,} {r["n1"]:>8,} '
            f'{d0:>10} {d1:>11} {dd:>10}')
    log(f'    pooled diff (cell-count-weighted, DECLARED)  : '
        f'{100 * pooled:+.4f} pts' if np.isfinite(pooled) else
        '    pooled diff (cell-count-weighted, DECLARED)  : N/A')
    log(f'    [info only, not the criterion] D=0-count-weighted pooled diff: '
        f'{100 * pooled_d0w:+.4f} pts' if np.isfinite(pooled_d0w) else
        '    [info only] D=0-count-weighted pooled diff: N/A')
    log(f'    quintiles with positive diff                 : {n_pos} of {C3_N_QUINTILES} '
        f'(need >= {C3_MIN_POSITIVE_QUINTILES})')
    c3 = bool(np.isfinite(pooled) and pooled > 0 and n_pos >= C3_MIN_POSITIVE_QUINTILES)
    log(f'C3  pooled diff > 0 AND >= {C3_MIN_POSITIVE_QUINTILES}/5 positive : '
        f'{"PASS" if c3 else "FAIL"}')

    overall = c1 and c2 and c3
    log('')
    if verdict_bearing:
        log(f'>>> OVERALL VERDICT (C1 and C2 and C3): {"PASS" if overall else "FAIL"}')
        if c1 and c2 and not c3:
            log('>>> RECORDED AS: "short-term reversal re-discovered, zoo-silence decorative" '
                '(spec: a FAIL).')
    else:
        log(f'>>> (non-verdict-bearing) C1={"PASS" if c1 else "FAIL"} '
            f'C2={"PASS" if c2 else "FAIL"} C3={"PASS" if c3 else "FAIL"} '
            f'-> would be {"PASS" if overall else "FAIL"}')
    return c1, c2, c3, overall


# ---------------------------------------------------------------------------
def main():
    smoke = '--smoke' in sys.argv
    out_file = OUT_FILE_SMOKE if smoke else OUT_FILE
    t_start = time.time()

    # ---------------- frozen-rules header, printed BEFORE any number --------
    log('=' * 100)
    log('ZOO-SILENCE REVERSAL -- OUT-OF-SAMPLE CONFIRMATION')
    log('PRE-REGISTERED, FROZEN SPEC. Verdict rules below were fixed before this script ran.')
    log('=' * 100)
    log(f'Spec        : {SPEC}  (APPROVED & FROZEN 2026-07-29)')
    log('Origin      : kite/research/consensus_probe.py, 2026-07-28, EXPLORATORY, TRAIN ERA ONLY.')
    log('              Its one positive-after-costs cell was D=0 (no clean zoo strategy long),')
    log('              mean 10d forward NET +0.3000%, mean prior-3d move -1.084%.')
    log('Hypothesis  : zoo silence marks recent small losers that drift up -- the zoo as a')
    log('              contrarian silence detector.')
    log('Test count  : 1 declared test (the D=0 cell at H=10).')
    log('')
    log('--- FROZEN RULES ---')
    log('SIGNAL   : D(symbol, day) = number of the clean-67 zoo strategies emitting a LONG signal.')
    log('           EVENT = D == 0. No prior-return condition, no volatility condition, nothing')
    log('           the probe cell did not have. Conditioning now would be tuning.')
    log('ENTRY    : OPEN of the next trading day (signal_bar + 1).')
    log(f'EXIT     : CLOSE of signal_bar + {H10_PRIMARY}  = the probe\'s H={H10_PRIMARY}. PRIMARY, VERDICT-BEARING.')
    log(f'           CLOSE of signal_bar + {H5_SECONDARY}   = the probe\'s H={H5_SECONDARY}.  SECONDARY, information only.')
    log(f'           CLOSE of signal_bar + {H11_LITERAL}  = the spec\'s literal "10th trading day AFTER')
    log('           ENTRY". The spec calls H=10 "the probe\'s best horizon", and its Signal section')
    log('           is headed "exactly the probe\'s cell, zero new conditions", so the PROBE-IDENTICAL')
    log('           bar is primary. The literal variant is printed in a fenced APPENDIX so the')
    log('           reviewer can adjudicate the wording without a re-run. It is NOT the verdict.')
    log(f'COSTS    : Rs {POSITION_RS:,} delivery position; zerodha_charges.calculate_charges(...)[\'total\']')
    log('           -- the KEY, never sum(.values()), which double-counts. Identical to the probe.')
    log(f'SLIPPAGE : {SLIPPAGE * 100:.2f}% per side (NIFTY tier). Identical to the probe.')
    log('ZOO      : STRATEGY_REGISTRY as-is, no subsetting by performance, no re-fitting. The')
    log('           probe\'s 9 leak-suspects + 2 erroring strategies stay excluded; that list is')
    log('           hard-coded from the probe output and ASSERTED against a live recomputation.')
    log('SIGNAL   : BaseStrategy.generate_signals(df)[\'signal\'] -- the probe\'s optimization over')
    log('  PATH     get_trade_signals() (bit-identical signal column, ~20x faster).')
    log('')
    log('--- ERA WALLS (asserted in code, not assumed) ---')
    log(f'  WALL 1  Indicator warm-up MAY see pre-{VALIDATION_START.date()} bars. Price frames are loaded in')
    log('          FULL (from 2020-07-14) on purpose -- strategies need lookback. Spec-permitted.')
    log(f'  WALL 2  NO CELL dated before {VALIDATION_START.date()} enters ANY statistic. Hard assert.')
    log('  WALL 3  Every forward window must END on or before the panel\'s last bar. Cells whose')
    log(f'          H={H10_PRIMARY} window is incomplete are DROPPED and COUNTED below. Hard assert.')
    log(f'  WALL 4  Probe warm-up floor retained: first {WARMUP_BARS} bars per symbol are never cells')
    log('          (subsumed by WALL 2, which sits ~860 bars into the panel; reported anyway).')
    log('  CONTAMINATION: the probe truncated every frame to <= 2023-12-31 AT LOAD, asserted. The')
    log('  validation era below was never loaded by the probe and never loaded when this spec was')
    log('  written. This is a true out-of-sample confirmation.')
    log('')
    log('--- VERDICT (frozen, ALL THREE must hold) ---')
    log(f'  C1  Validation D=0 mean NET at H={H10_PRIMARY} > 0.')
    log(f'  C2  Cluster-robust t >= +{C2_T_THRESH:.1f}, clustered by ISO week of the ENTRY date. Formula')
    log('      copied verbatim from announcement_drift_confirmation.py::cluster_robust_t -- a')
    log('      one-sample t on WEEKLY CLUSTER MEANS, not on raw cells.')
    log('  C3  MOMENTUM/REVERSAL CONTROL. Quintiles of prior-3d return, breakpoints over ALL')
    log('      validation cells with D POOLED. Within each quintile, mean net(D=0) minus mean')
    log(f'      net(D>=1). Passes iff the pooled cell-count-weighted difference > 0 AND positive')
    log(f'      in >= {C3_MIN_POSITIVE_QUINTILES} of {C3_N_QUINTILES} quintiles.')
    log('      If C1 and C2 pass but C3 fails, the recorded verdict is "short-term reversal')
    log('      re-discovered, zoo-silence decorative" -- a FAIL for this spec.')
    log('')
    log('--- CAVEATS (stated before results) ---')
    log('  - Train-era exploration found this cell among ~15 bucket cells examined: a mild')
    log('    selection effect, which is exactly what this true-OOS design disciplines.')
    log('  - The reversal family has graveyard cousins. C3 exists to stop a re-labelled')
    log('    short-term-reversal passing as novel.')
    log('  - 48 large-cap NIFTY symbols only. Any pass generalizes to nothing wider without its')
    log('    own test.')
    log('  - Overlapping 10-day windows within an ISO week share a cluster; residual overlap')
    log('    ACROSS weeks is a stated limitation and is NOT patched post hoc.')
    log('  - On a pass: phase-2 spec (portfolio construction, incubator candidacy) needs separate')
    log('    approval. Never straight to live.')
    log('')

    if smoke:
        log('*' * 100)
        log('*** SMOKE MODE (--smoke): CELLS RESTRICTED TO SIGNAL DATES IN 2024-01 ONLY.          ***')
        log(f'*** ({VALIDATION_START.date()} .. {SMOKE_END.date()}). Roughly one month of cells; the ISO-week cluster    ***')
        log('*** count is ~5, so C2 is structurally underpowered and the C3 quintiles are thin.    ***')
        log('*** THIS IS NOT A VERDICT RUN. It is an end-to-end plumbing self-check.              ***')
        log('*' * 100)
        log('')

    # ---------------- data --------------------------------------------------
    data = load_data()
    all_dates = pd.DatetimeIndex(sorted(set().union(*[df.index for df in data.values()])))
    panel_first, panel_last = all_dates.min(), all_dates.max()
    log('--- data ---')
    log(f'universe loaded : {len(data)} symbols from {DATA_DIR}')
    log(f'panel bar range : {panel_first.date()} -> {panel_last.date()} ({len(all_dates)} trading days)')
    log(f'  train-era bars (< {VALIDATION_START.date()}) are LOADED for indicator warm-up only (WALL 1);')
    log('  they can never become cells (WALL 2).')
    flush_out(out_file)

    # ---------------- zoo ---------------------------------------------------
    flags = leak_flags()
    log('')
    log(f'leak flags read from {AUDIT_CSV.relative_to(ROOT)} using retest_all.leak_flags() verbatim')
    log(f'registry size: {len(STRATEGY_REGISTRY)} strategies')
    long_book, short_counts, used, skipped_leak, errored = build_signal_book(data, flags)
    err_names = assert_exclusion_list(used, skipped_leak, errored)

    log('')
    log('--- strategy inventory (ASSERTED identical to the probe\'s) ---')
    log(f'registered             : {len(STRATEGY_REGISTRY)}   (probe: {PROBE_REGISTRY_N})')
    log(f'EXCLUDED (leak-suspect): {len(skipped_leak)}   (probe: {len(PROBE_EXCLUDED_LEAK)})')
    for n in sorted(skipped_leak):
        log(f'    - {n}')
    log(f'EXCLUDED (raised)      : {len(errored)}   (probe: {len(PROBE_EXCLUDED_ERROR)})')
    for n, e in errored:
        log(f'    - {n}: {e}')
    log(f'USED in the clean set  : {len(used)}   (probe: {PROBE_CLEAN_N})')
    log('ASSERT OK: recomputed leak-exclusion list == the probe\'s, name for name.')
    log('ASSERT OK: recomputed error-exclusion list == the probe\'s, name for name.')
    log(f'ASSERT OK: clean set size == {PROBE_CLEAN_N}, and equals registry minus the exclusions.')
    log(f'           leak list  : {sorted(skipped_leak)}')
    log(f'           error list : {err_names}')

    counts = sorted(((n, sum(int(m.sum()) for m in long_book[n].values())) for n in used),
                    key=lambda x: -x[1])
    total_long = sum(c for _, c in counts)
    total_short = sum(short_counts[n] for n in used)
    log('')
    log(f'LONG signal-cells emitted by the clean 67 over the FULL loaded panel : {total_long:,}')
    log(f'SHORT signal-cells (counted only, never analysed)                    : {total_short:,}')
    flush_out(out_file)

    # ---------------- cells -------------------------------------------------
    sample, acc = build_sample(data, smoke)
    assert sample, 'no validation cells survived -- nothing to test'
    first_cell, last_cell, worst_exit = assert_era_walls(data, sample, panel_last)
    cells = collect(depth_from_book(long_book, sample), sample)

    n_cells = len(cells['D'])
    log('')
    log('--- CELL ACCOUNTING / DROP ACCOUNTING ---')
    log(f'(symbol, bar) pairs in the loaded panel                       : {acc["panel_bars"]:>9,}')
    log(f'  DROPPED, dated before {VALIDATION_START.date()} (WALL 2, warm-up only)      : {acc["pre_era"]:>9,}')
    if smoke:
        log(f'  DROPPED, dated after {SMOKE_END.date()} (SMOKE restriction only)    : {acc["post_smoke_end"]:>9,}')
    log(f'  DROPPED, inside the first {WARMUP_BARS} bars (WALL 4)              : {acc["warmup"]:>9,}')
    log(f'  DROPPED, no entry bar (signal bar is the panel\'s last)       : {acc["no_entry_bar"]:>9,}')
    log(f'  DROPPED, H={H10_PRIMARY} forward window INCOMPLETE (WALL 3)          : {acc["incomplete_h10"]:>9,}')
    log(f'  KEPT as validation cells                                    : {acc["kept"]:>9,}')
    assert acc['kept'] == n_cells, 'cell accounting mismatch'
    log('')
    log(f'validation cells analysed : {n_cells:,}  across {len(sample)} symbols')
    log(f'cell (signal-bar) dates   : {pd.Timestamp(first_cell).date()} -> {pd.Timestamp(last_cell).date()}')
    log(f'latest forward-window bar : {pd.Timestamp(worst_exit).date()}')
    log(f'ASSERT OK (WALL 2): first cell {pd.Timestamp(first_cell).date()} >= {VALIDATION_START.date()}')
    log(f'ASSERT OK (WALL 3): last exit  {pd.Timestamp(worst_exit).date()} <= panel last {panel_last.date()}')
    log('')
    log('non-finite accounting inside the kept cells (should be ~0; a NaN storm here invalidates):')
    for k in EXIT_OFFSETS:
        bad_g = int((~np.isfinite(cells['gross'][k])).sum())
        bad_n = int((~np.isfinite(cells['net'][k])).sum())
        tag = 'PRIMARY' if k == H10_PRIMARY else ('secondary' if k == H5_SECONDARY else 'appendix')
        log(f'  exit offset +{k:<3} ({tag:<9}): NaN gross {bad_g:>7,}  NaN net {bad_n:>7,}  '
            f'({100 * bad_n / n_cells:.3f}% of cells)')
    log(f'  prior-3d return          : NaN {int((~np.isfinite(cells["prior"])).sum()):>7,}')
    log(f'  distinct ISO entry weeks : {len(set(cells["week"])):>7,}')

    # Named, not hidden: net_return() returns NaN when int(POSITION_RS/buy_px) == 0,
    # i.e. a share that costs more than the whole Rs 20k position. That silently
    # removes the symbol from every NET statistic. This is the PROBE'S OWN cost
    # model unchanged -- the probe dropped the same names for the same reason --
    # but it is a real sample restriction and is spelled out here.
    bad_net = ~np.isfinite(cells['net'][H10_PRIMARY])
    if bad_net.any():
        log('')
        log(f'  per-symbol NaN net at the PRIMARY offset +{H10_PRIMARY} (cells present, but excluded from')
        log('  every NET mean). Cause is almost always price > position size -> qty 0:')
        for s in sorted(set(cells['sym'][bad_net])):
            ms = (cells['sym'] == s)
            allbad = (ms & bad_net).sum() == ms.sum()
            log(f'    {s:<14} {int((ms & bad_net).sum()):>6,} of {int(ms.sum()):>6,} cells NaN'
                f'{"   <-- ALL cells: symbol contributes nothing to any net statistic" if allbad else ""}')
        log(f'  symbols fully excluded from NET stats: '
            f'{sorted(s for s in set(cells["sym"][bad_net]) if (cells["sym"] == s).sum() == ((cells["sym"] == s) & bad_net).sum())}')
        log('  GROSS statistics are unaffected (they do not depend on quantity).')

    # ---------------- depth distribution -----------------------------------
    D = cells['D']
    log('')
    log('--- agreement-depth distribution over the VALIDATION cells (clean 67) ---')
    log(f'{"D":>6} {"cells":>10} {"% of all":>10}')
    for d in range(0, int(D.max()) + 1):
        k = int((D == d).sum())
        if k == 0 and d > 0:
            continue
        log(f'{d:>6} {k:>10,} {100 * k / n_cells:>9.2f}%')
    log(f'{"D>=1":>6} {int((D >= 1).sum()):>10,} {100 * (D >= 1).mean():>9.2f}%   '
        '(the C3 comparison group)')
    flush_out(out_file)

    # ---------------- PRIMARY verdict --------------------------------------
    c1, c2, c3, overall = verdict_block(
        cells, H10_PRIMARY,
        f'PRIMARY -- VERDICT-BEARING. H={H10_PRIMARY} (probe-identical: entry OPEN[sig+1], '
        f'exit CLOSE[sig+{H10_PRIMARY}])',
        verdict_bearing=True)
    flush_out(out_file)

    # ---------------- secondary H=5 (information only) ----------------------
    m0 = (D == 0)
    mean5, n5 = mean_finite(cells['net'][H5_SECONDARY][m0])
    t5, w5 = cluster_robust_t(cells['net'][H5_SECONDARY][m0], cells['week'][m0])
    log('')
    log('-' * 100)
    log(f'SECONDARY INFORMATION ONLY -- H={H5_SECONDARY} (exit CLOSE[sig+{H5_SECONDARY}]). '
        'NEVER VERDICT-BEARING (spec).')
    log('-' * 100)
    log(f'  D=0 mean NET (H={H5_SECONDARY}) : {mean5:+.4%}  (n={n5:,})' if n5 else
        f'  D=0 mean NET (H={H5_SECONDARY}) : N/A')
    log(f'  D=0 cluster-robust t   : {t5:+.3f} (n_weeks={w5})' if np.isfinite(t5) else
        f'  D=0 cluster-robust t   : N/A (n_weeks={w5})')
    log('  No PASS/FAIL is attached to this horizon and none may be inferred.')

    # ---------------- appendix: the literal wording -------------------------
    log('')
    log('#' * 100)
    log('# APPENDIX -- NOT THE VERDICT. Spec-wording disambiguation only.')
    log(f'# The spec sentence "exit at close of the 10th trading day after entry" reads literally as')
    log(f'# CLOSE[sig+{H11_LITERAL}], while the same sentence calls H=10 "the probe\'s best horizon", which is')
    log(f'# CLOSE[sig+{H10_PRIMARY}]. The primary block above uses the probe-identical bar, per the spec\'s')
    log('# "exactly the probe\'s cell" heading. The block below exists so that if the reviewer')
    log('# adjudicates the wording the other way, the numbers are already on record -- computed on')
    log(f'# the SAME cell set (defined by the H={H10_PRIMARY} completeness rule), so a few cells at each')
    log(f'# symbol\'s tail have a NaN +{H11_LITERAL} exit and drop out of these means.')
    log('#' * 100)
    verdict_block(
        cells, H11_LITERAL,
        f'APPENDIX -- NON-VERDICT. exit CLOSE[sig+{H11_LITERAL}] ("10th trading day after entry", literal)',
        verdict_bearing=False)

    # ---------------- close -------------------------------------------------
    log('')
    log('=' * 100)
    if smoke:
        log('*** SMOKE MODE -- the PASS/FAIL lines above are NOT the study verdict. One month of')
        log('*** cells cannot carry C2 (too few ISO-week clusters) and the C3 quintiles are thin.')
        log(f'*** The full study writes to {OUT_FILE.name} instead.')
    else:
        log(f'FINAL RECORDED VERDICT: {"PASS" if overall else "FAIL"}   '
            f'(C1 {"PASS" if c1 else "FAIL"} / C2 {"PASS" if c2 else "FAIL"} / C3 {"PASS" if c3 else "FAIL"})')
        log('Declared test count was 1. No threshold was moved, no alternate cut was shopped, and')
        log('the H=5 and appendix horizons carry no verdict weight.')
    log('=' * 100)
    log(f'runtime: {time.time() - t_start:.1f}s')
    flush_out(out_file)
    print(f'\nFull output saved to {out_file}')


if __name__ == '__main__':
    main()
