"""EXPLORATORY consensus-depth probe -- TRAIN-ERA ONLY -- NO VERDICT.

WHAT THIS IS
------------
A measurement script, not a test. It asks one descriptive question of the
project's existing strategy zoo, as-is, with no re-tuning:

    Does K-of-N signal agreement (how many registered strategies say "long"
    on the same symbol on the same day) select trades with higher PER-TRADE
    forward expectancy -- gross and net -- than shallow agreement?

It prints distributions and per-bucket averages. It does NOT emit PASS/FAIL,
does NOT declare an edge, and does NOT promote anything. If a future
pre-registered spec wants to test consensus, this file is the sighting shot
that tells that spec what the sample sizes and effect scales look like.

HOUSE RULE ENFORCED IN CODE
---------------------------
Validation data is never loaded. Every price frame is truncated to
<= 2023-12-31 immediately after read, BEFORE any indicator or signal is
computed, and a hard assert re-checks it. Because the last loaded bar is
<= 2023-12-31, every forward window necessarily ends <= 2023-12-31 too;
that is asserted separately and explicitly rather than assumed.

Note this cutoff (2023-12-31) is STRICTER than retest_all.py's TRAIN_END
(2024-06-30). The stricter one was mandated for this probe; the extra six
months of 2024 H1 train data is deliberately left on the table.

CONVENTIONS REUSED (not reinvented)
-----------------------------------
- Universe + loader: retest_all.py's load_data() -- data/daily/*_day_2000d.csv,
  tz-naive normalised date index, keep symbols with > 300 bars. Same 48 NIFTY
  names the zoo was built and re-tested on.
- Strategy zoo: kite.strategies.STRATEGY_REGISTRY, used as-is. No subsetting
  by performance, no parameter changes, no re-fitting.
- Signal path: BaseStrategy.generate_signals(df). retest_all.py calls
  get_trade_signals(), which is generate_signals() followed by a per-row
  Python loop that fills stop_loss/take_profit. This probe needs only the
  'signal' column, which the two produce identically (verified elementwise
  before this script was written), so it calls generate_signals() directly
  and skips the SL/TP loop -- a ~20x speedup with a bit-identical signal
  column. No strategy in the package overrides get_trade_signals().
- Leak flags: retest_all.py's leak_flags(), reading
  kite/reports/walkforward_audit.csv verbatim (same trade-count-blowup rule).
- Costs: config.zerodha_charges.calculate_charges(buy_v, sell_v,
  is_intraday=False)['total'] -- the 'total' KEY, never sum(.values()), which
  double-counts because 'total' is itself the sum of the other components.
- Slippage: 0.0005 (0.05%/side), honest_lab.py / retest_all.py's NIFTY-tier
  assumption.

ONE DEVIATION, STATED LOUDLY
----------------------------
retest_all.py LABELS leak-suspect strategies but still runs them. This probe
EXCLUDES them from the consensus pool, because a lookahead-contaminated
strategy fires on days it could not really have fired on, which would inflate
agreement depth D for spurious reasons and contaminate the one quantity being
measured. The excluded names are printed in full.

DECLARED BEFORE THE RUN (no search, no tuning, one pass)
--------------------------------------------------------
- Direction: long-only analysis. Short signals are counted and reported but
  never analysed.
- Warm-up: each symbol's first 252 bars are dropped from the analysis sample,
  identically for the real and shuffled arms. Reason: real signals cannot
  fire while indicators are still NaN, so a shuffle that could place signals
  there would face a null that the real arm never faced.
- Horizons: 1, 3, 5, 10 trading days. Entry at OPEN of the bar after the
  signal bar (house convention), exit at CLOSE of the bar H bars after the
  signal bar.
- Buckets: D=1, D=2, D=3-4, D=5-7, D=8+. D=0 is carried as a no-signal
  reference row, not as a bucket.
- Position: Rs 20,000 notional, delivery. The DP charge is a flat Rs 13.5,
  so position size genuinely matters and is fixed here rather than swept.
- Shuffle seed: 20260727, single shuffle, one pass.

Usage: python -W ignore kite/research/consensus_probe.py
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
from config import zerodha_charges
from kite.strategies import STRATEGY_REGISTRY

DATA_DIR = ROOT / 'data' / 'daily'
AUDIT_CSV = ROOT / 'kite' / 'reports' / 'walkforward_audit.csv'
OUT_FILE = ROOT / 'kite' / 'research' / 'consensus_probe_results.txt'

TRAIN_CUTOFF = pd.Timestamp('2023-12-31')   # HARD house rule. Nothing after this is loaded.
WARMUP_BARS = 252                           # declared, applied to real and shuffled arms alike
HORIZONS = (1, 3, 5, 10)
MAX_H = max(HORIZONS)
SLIPPAGE = 0.0005                           # 0.05%/side, NIFTY-tier
POSITION_RS = 20_000                        # delivery, flat-DP-charge sensitive
SHUFFLE_SEED = 20260727
BIG_MOVE = 0.02                             # |3-day move| threshold for the correlation diagnostic
PRIOR_DAYS = 3

# (label, lo, hi) inclusive on both ends; hi=None means open-ended
BUCKETS = [('D=1', 1, 1), ('D=2', 2, 2), ('D=3-4', 3, 4), ('D=5-7', 5, 7), ('D=8+', 8, None)]

_LINES = []


def log(s=''):
    print(s, flush=True)
    _LINES.append(str(s))


def flush_out():
    OUT_FILE.write_text('\n'.join(_LINES) + '\n', encoding='utf-8')


# ---------------------------------------------------------------------------
# Loader -- retest_all.load_data() with the train-era truncation bolted on
# BEFORE anything downstream can see a post-cutoff bar.
# ---------------------------------------------------------------------------
def load_data():
    data = {}
    for f in sorted(DATA_DIR.glob('*_day_2000d.csv')):
        sym = f.name.split('_day_')[0]
        df = pd.read_csv(f, parse_dates=['datetime'])
        df['date'] = df.datetime.dt.tz_localize(None).dt.normalize()
        df = df.set_index('date')[['open', 'high', 'low', 'close', 'volume']]
        df = df[~df.index.duplicated(keep='last')].sort_index()
        df = df[df.index <= TRAIN_CUTOFF]           # <-- validation data never enters memory
        if len(df) > 300:
            data[sym] = df
    # hard assert: no loaded bar may exceed the cutoff
    for sym, df in data.items():
        assert df.index.max() <= TRAIN_CUTOFF, f'TRAIN-ERA VIOLATION: {sym} has bar {df.index.max()}'
    return data


def leak_flags():
    """retest_all.leak_flags() verbatim: trade-count blowup between the
    vectorised and walkforward runs of the audit."""
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
# Cost model -- Rs 20k delivery position, 0.05%/side slippage, ['total'] key.
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
# Signal generation over the whole zoo.
# ---------------------------------------------------------------------------
def build_signal_book(data, flags):
    """Returns (long_book, short_counts, used, skipped_leak, errored).

    long_book: {strategy: {sym: bool ndarray aligned to data[sym].index}}
    """
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
                per_sym[sym] = (sig == 1)
                n_long += int((sig == 1).sum())
                n_short += int((sig == -1).sum())
            long_book[name] = per_sym
            short_counts[name] = n_short
            used.append(name)
            print(f'[{i}/{len(names)}] {name}: long={n_long} short={n_short} ({flags.get(name, "?")})',
                  flush=True)
        except Exception as e:
            errored.append((name, repr(e)[:110]))
            print(f'[{i}/{len(names)}] {name}: ERROR {repr(e)[:110]}', flush=True)
            traceback.print_exc()
    return long_book, short_counts, used, skipped_leak, errored


# ---------------------------------------------------------------------------
# Per-symbol analysis sample: warm-up dropped, forward window must fit.
# ---------------------------------------------------------------------------
def build_sample(data):
    """Returns {sym: dict} with the analysable positions and their pre-computed
    gross/net forward returns at every horizon, plus the prior-3-day move."""
    sample = {}
    for sym, df in data.items():
        n = len(df)
        o = df.open.to_numpy(float)
        c = df.close.to_numpy(float)
        # signal bar positions i: need i+1 (entry) .. i+MAX_H (longest exit) to exist
        pos = np.arange(WARMUP_BARS, n - MAX_H)
        if len(pos) == 0:
            continue
        entry = o[pos + 1]
        gross, net = {}, {}
        for h in HORIZONS:
            ex = c[pos + h]
            gross[h] = ex / entry - 1.0
            net[h] = np.array([net_return(a, b) for a, b in zip(entry, ex)])
        prior = np.full(len(pos), np.nan)
        ok = pos >= PRIOR_DAYS
        prior[ok] = c[pos[ok]] / c[pos[ok] - PRIOR_DAYS] - 1.0
        sample[sym] = {'pos': pos, 'gross': gross, 'net': net, 'prior': prior,
                       'dates': df.index.to_numpy(), 'n': n}
    return sample


def assert_train_era(data, sample):
    """Hard assert #2: EVERY forward window (entry bar and exit bar alike)
    ends on or before the cutoff. Independent of the loader's truncation."""
    worst = pd.Timestamp('1900-01-01')
    for sym, sd in sample.items():
        idx = data[sym].index
        for h in HORIZONS:
            worst = max(worst, idx[sd['pos'] + h].max())
        worst = max(worst, idx[sd['pos'] + 1].max())   # entry bar
    assert worst <= TRAIN_CUTOFF, f'TRAIN-ERA VIOLATION: forward window ends {worst} > {TRAIN_CUTOFF}'
    return worst


# ---------------------------------------------------------------------------
# Agreement depth
# ---------------------------------------------------------------------------
def depth_from_book(long_book, sample):
    """D(sym, position) = number of strategies signalling long there."""
    depth = {}
    for sym, sd in sample.items():
        d = np.zeros(sd['n'], dtype=np.int32)
        for per_sym in long_book.values():
            d += per_sym[sym].astype(np.int32)
        depth[sym] = d
    return depth


def shuffled_book(long_book, sample, seed):
    """Within-symbol reassignment of each strategy's long-signal dates.

    Preserves (a) each strategy's per-symbol signal COUNT exactly and (b) the
    symbol's date pool. Destroys only the cross-strategy alignment of dates,
    which is precisely the quantity D measures. Pool = the symbol's analysis
    positions (warm-up already dropped), so both arms draw from the same pool.
    """
    rng = np.random.default_rng(seed)
    out = {}
    for name, per_sym in long_book.items():
        new = {}
        for sym, mask in per_sym.items():
            arr = np.zeros(len(mask), dtype=bool)
            if sym in sample:
                pool = sample[sym]['pos']
                k = int(mask[pool].sum())          # count inside the analysable pool
                if k > 0:
                    k = min(k, len(pool))
                    arr[rng.choice(pool, size=k, replace=False)] = True
            new[sym] = arr
        out[name] = new
    return out


# ---------------------------------------------------------------------------
# Bucketing + reporting
# ---------------------------------------------------------------------------
def collect(depth, sample):
    """Flatten every analysable (symbol, position) cell into arrays."""
    D, prior = [], []
    gross = {h: [] for h in HORIZONS}
    net = {h: [] for h in HORIZONS}
    for sym, sd in sample.items():
        pos = sd['pos']
        D.append(depth[sym][pos])
        prior.append(sd['prior'])
        for h in HORIZONS:
            gross[h].append(sd['gross'][h])
            net[h].append(sd['net'][h])
    return (np.concatenate(D), np.concatenate(prior),
            {h: np.concatenate(v) for h, v in gross.items()},
            {h: np.concatenate(v) for h, v in net.items()})


def bucket_mask(D, lo, hi):
    return (D >= lo) if hi is None else ((D >= lo) & (D <= hi))


def depth_distribution(D, label):
    log('')
    log(f'--- distribution of agreement depth D ({label}) ---')
    log(f'total analysable (symbol, date) cells: {len(D)}')
    log('')
    log(f'{"D":>6} {"cells":>10} {"% of all":>10} {"% of D>=1":>11} {"cum % of D>=1":>15}')
    nz = int((D >= 1).sum())
    cum = 0
    for d in range(0, int(D.max()) + 1):
        k = int((D == d).sum())
        if d >= 1:
            cum += k
        if k == 0 and d > 0:
            continue
        pct_nz = 100 * k / nz if (nz and d >= 1) else float('nan')
        cum_pct = 100 * cum / nz if (nz and d >= 1) else float('nan')
        lab = f'{d}'
        if d == 0:
            log(f'{lab:>6} {k:>10} {100 * k / len(D):>9.2f}% {"--":>11} {"--":>15}')
        else:
            log(f'{lab:>6} {k:>10} {100 * k / len(D):>9.2f}% {pct_nz:>10.2f}% {cum_pct:>14.2f}%')
    log('')
    log('milestone tail counts (cells with at least this many strategies agreeing):')
    for k in (2, 3, 5, 8, 10, 15, 20):
        n = int((D >= k).sum())
        log(f'  D >= {k:<3}: {n:>8} cells  ({100 * n / len(D):6.3f}% of all cells,'
            f' {100 * n / nz if nz else float("nan"):6.3f}% of signalling cells)')


def bucket_table(D, gross, net, title):
    log('')
    log('=' * 108)
    log(title)
    log('entry: OPEN of the bar after the signal bar. exit: CLOSE of the bar H bars after the signal bar.')
    log(f'net = gross minus {SLIPPAGE * 100:.2f}%/side slippage and delivery charges on a Rs {POSITION_RS:,} position')
    log('=' * 108)
    log(f'{"bucket":>8} {"H":>4} {"N":>8} {"mean_gross%":>12} {"med_gross%":>11} '
        f'{"mean_net%":>10} {"med_net%":>9} {"win_gross%":>11} {"win_net%":>9}')
    rows = [('D=0 (ref)', 0, 0)] + BUCKETS
    store = {}
    for label, lo, hi in rows:
        m = (D == 0) if label.startswith('D=0') else bucket_mask(D, lo, hi)
        n_cells = int(m.sum())
        if n_cells == 0:
            log(f'{label:>8} {"--":>4} {0:>8}   (no cells in bucket)')
            continue
        for h in HORIZONS:
            g, nt = gross[h][m], net[h][m]
            gv, nv = g[np.isfinite(g)], nt[np.isfinite(nt)]
            if len(gv) == 0:
                continue
            log(f'{label:>8} {h:>4} {len(gv):>8} {100 * gv.mean():>12.4f} {100 * np.median(gv):>11.4f} '
                f'{100 * nv.mean():>10.4f} {100 * np.median(nv):>9.4f} '
                f'{100 * (gv > 0).mean():>11.2f} {100 * (nv > 0).mean():>9.2f}')
            store[(label, h)] = (float(gv.mean()), float(nv.mean()))
        log('-' * 108)

    # purely descriptive: order the buckets by mean net at each horizon. No claim
    # is attached to the ordering -- it is here so the shape is readable at a glance.
    log('')
    log('descriptive ordering -- buckets ranked by mean NET return at each horizon (best first).')
    log('This is a restatement of the table above, not an inference. Nothing is being selected by it.')
    labels = ['D=0 (ref)'] + [b[0] for b in BUCKETS]
    for h in HORIZONS:
        order = sorted((l for l in labels if (l, h) in store), key=lambda l: -store[(l, h)][1])
        log(f'  H={h:<3}: ' + '  >  '.join(f'{l} ({100 * store[(l, h)][1]:+.4f}%)' for l in order))
    log('')
    log('monotonicity check on the declared buckets only (D=0 reference excluded), stated descriptively:')
    for h in HORIZONS:
        seq = [store[(b[0], h)][1] for b in BUCKETS if (b[0], h) in store]
        if len(seq) < 2:
            continue
        rising = all(b >= a for a, b in zip(seq, seq[1:]))
        falling = all(b <= a for a, b in zip(seq, seq[1:]))
        shape = 'monotone increasing in D' if rising else (
            'monotone decreasing in D' if falling else 'non-monotone in D')
        log(f'  H={h:<3}: mean net across D=1 -> D=8+ is {shape}  '
            f'(spread {100 * (max(seq) - min(seq)):.4f} pts, D=8+ minus D=1 = '
            f'{100 * (seq[-1] - seq[0]):+.4f} pts)')


def correlation_diagnostic(D, prior):
    log('')
    log('=' * 108)
    log('CORRELATION DIAGNOSTIC -- is deep agreement just a big-recent-move detector?')
    log(f'measures: fraction of cells whose prior {PRIOR_DAYS}-day return had absolute value >= {BIG_MOVE * 100:.0f}%')
    log(f'prior move = close[signal bar] / close[signal bar - {PRIOR_DAYS}] - 1  (strictly backward-looking)')
    log('=' * 108)
    log(f'{"group":>14} {"N":>9} {"frac |3d move| >= 2%":>22} {"mean |3d move|%":>18} {"mean signed 3d move%":>22}')
    groups = [('D=0', D == 0), ('D=1', D == 1), ('D=2', D == 2), ('D=3-4', (D >= 3) & (D <= 4)),
              ('D=5-7', (D >= 5) & (D <= 7)), ('D=8+', D >= 8), ('D>=5', D >= 5)]
    stats = {}
    for label, m in groups:
        p = prior[m]
        p = p[np.isfinite(p)]
        if len(p) == 0:
            log(f'{label:>14} {0:>9}   (no cells)')
            continue
        frac = float((np.abs(p) >= BIG_MOVE).mean())
        stats[label] = frac
        log(f'{label:>14} {len(p):>9} {100 * frac:>21.2f}% {100 * np.abs(p).mean():>17.3f} '
            f'{100 * p.mean():>21.3f}')
    if 'D>=5' in stats and 'D=1' in stats:
        log('')
        log(f'OBSERVATION (no verdict): D>=5 cells are big-mover cells {100 * stats["D>=5"]:.2f}% of the time '
            f'vs {100 * stats["D=1"]:.2f}% for D=1 cells;')
        log(f'  ratio = {stats["D>=5"] / stats["D=1"]:.3f}x. A ratio near 1.0 would say deep agreement is NOT '
            f'merely restating recent volatility;')
        log('  a ratio well above 1.0 would say a large part of what D encodes is "something just moved".')


def shuffle_comparison(D_real, D_shuf, gross, net):
    log('')
    log('=' * 108)
    log(f'SHUFFLED CONTROL -- seed {SHUFFLE_SEED}, single shuffle, one pass')
    log('each strategy keeps its exact per-symbol long-signal COUNT; its signal DATES are redrawn')
    log('without replacement from that symbol\'s analysable date pool. Only cross-strategy date')
    log('alignment is destroyed. If real buckets do not separate from shuffled buckets, agreement')
    log('depth carries no information beyond how often the strategies fire.')
    log('=' * 108)
    log('')
    log('depth distribution, real vs shuffled:')
    log(f'{"D >=":>8} {"real cells":>12} {"shuffled cells":>16} {"real/shuf":>11}')
    for k in (1, 2, 3, 5, 8, 10, 15, 20):
        r, s = int((D_real >= k).sum()), int((D_shuf >= k).sum())
        ratio = (r / s) if s else float('inf')
        log(f'{k:>8} {r:>12} {s:>16} {ratio:>11.3f}')
    log('')
    log('per-bucket forward returns, real vs shuffled (mean %, all horizons):')
    log(f'{"bucket":>8} {"H":>4} {"N_real":>8} {"N_shuf":>8} {"gross_real":>11} {"gross_shuf":>11} '
        f'{"delta_g":>9} {"net_real":>9} {"net_shuf":>9} {"delta_n":>9}')
    for label, lo, hi in BUCKETS:
        mr, ms = bucket_mask(D_real, lo, hi), bucket_mask(D_shuf, lo, hi)
        for h in HORIZONS:
            gr, gs = gross[h][mr], gross[h][ms]
            nr, ns = net[h][mr], net[h][ms]
            gr, gs = gr[np.isfinite(gr)], gs[np.isfinite(gs)]
            nr, ns = nr[np.isfinite(nr)], ns[np.isfinite(ns)]
            if len(gr) == 0 or len(gs) == 0:
                log(f'{label:>8} {h:>4} {len(gr):>8} {len(gs):>8}   (one side empty)')
                continue
            thin = '   <-- shuffled N too small to compare' if len(gs) < 100 else ''
            log(f'{label:>8} {h:>4} {len(gr):>8} {len(gs):>8} {100 * gr.mean():>11.4f} '
                f'{100 * gs.mean():>11.4f} {100 * (gr.mean() - gs.mean()):>9.4f} '
                f'{100 * nr.mean():>9.4f} {100 * ns.mean():>9.4f} '
                f'{100 * (nr.mean() - ns.mean()):>9.4f}{thin}')
        log('-' * 108)
    log('')
    log('CAVEAT ON THE DEEP BUCKETS: the shuffle destroys co-firing by construction, so it produces very')
    log('few deep-agreement cells. Any bucket marked above as having too small a shuffled N has a')
    log('return delta dominated by noise in the shuffled arm and should not be read as a comparison.')
    log('The DEPTH-DISTRIBUTION half of this control (real vs shuffled cell counts) does not have that')
    log('problem -- counts are exact, and that is where the shuffle is informative.')


# ---------------------------------------------------------------------------
def main():
    t_start = time.time()
    log('=' * 108)
    log('EXPLORATORY -- TRAIN-ERA ONLY -- NO VERDICT')
    log('=' * 108)
    log('K-of-N SIGNAL AGREEMENT vs PER-TRADE FORWARD EXPECTANCY, measured over the existing strategy zoo.')
    log('')
    log('THIS IS A MEASUREMENT, NOT A TEST. No threshold is being evaluated, nothing passes or fails here,')
    log('and no strategy is promoted, retired, or ranked by anything printed below. The numbers exist so a')
    log('possible FUTURE pre-registered spec can be written with realistic sample sizes and effect scales')
    log('already known. Reading a trading decision out of this file would be reading it wrong.')
    log('')
    log('TRAIN-ERA GUARANTEE: every price frame is truncated to <= '
        f'{TRAIN_CUTOFF.date()} at load time, before any indicator or')
    log('signal is computed. Validation-era bars are never read into memory. Two hard asserts enforce it:')
    log('  (1) no loaded bar may exceed the cutoff; (2) no forward window (entry bar or exit bar) may end after it.')
    log('This cutoff is STRICTER than retest_all.py\'s TRAIN_END of 2024-06-30; the extra 2024 H1 train data')
    log('is deliberately unused.')
    log('')
    log('DECLARED BEFORE THE RUN -- no parameter search, no strategy subsetting by performance, no threshold')
    log('tuning, one pass:')
    log(f'  horizons          : {HORIZONS} trading days')
    log('  entry / exit      : entry at OPEN of signal_bar+1, exit at CLOSE of signal_bar+H')
    log(f'  buckets           : D=1, D=2, D=3-4, D=5-7, D=8+   (D=0 kept as a reference row only)')
    log(f'  warm-up dropped   : first {WARMUP_BARS} bars per symbol, applied to real AND shuffled arms alike')
    log(f'  slippage          : {SLIPPAGE * 100:.2f}% per side')
    log(f'  position          : Rs {POSITION_RS:,} delivery (flat Rs 13.5 DP charge makes size matter)')
    log('  costs             : zerodha_charges.calculate_charges(...)[\'total\']  -- the key, never sum(.values())')
    log(f'  shuffle seed      : {SHUFFLE_SEED}, one shuffle')
    log('  direction         : long-only analysis; short signals counted and reported but never analysed')
    log('')

    data = load_data()
    all_dates = pd.DatetimeIndex(sorted(set().union(*[df.index for df in data.values()])))
    log(f'universe loaded: {len(data)} symbols from {DATA_DIR}')
    log(f'loaded bar range: {all_dates.min().date()} -> {all_dates.max().date()} ({len(all_dates)} trading days)')
    log(f'ASSERT OK: max loaded bar {all_dates.max().date()} <= cutoff {TRAIN_CUTOFF.date()}')
    flush_out()

    flags = leak_flags()
    log('')
    log(f'leak flags read from {AUDIT_CSV.relative_to(ROOT)} using retest_all.leak_flags() verbatim')
    log(f'registry size: {len(STRATEGY_REGISTRY)} strategies')

    long_book, short_counts, used, skipped_leak, errored = build_signal_book(data, flags)

    log('')
    log('--- strategy inventory ---')
    log(f'registered            : {len(STRATEGY_REGISTRY)}')
    log(f'EXCLUDED (leak-suspect): {len(skipped_leak)}')
    for n in skipped_leak:
        log(f'    - {n}')
    log('  NOTE ON THIS DEVIATION: retest_all.py labels these but still runs them. This probe drops them,')
    log('  because a lookahead-contaminated strategy fires on days it could not really have fired on, which')
    log('  would inflate agreement depth D for spurious reasons -- D is the one quantity being measured here.')
    log(f'EXCLUDED (raised)     : {len(errored)}')
    for n, e in errored:
        log(f'    - {n}: {e}')
    log(f'USED in consensus pool: {len(used)}')
    log('  (strategies flagged "no-data" by the audit are KEPT -- that flag means the audit saw zero trades')
    log('   in both arms, which is a low firing rate, not evidence of leakage.)')

    counts = sorted(((n, sum(int(m.sum()) for m in long_book[n].values())) for n in used),
                    key=lambda x: -x[1])
    total_long = sum(c for _, c in counts)
    total_short = sum(short_counts[n] for n in used)
    log('')
    log(f'total LONG signal-cells emitted by the used pool : {total_long}')
    log(f'total SHORT signal-cells emitted by the used pool: {total_short}   (counted only; not analysed)')
    log('')
    log('most-firing strategies (long-cells, whole loaded train era, all 48 symbols):')
    for n, c in counts[:10]:
        log(f'    {n:26} {c:>7}  ({100 * c / total_long:5.2f}% of all long-cells)')
    log('least-firing strategies:')
    for n, c in counts[-10:]:
        log(f'    {n:26} {c:>7}  ({100 * c / total_long:5.2f}% of all long-cells)')
    flush_out()

    sample = build_sample(data)
    worst = assert_train_era(data, sample)
    n_cells = sum(len(sd['pos']) for sd in sample.values())
    first = min(data[s].index[sd['pos'][0]] for s, sd in sample.items())
    last = max(data[s].index[sd['pos'][-1]] for s, sd in sample.items())
    log('')
    log('--- analysis sample ---')
    log(f'signal bars analysed : {first.date()} -> {last.date()}')
    log(f'latest forward-window exit bar anywhere in the sample: {pd.Timestamp(worst).date()}')
    log(f'ASSERT OK: {pd.Timestamp(worst).date()} <= cutoff {TRAIN_CUTOFF.date()}  '
        '(no forward return peeks past the train era)')
    log(f'analysable (symbol, date) cells: {n_cells}')

    depth_real = depth_from_book(long_book, sample)
    D_real, prior, gross, net = collect(depth_real, sample)
    depth_distribution(D_real, 'REAL zoo')
    flush_out()

    bucket_table(D_real, gross, net,
                 'PER-TRADE FORWARD RETURNS BY AGREEMENT DEPTH -- REAL ZOO (exploratory, no verdict)')
    flush_out()

    correlation_diagnostic(D_real, prior)
    flush_out()

    shuf_book = shuffled_book(long_book, sample, SHUFFLE_SEED)
    depth_shuf = depth_from_book(shuf_book, sample)
    D_shuf, _, _, _ = collect(depth_shuf, sample)
    shuffle_comparison(D_real, D_shuf, gross, net)
    flush_out()

    log('')
    log('=' * 108)
    log('END OF EXPLORATORY OUTPUT -- NO VERDICT WAS RENDERED AND NONE SHOULD BE INFERRED')
    log('=' * 108)
    log('What this file is licensed to be used for: sizing a future pre-registered consensus spec (sample')
    log('sizes per bucket, plausible effect scales, whether deep agreement is even frequent enough to trade).')
    log('What it is NOT licensed for: concluding that consensus works. Everything above is in-sample on the')
    log('train era, over a zoo whose members were themselves selected and iterated on overlapping data, with')
    log('no multiple-comparison control and no out-of-sample confirmation. Any real claim needs a frozen spec')
    log('written BEFORE looking at validation data, and validation data has not been touched here.')
    log('')
    log(f'runtime: {time.time() - t_start:.1f}s')
    flush_out()
    print(f'\nFull output saved to {OUT_FILE}')


if __name__ == '__main__':
    main()
