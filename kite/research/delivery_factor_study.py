"""Delivery-Percentage Factor -- FROZEN pre-registered study.

Spec (frozen, read this first, do not deviate without a spec amendment):
    docs/superpowers/specs/2026-07-27-delivery-factor-design.md

NOTE on datalib.py: the build instructions said to read kite/research/
datalib.py first and reuse its loaders. That file does not exist in this
repo snapshot (checked 2026-07-28, no datalib.py anywhere under kite/). The
closest existing conventions in this codebase are kite/research/
universe_lab.py and kite/research/anomaly_batch2_corrected.py (liquidity
gate constants, EW daily-rebalanced benchmark via cross-sectional mean of
clipped returns, costs via zerodha_charges.calculate_charges(...)['total']
-- never sum(.values())). This script follows those conventions instead.

HYPOTHESIS: abnormally high delivery share (DELIV_PER) on an up day marks
multi-day-horizon accumulation and predicts positive near-term drift. The
mirror (abnormal delivery on a down day = distribution) is measured for
information only -- not tradeable (no retail cash-market shorting).

DATA: data/bhavcopy_full/sec_bhavdata_full_DDMMYYYY.csv (from
fetch_bhavcopy_full.py) + data/corp_actions_adjustments.csv (from
build_corp_actions.py). Universe is built PER-DATE from the files
themselves (survivorship-free by construction -- brief rule R15, never
today's constituent list).

SIGNAL (frozen): z_t = (DELIV_PER_t - mean_20d) / std_20d over the trailing
20 ELIGIBLE days (t-20..t-1, day t itself excluded), std > 0 required.
Accumulation = z_t >= +2.0 AND same-day adjusted close-to-close return > 0.

ELIGIBILITY (frozen gate + one documented interpretation choice): series
EQ, TURNOVER_LACS >= 200 (Rs 2 crore), adjusted close >= Rs 20, AND >= 20
prior eligible days for that symbol. INTERPRETATION CHOICE (flagged for
review): "eligible day" is defined here as (EQ & turnover>=200 & adj_close
>=20 & DELIV_PER not NaN) -- i.e. the DELIV_PER-not-NaN requirement is
folded into the base eligibility gate, not bolted on separately. This
makes "20 prior eligible days" exactly equal to "20 prior days with a
usable DELIV_PER value for the rolling mean/std window", which is the only
reading under which that window is actually computable, and it is also
the SAME universe used for the benchmark ("same eligible universe" in the
spec) -- so signal-eligibility and benchmark-membership are one flag, not
two. This is a judgment call the spec's one-line eligibility bullet does
not fully pin down; reviewer should sanity-check it (declared per the
spec's review-focal-point on "universe construction").

CORPORATE ACTIONS: OPEN/CLOSE are back-adjusted (multiply every price
strictly BEFORE an action's ex_date by that action's factor, compounding
across multiple actions for the same symbol -- see build_corp_actions.py's
docstring for the exact convention). HALT (script exits nonzero) if any
corporate-action row has factor=NaN (unparseable split/bonus text) AND
that symbol has panel rows dated before that action's ex_date -- i.e. the
ambiguous factor would silently corrupt a price we actually use.

CLIP GUARD (frozen): adjusted daily returns clipped to +/-25%. If more
than 0.1% of ELIGIBLE stock-days had a RAW (pre-clip) return outside that
band, HALT and print every offending (symbol, date, raw_return) row --
this is the honesty rule from brief R9 (stale-price/corrupt-print
contamination), not a tunable.

PORTFOLIO (primary, frozen): weekly, on the last trading day of each ISO
week, rank that day's accumulation signals by z; long the top 20 (fewer if
fewer qualify), equal weight; enter next trading day's OPEN; hold through
to the FOLLOWING rebalance's entry open (names that re-qualify are held,
not sold and rebought -- no cost on held slots); long-only, cash the rest.
LEAK WALL: signal computed using day t's own close/turnover/deliv data ->
first tradeable action is day t+1's open. Never same-day.

COSTS: real round trips only, via
    from kite.config import zerodha_charges
    zerodha_charges.calculate_charges(buy_value, sell_value,
                                       is_intraday=False)['total']
(NEVER sum(charges.values()) -- that dict already contains a 'total' key
equal to the sum of the other six components; summing everything
double-counts, the exact bug fixed across this repo on 2026-07-26/27).
Plus 0.2%/side slippage on both legs, applied to the fill price before
the charges call.

BENCHMARK: equal-weight, DAILY-rebalanced buy-and-hold of the same
eligible universe, on clip-guarded returns, FRICTIONLESS (no costs, no
slippage -- stated explicitly, this is a deliberately generous
counterfactual so the strategy has to clear a real bar).

SPLIT: train 2019-10 .. 2023-12, validation 2024-01 .. 2026-07 (or latest
data if earlier). Each period is run as an INDEPENDENT simulation with
capital reset at the period's own start (matches this repo's existing
train/val convention in anomaly_batch2_corrected.py / universe_lab.py --
avoids one period's compounding leaking into the other's CAGR).

VERDICT (frozen, PRIMARY CONFIG ONLY -- the two sensitivity variants below
carry no verdict weight per the spec's declared test count): pass requires
ALL THREE:
    1. Validation net CAGR >= universe B&H validation CAGR + 3pp.
    2. Train net CAGR >= universe B&H train CAGR (no train/val sign flip).
    3. Validation maxDD <= 1.25x universe B&H validation maxDD (compared
       by magnitude, abs(strategy) vs abs(benchmark)*1.25 -- same
       convention as Test C in anomaly_batch2_corrected.py).

DECLARED TEST COUNT (multiple-testing honesty, frozen): three runs total --
primary (this file's default), (a) --variant monthly, (b) --variant
decile. Nothing else. The distribution/short-side leg (--short-side) is
informational only, never a fourth verdict-bearing test.

  --variant decile INTERPRETATION CHOICE (flagged for review, spec gives
  only "top decile by z instead of top-20" with no further mechanics):
  implemented here as the SAME frozen signal (z>=2.0 AND same-day return
  >0) and SAME weekly rebalance, but the selection count each rebalance
  day scales with that day's eligible-universe size instead of being
  capped at a flat 20: n_take = max(1, round(0.10 * n_eligible_that_day)),
  capped at however many accumulation candidates actually exist. This
  keeps the frozen signal untouched (no scope creep) while making
  portfolio breadth proportional to the live universe, which is the
  natural reading of "decile" as a breadth rule rather than a redefinition
  of the signal itself (the research brief's original 1.9 framing -- pure
  cross-sectional decile sort with no absolute z threshold -- was
  considered and rejected here because it would silently drop the frozen
  z>=2.0/return-sign gate, which the one-line spec sentence does not
  license). Reviewer should confirm this reading before trusting decile
  numbers.

Usage:
    python kite/research/delivery_factor_study.py --smoke
    python kite/research/delivery_factor_study.py
    python kite/research/delivery_factor_study.py --variant monthly
    python kite/research/delivery_factor_study.py --variant decile
    python kite/research/delivery_factor_study.py --short-side
"""
import argparse
import re
import sys
from pathlib import Path

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))
from kite.config import zerodha_charges  # noqa: E402  (['total'] only -- see module docstring)

DATA_DIR = ROOT / 'data' / 'bhavcopy_full'
CORP_ACTIONS_PATH = ROOT / 'data' / 'corp_actions_adjustments.csv'
OUT_DIR = ROOT / 'kite' / 'research'

# ---------------------------------------------------------------------------
# Frozen constants
# ---------------------------------------------------------------------------
MIN_TURNOVER_LACS = 200.0     # Rs 2 crore
MIN_PRICE = 20.0              # Rs 20 adjusted close
Z_WINDOW = 20                 # trailing eligible days
Z_THRESHOLD = 2.0
TOP_N = 20
DECILE_FRAC = 0.10
CAPITAL = 100_000.0
SLIP = 0.002                  # 0.2%/side
CLIP = 0.25                   # +/-25% daily return clip
CLIP_HALT_FRAC = 0.001        # >0.1% of eligible stock-days -> HALT

TRAIN_START = pd.Timestamp('2019-10-01')
TRAIN_END = pd.Timestamp('2023-12-31')
VAL_START = pd.Timestamp('2024-01-01')
VAL_END = pd.Timestamp('2026-07-31')
SMOKE_START = pd.Timestamp('2024-01-01')
SMOKE_END = pd.Timestamp('2024-03-31')

FNAME_DATE_RE = re.compile(r'sec_bhavdata_full_(\d{2})(\d{2})(\d{4})\.csv$', re.IGNORECASE)

NEEDED_COLS = ['SYMBOL', 'SERIES', 'DATE1', 'OPEN_PRICE', 'CLOSE_PRICE',
               'TTL_TRD_QNTY', 'TURNOVER_LACS', 'DELIV_QTY', 'DELIV_PER']

_OUT_LINES = []


def log(msg=''):
    print(msg, flush=True)
    _OUT_LINES.append(str(msg))


def flush_out(path):
    path.write_text('\n'.join(_OUT_LINES) + '\n', encoding='utf-8')


# ---------------------------------------------------------------------------
# Loading -- strip whitespace from headers AND string values, SERIES=='EQ'
# only, DELIV_PER=='-' -> NaN. Trading day taken from the FILENAME (robust,
# doesn't depend on guessing NSE's DATE1 text format) rather than parsing
# DATE1; DATE1 is still read (per the spec's column list) purely so a
# mismatch would be visible if anyone inspects the raw files by hand.
# ---------------------------------------------------------------------------
def load_panel(data_dir=DATA_DIR):
    files = sorted(data_dir.glob('sec_bhavdata_full_*.csv'))
    frames = []
    n_skipped_files = 0
    for f in files:
        m = FNAME_DATE_RE.search(f.name)
        if not m:
            log(f'  WARN: {f.name} does not match expected filename pattern, skipping')
            n_skipped_files += 1
            continue
        file_date = pd.Timestamp(year=int(m.group(3)), month=int(m.group(2)), day=int(m.group(1)))
        try:
            df = pd.read_csv(f, dtype=str, encoding='utf-8')
        except Exception as e:
            log(f'  WARN: failed to read {f.name}: {type(e).__name__}: {e}, skipping')
            n_skipped_files += 1
            continue
        df.columns = df.columns.str.strip()
        missing = [c for c in NEEDED_COLS if c not in df.columns]
        if missing:
            log(f'  WARN: {f.name} missing columns {missing}, skipping file')
            n_skipped_files += 1
            continue
        df = df[NEEDED_COLS].copy()
        for c in NEEDED_COLS:
            df[c] = df[c].astype(str).str.strip()
        df = df[df['SERIES'] == 'EQ'].copy()
        if df.empty:
            continue
        df['date'] = file_date
        for c in ['OPEN_PRICE', 'CLOSE_PRICE', 'TTL_TRD_QNTY', 'TURNOVER_LACS', 'DELIV_QTY']:
            df[c] = pd.to_numeric(df[c], errors='coerce')
        # DELIV_PER=='-' -> NaN (explicit, per spec wording; to_numeric with
        # errors='coerce' would already turn '-' into NaN, this just makes
        # the rule visible in the code).
        deliv_per_raw = df['DELIV_PER'].replace('-', np.nan)
        df['DELIV_PER'] = pd.to_numeric(deliv_per_raw, errors='coerce')
        frames.append(df.rename(columns={
            'SYMBOL': 'symbol', 'OPEN_PRICE': 'open', 'CLOSE_PRICE': 'close',
            'TTL_TRD_QNTY': 'ttl_qty', 'TURNOVER_LACS': 'turnover_lacs',
            'DELIV_QTY': 'deliv_qty', 'DELIV_PER': 'deliv_per',
        })[['symbol', 'date', 'open', 'close', 'ttl_qty', 'turnover_lacs',
            'deliv_qty', 'deliv_per']])
    if not frames:
        sys.exit(f'HALTED: no usable files found under {data_dir}. Run fetch_bhavcopy_full.py first.')
    panel = pd.concat(frames, ignore_index=True)
    panel = panel.drop_duplicates(subset=['symbol', 'date'], keep='last')
    panel = panel.sort_values(['symbol', 'date']).reset_index(drop=True)
    log(f'Loaded {len(files)} files ({n_skipped_files} skipped), '
        f'{len(panel)} EQ stock-day rows, {panel.symbol.nunique()} symbols, '
        f'{panel.date.min().date()} -> {panel.date.max().date()}')
    return panel


# ---------------------------------------------------------------------------
# Corporate actions: HALT check, then back-adjustment of OPEN/CLOSE.
# ---------------------------------------------------------------------------
def load_corp_actions(path=CORP_ACTIONS_PATH):
    if not path.exists():
        sys.exit(f'HALTED: {path} not found. Run build_corp_actions.py first.')
    df = pd.read_csv(path)
    df['ex_date'] = pd.to_datetime(df['ex_date'])
    return df


def halt_on_unresolved_nan_factors(panel, corp_actions):
    """HALT if any NaN-factor corp-action row's symbol has panel data dated
    before that action's ex_date (i.e. the missing factor would silently
    corrupt a price the study actually uses)."""
    nan_rows = corp_actions[corp_actions['factor'].isna()]
    if nan_rows.empty:
        return
    panel_symbols = set(panel['symbol'].unique())
    offenders = []
    for _, row in nan_rows.iterrows():
        sym, ex = row['symbol'], row['ex_date']
        if sym not in panel_symbols:
            continue
        sym_dates = panel.loc[panel['symbol'] == sym, 'date']
        if (sym_dates < ex).any():
            offenders.append((sym, ex.date().isoformat(), row.get('subject', '')))
    if offenders:
        log('')
        log('HALT: unresolved (factor=NaN) corporate action(s) touch dates in the loaded panel:')
        for sym, ex, subj in offenders:
            log(f'  {sym}  ex_date={ex}  subject={subj!r}')
        sys.exit(f'HALTED: {len(offenders)} unresolved corp-action factor(s) affect the loaded panel. '
                 f'Fix build_corp_actions.py parsing for these symbols/subjects before re-running.')


def apply_corp_action_adjustments(panel, corp_actions):
    """Multiply OPEN/CLOSE by the cumulative product of all factors whose
    ex_date is STRICTLY AFTER the row's date (standard back-adjustment,
    compounds multiple actions). NaN-factor rows are excluded here (already
    fatal via halt_on_unresolved_nan_factors if they'd matter)."""
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
        d = dates_arr[idxs]
        j = np.searchsorted(ex_dates, d, side='right')  # count of ex_dates <= d
        mult[idxs] = suffix[j]

    panel['adj_mult'] = mult
    panel['adj_open'] = panel['open'] * panel['adj_mult']
    panel['adj_close'] = panel['close'] * panel['adj_mult']
    n_adjusted = int((mult != 1.0).sum())
    log(f'Corporate-action adjustment applied: {n_adjusted} stock-day rows scaled '
        f'(factor != 1.0), {valid["symbol"].nunique()} symbols with >=1 valid action.')
    return panel


# ---------------------------------------------------------------------------
# Returns, clip guard (HALT rule), eligibility, z-score, signals.
# ---------------------------------------------------------------------------
def compute_returns_and_clip_guard(panel):
    panel = panel.sort_values(['symbol', 'date']).reset_index(drop=True)
    panel['prev_adj_close'] = panel.groupby('symbol')['adj_close'].shift(1)
    panel['raw_ret'] = panel['adj_close'] / panel['prev_adj_close'] - 1
    panel['ret'] = panel['raw_ret'].clip(-CLIP, CLIP)
    return panel


def compute_eligibility_and_signal(panel):
    panel['gate'] = (panel['turnover_lacs'] >= MIN_TURNOVER_LACS) & (panel['adj_close'] >= MIN_PRICE)
    panel['deliv_valid'] = panel['deliv_per'].notna()
    panel['gate_ok'] = panel['gate'] & panel['deliv_valid']

    elig = panel.loc[panel['gate_ok'], ['symbol', 'date', 'deliv_per']].sort_values(['symbol', 'date'])
    grp = elig.groupby('symbol')['deliv_per']
    elig['roll_mean'] = grp.transform(lambda s: s.shift(1).rolling(Z_WINDOW, min_periods=Z_WINDOW).mean())
    elig['roll_std'] = grp.transform(lambda s: s.shift(1).rolling(Z_WINDOW, min_periods=Z_WINDOW).std())
    elig['z'] = (elig['deliv_per'] - elig['roll_mean']) / elig['roll_std']
    elig.loc[~(elig['roll_std'] > 0), 'z'] = np.nan  # std > 0 required

    panel = panel.merge(elig[['symbol', 'date', 'z']], on=['symbol', 'date'], how='left')
    panel['eligible'] = panel['gate_ok'] & panel['z'].notna()
    panel['accumulation'] = panel['eligible'] & (panel['z'] >= Z_THRESHOLD) & (panel['ret'] > 0)
    panel['distribution'] = panel['eligible'] & (panel['z'] >= Z_THRESHOLD) & (panel['ret'] < 0)
    return panel


def halt_on_clip_guard(panel):
    """Clip guard (frozen): among ELIGIBLE stock-days with a defined raw
    return, if more than CLIP_HALT_FRAC (0.1%) had |raw_return| > CLIP
    (25%), HALT and print every offender."""
    sub = panel.loc[panel['eligible'] & panel['raw_ret'].notna(), ['symbol', 'date', 'raw_ret']]
    n_valid = len(sub)
    offenders = sub[sub['raw_ret'].abs() > CLIP]
    n_clipped = len(offenders)
    frac = (n_clipped / n_valid) if n_valid else 0.0
    log('')
    log(f'Clip guard: {n_clipped}/{n_valid} eligible stock-days ({frac * 100:.4f}%) had '
        f'|raw return| > {CLIP * 100:.0f}% (frozen HALT bar: {CLIP_HALT_FRAC * 100:.2f}%).')
    if frac > CLIP_HALT_FRAC:
        log('')
        log('HALT: clip guard fired on more than 0.1% of eligible stock-days. Offenders:')
        for _, row in offenders.sort_values('date').iterrows():
            log(f'  {row.symbol}  {row.date.date()}  raw_return={row.raw_ret * 100:+.1f}%')
        sys.exit(f'HALTED: clip guard exceeded frozen bar ({frac * 100:.4f}% > {CLIP_HALT_FRAC * 100:.2f}%). '
                 f'Inspect the {n_clipped} offenders above for bad prints / stale-price / corp-action gaps '
                 f'before re-running (brief rule R9).')


def prepare_panel():
    panel = load_panel()
    corp_actions = load_corp_actions()
    halt_on_unresolved_nan_factors(panel, corp_actions)
    panel = apply_corp_action_adjustments(panel, corp_actions)
    panel = compute_returns_and_clip_guard(panel)
    panel = compute_eligibility_and_signal(panel)
    halt_on_clip_guard(panel)
    n_elig = int(panel['eligible'].sum())
    n_accum = int(panel['accumulation'].sum())
    n_dist = int(panel['distribution'].sum())
    log(f'Eligible stock-days: {n_elig} ({100 * n_elig / max(len(panel), 1):.2f}% of EQ stock-days). '
        f'Accumulation signals: {n_accum}. Distribution signals (info only): {n_dist}.')
    return panel


# ---------------------------------------------------------------------------
# Calendar / rebalance-date construction.
# ---------------------------------------------------------------------------
def build_calendar(panel):
    return pd.DatetimeIndex(sorted(panel['date'].unique()))


def weekly_rebalance_dates(all_dates):
    if len(all_dates) == 0:
        return pd.DatetimeIndex([])
    iso = all_dates.isocalendar()
    key = iso['year'].astype(str) + '-W' + iso['week'].astype(str).str.zfill(2)
    df_cal = pd.DataFrame({'date': all_dates, 'key': key.values})
    last_per_week = df_cal.groupby('key')['date'].max()
    return pd.DatetimeIndex(sorted(last_per_week.values))


def monthly_rebalance_dates(all_dates):
    if len(all_dates) == 0:
        return pd.DatetimeIndex([])
    key = all_dates.year.astype(str) + '-' + all_dates.month.astype(str).str.zfill(2)
    df_cal = pd.DataFrame({'date': all_dates, 'key': key})
    last_per_month = df_cal.groupby('key')['date'].max()
    return pd.DatetimeIndex(sorted(last_per_month.values))


# ---------------------------------------------------------------------------
# Precomputed lookup structures shared across period simulations.
# ---------------------------------------------------------------------------
class Precomputed:
    def __init__(self, panel):
        self.open_wide = panel.pivot(index='date', columns='symbol', values='adj_open')
        self.close_wide = panel.pivot(index='date', columns='symbol', values='adj_close')
        accum = panel.loc[panel['accumulation'], ['date', 'symbol', 'z']]
        self.accum_by_date = {
            d: g.sort_values('z', ascending=False)[['symbol', 'z']]
            for d, g in accum.groupby('date')
        }
        dist = panel.loc[panel['distribution'], ['date', 'symbol', 'z']]
        self.dist_by_date = {
            d: g.sort_values('z', ascending=False)[['symbol', 'z']]
            for d, g in dist.groupby('date')
        }
        self.eligible_count_by_date = panel.loc[panel['eligible']].groupby('date').size()
        panel = panel.copy()
        panel['ret_elig'] = panel['ret'].where(panel['eligible'])
        self.elig_ret_wide = panel.pivot(index='date', columns='symbol', values='ret_elig')
        self.bh_ret_series = self.elig_ret_wide.mean(axis=1, skipna=True)


# ---------------------------------------------------------------------------
# Portfolio simulation for one period (fresh capital at period start).
# ---------------------------------------------------------------------------
def simulate_period(pre, all_dates, start, end, freq='weekly', decile=False):
    dates_in_period = all_dates[(all_dates >= start) & (all_dates <= end)]
    if len(dates_in_period) < 2:
        return None

    reb_dates = (weekly_rebalance_dates(dates_in_period) if freq == 'weekly'
                 else monthly_rebalance_dates(dates_in_period))
    date_list = list(dates_in_period)
    date_pos = {d: i for i, d in enumerate(date_list)}

    # Build entry-day -> target-symbol-list events (LEAK WALL: target chosen
    # using day d's own signals, executed at day d+1's open).
    events_by_date = {}
    n_reb_no_next_day = 0
    for d in sorted(reb_dates):
        i = date_pos.get(d)
        if i is None or i + 1 >= len(date_list):
            n_reb_no_next_day += 1
            continue
        entry_date = date_list[i + 1]
        cands = pre.accum_by_date.get(d)
        if cands is None or cands.empty:
            target_syms = []
        elif decile:
            n_elig = int(pre.eligible_count_by_date.get(d, 0))
            target_count = max(1, round(DECILE_FRAC * n_elig)) if n_elig else 0
            n_take = min(len(cands), target_count) if target_count else 0
            target_syms = cands['symbol'].tolist()[:n_take]
        else:
            target_syms = cands['symbol'].tolist()[:min(len(cands), TOP_N)]
        events_by_date.setdefault(entry_date, target_syms)

    positions = {}
    cash = CAPITAL
    equity = []
    trades = []
    names_held_per_period = []
    n_fill_misses = 0

    def mval(t):
        total = 0.0
        for s, p in positions.items():
            c = pre.close_wide.at[t, s] if (t in pre.close_wide.index and s in pre.close_wide.columns) else np.nan
            px = c if pd.notna(c) else p['entry']
            total += p['qty'] * px
        return total

    for t in date_list:
        if t in events_by_date:
            target_syms = events_by_date[t]
            target_set = set(target_syms)
            exits = [s for s in list(positions) if s not in target_set]
            for s in exits:
                p = positions[s]
                o = pre.open_wide.at[t, s] if (t in pre.open_wide.index and s in pre.open_wide.columns) else np.nan
                if pd.isna(o):
                    n_fill_misses += 1
                    continue  # can't fill; keep holding, try again next event
                del positions[s]
                exit_px = o * (1 - SLIP)
                sell_v = p['qty'] * exit_px
                buy_v = p['qty'] * p['entry']
                fees = zerodha_charges.calculate_charges(buy_v, sell_v, is_intraday=False)['total']
                cash += sell_v - fees
                trades.append(sell_v - buy_v - fees)

            new_entries = [s for s in target_syms if s not in positions]
            n_target = len(target_syms)
            if n_target > 0 and new_entries:
                cur_mval = mval(t)
                slot = (cash + cur_mval) / n_target
                for s in new_entries:
                    o = pre.open_wide.at[t, s] if (t in pre.open_wide.index and s in pre.open_wide.columns) else np.nan
                    if pd.isna(o):
                        n_fill_misses += 1
                        continue
                    entry_px = o * (1 + SLIP)
                    qty = int(min(cash, slot) / entry_px)
                    if qty <= 0:
                        continue
                    cash -= qty * entry_px
                    positions[s] = {'qty': qty, 'entry': entry_px}
            if target_syms:
                names_held_per_period.append(len(positions))

        equity.append((t, cash + mval(t)))

    eq = pd.Series(dict(equity)).sort_index()
    stats = curve_stats(eq)
    stats['trades'] = len(trades)
    stats['avg_names_held'] = float(np.mean(names_held_per_period)) if names_held_per_period else 0.0
    stats['n_rebalances'] = len(reb_dates)
    stats['n_rebalances_no_next_day'] = n_reb_no_next_day
    stats['n_fill_misses'] = n_fill_misses
    stats['equity'] = eq
    return stats


def curve_stats(equity):
    equity = equity.dropna()
    if len(equity) < 2 or equity.iloc[0] <= 0:
        return {'cagr': float('nan'), 'maxdd': float('nan'), 'n_days': len(equity)}
    yrs = len(equity) / 252.0
    cagr = ((equity.iloc[-1] / equity.iloc[0]) ** (1 / yrs) - 1) * 100 if yrs > 0 else float('nan')
    dd = ((equity / equity.cummax()) - 1).min() * 100
    return {'cagr': float(cagr), 'maxdd': float(dd), 'n_days': len(equity)}


def benchmark_period(pre, all_dates, start, end):
    dates_in_period = all_dates[(all_dates >= start) & (all_dates <= end)]
    if len(dates_in_period) < 2:
        return None
    ret = pre.bh_ret_series.reindex(dates_in_period).fillna(0.0)
    eq = (1 + ret).cumprod() * CAPITAL
    return curve_stats(eq)


# ---------------------------------------------------------------------------
# Reporting
# ---------------------------------------------------------------------------
def print_period_row(label, stats):
    if stats is None:
        log(f'  {label:24}: no data in this window')
        return
    log(f'  {label:24}: CAGR {stats["cagr"]:+7.2f}%   maxDD {stats["maxdd"]:+7.2f}%   '
        f'days {stats["n_days"]:5}'
        + (f'   trades {stats["trades"]:4}   avg names held {stats["avg_names_held"]:5.1f}'
           f'   rebalances {stats["n_rebalances"]} (no-next-day {stats["n_rebalances_no_next_day"]}, '
           f'fill-misses {stats["n_fill_misses"]})' if 'trades' in stats else ''))


def print_verdict(variant_label, verdict_weight, train_strat, val_strat, train_bh, val_bh):
    log('')
    log(f'Verdict ({variant_label}):')
    if not verdict_weight:
        log('  SENSITIVITY VARIANT -- NO VERDICT WEIGHT per the frozen spec\'s declared test count.')
        log('  (Reported for reference only; PASS/FAIL is only computed for the primary weekly/top-20 config.)')
        return None
    if train_strat is None or val_strat is None or train_bh is None or val_bh is None:
        log('  Cannot compute verdict -- missing train or validation data.')
        return None
    c1 = val_strat['cagr'] >= val_bh['cagr'] + 3.0
    log(f'  1. Validation net CAGR >= B&H val CAGR + 3pp : {val_strat["cagr"]:.2f} >= '
        f'{val_bh["cagr"] + 3.0:.2f}  -> {"PASS" if c1 else "FAIL"}')
    c2 = train_strat['cagr'] >= train_bh['cagr']
    log(f'  2. Train net CAGR >= B&H train CAGR (no sign flip): {train_strat["cagr"]:.2f} >= '
        f'{train_bh["cagr"]:.2f}  -> {"PASS" if c2 else "FAIL"}')
    c3 = abs(val_strat['maxdd']) <= 1.25 * abs(val_bh['maxdd'])
    log(f'  3. Validation maxDD <= 1.25x B&H val maxDD    : |{val_strat["maxdd"]:.2f}| <= '
        f'{1.25 * abs(val_bh["maxdd"]):.2f}  -> {"PASS" if c3 else "FAIL"}')
    overall = c1 and c2 and c3
    log(f'  OVERALL: {"PASS -> earns an incubator discussion (not a deployment)" if overall else "FAIL -> dead, recorded, no re-tuning"}')
    return overall


def short_side_report(pre, all_dates, start, end, label):
    """Distribution leg -- information only, no cost model, not tradeable
    (no retail cash-market short selling). Gross forward return only."""
    log('')
    log(f'Distribution (short) leg -- INFORMATION ONLY, no verdict, no cost model -- {label}:')
    dates_in_period = all_dates[(all_dates >= start) & (all_dates <= end)]
    reb_dates = weekly_rebalance_dates(dates_in_period)
    date_list = list(dates_in_period)
    date_pos = {d: i for i, d in enumerate(date_list)}
    fwd_rets = []
    n_signals = 0
    for idx, d in enumerate(sorted(reb_dates)):
        i = date_pos.get(d)
        if i is None or i + 1 >= len(date_list):
            continue
        entry_date = date_list[i + 1]
        cands = pre.dist_by_date.get(d)
        if cands is None or cands.empty:
            continue
        # exit at the NEXT rebalance's entry date (same holding convention as the long leg)
        next_reb = sorted(reb_dates)[idx + 1] if idx + 1 < len(reb_dates) else None
        exit_date = None
        if next_reb is not None:
            j = date_pos.get(next_reb)
            if j is not None and j + 1 < len(date_list):
                exit_date = date_list[j + 1]
        if exit_date is None:
            continue
        for _, row in cands.iterrows():
            sym = row['symbol']
            o_in = pre.open_wide.at[entry_date, sym] if (entry_date in pre.open_wide.index and sym in pre.open_wide.columns) else np.nan
            o_out = pre.open_wide.at[exit_date, sym] if (exit_date in pre.open_wide.index and sym in pre.open_wide.columns) else np.nan
            if pd.isna(o_in) or pd.isna(o_out) or o_in <= 0:
                continue
            fwd_rets.append(o_out / o_in - 1)
            n_signals += 1
    if not fwd_rets:
        log('  No distribution signals with a computable forward return in this window.')
        return
    arr = np.array(fwd_rets)
    log(f'  n signals with computable forward return: {n_signals}')
    log(f'  mean gross forward return (entry open -> next-rebalance entry open): {arr.mean() * 100:+.2f}%')
    log(f'  median gross forward return: {np.median(arr) * 100:+.2f}%')
    log(f'  fraction negative (i.e. distribution "worked" as a would-be short): {(arr < 0).mean() * 100:.1f}%')
    log('  Reminder: gross, no slippage/costs/borrow modeled -- not a tradeable verdict either way.')


# ---------------------------------------------------------------------------
# Header (frozen rules restated first, pattern from trailing_stop_study.py)
# ---------------------------------------------------------------------------
def print_header(smoke):
    log('=' * 92)
    log('DELIVERY-PERCENTAGE FACTOR STUDY (pre-registered, FROZEN)')
    log('Spec: docs/superpowers/specs/2026-07-27-delivery-factor-design.md')
    log('=' * 92)
    log('')
    log('FROZEN RULES (restated before any results below were computed):')
    log('  Signal   : z_t = (DELIV_PER_t - mean_20d)/std_20d over trailing 20 ELIGIBLE days')
    log('             (t-20..t-1, day t excluded, std>0 required).')
    log('             Accumulation = z_t >= +2.0 AND same-day adjusted close-to-close return > 0.')
    log('  Eligible : series EQ, TURNOVER_LACS >= 200, adjusted close >= Rs 20, >= 20 prior')
    log('             eligible days (DELIV_PER-not-NaN folded into the eligibility gate -- see')
    log('             module docstring INTERPRETATION CHOICE).')
    log('  Leak wall: signal computed on day t -> first tradeable action is day t+1 OPEN. Never same-day.')
    log('  Portfolio: weekly, last trading day of week, rank accumulation by z, long top 20 EW,')
    log('             enter next-day open, hold to following rebalance entry open, re-qualifying')
    log('             names held (no cost on held slots).')
    log('  Costs    : zerodha_charges.calculate_charges(buy_v, sell_v, is_intraday=False)[\'total\']')
    log('             (never sum(.values()) -- double-counts) + 0.2%/side slippage both legs.')
    log('  Benchmark: EW daily-rebalanced B&H of the same eligible universe, clip-guarded returns,')
    log('             FRICTIONLESS (no costs/slippage -- deliberately generous to the benchmark).')
    log('  Clip guard: adjusted daily returns clipped +/-25%; HALT if clipping fires on >0.1% of')
    log('             eligible stock-days.')
    log('  Split    : train 2019-10..2023-12, validation 2024-01..2026-07 (or latest data).')
    log('  Verdict  : PRIMARY CONFIG ONLY, pass requires ALL THREE --')
    log('             1) val net CAGR >= B&H val CAGR + 3pp')
    log('             2) train net CAGR >= B&H train CAGR (no sign flip)')
    log('             3) val maxDD <= 1.25x B&H val maxDD (by magnitude)')
    log('  Declared test count: primary + --variant monthly + --variant decile (no verdict weight')
    log('             on the two variants). --short-side is informational only, never a 4th test.')
    if smoke:
        log('')
        log(f'  *** SMOKE MODE: restricted to {SMOKE_START.date()} .. {SMOKE_END.date()} only. ***')
        log('  *** No verdict is computed or printed in smoke mode. ***')
    log('')


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------
def parse_args():
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument('--smoke', action='store_true',
                    help=f'Restrict to {SMOKE_START.date()}..{SMOKE_END.date()}, write to a separate '
                         f'_smoke.txt, print no verdict.')
    p.add_argument('--variant', choices=['monthly', 'decile'], default=None,
                    help='Sensitivity variant (no verdict weight). Default: primary (weekly, top-20).')
    p.add_argument('--short-side', action='store_true',
                    help='Also print the distribution (short) leg informational report.')
    return p.parse_args()


def main():
    args = parse_args()
    print_header(args.smoke)

    panel = prepare_panel()
    all_dates = build_calendar(panel)
    pre = Precomputed(panel)

    if args.smoke:
        smoke_freq = 'monthly' if args.variant == 'monthly' else 'weekly'
        smoke_decile = (args.variant == 'decile')
        log('')
        log('=' * 92)
        log(f'SMOKE RUN: {SMOKE_START.date()} .. {SMOKE_END.date()} '
            f'({args.variant or "primary (weekly, top-20)"} config)')
        log('=' * 92)
        strat = simulate_period(pre, all_dates, SMOKE_START, SMOKE_END, freq=smoke_freq, decile=smoke_decile)
        bh = benchmark_period(pre, all_dates, SMOKE_START, SMOKE_END)
        print_period_row('strategy (smoke)', strat)
        print_period_row('benchmark B&H (smoke)', bh)
        if args.short_side:
            short_side_report(pre, all_dates, SMOKE_START, SMOKE_END, 'smoke window')
        log('')
        log('NO VERDICT IN SMOKE MODE (per spec -- smoke is a plumbing check only, not evidence).')
        out_path = OUT_DIR / 'delivery_factor_results_smoke.txt'
        flush_out(out_path)
        log(f'\n[saved output to {out_path}]')
        return

    variant = args.variant
    freq = 'monthly' if variant == 'monthly' else 'weekly'
    decile = (variant == 'decile')
    verdict_weight = (variant is None)
    label = variant or 'primary (weekly, top-20)'

    val_end_actual = min(VAL_END, all_dates.max()) if len(all_dates) else VAL_END

    log('')
    log('=' * 92)
    log(f'RUN: {label}')
    log('=' * 92)

    train_strat = simulate_period(pre, all_dates, TRAIN_START, TRAIN_END, freq=freq, decile=decile)
    val_strat = simulate_period(pre, all_dates, VAL_START, val_end_actual, freq=freq, decile=decile)
    train_bh = benchmark_period(pre, all_dates, TRAIN_START, TRAIN_END)
    val_bh = benchmark_period(pre, all_dates, VAL_START, val_end_actual)

    log('')
    log(f'Train  ({TRAIN_START.date()} .. {TRAIN_END.date()}):')
    print_period_row('  strategy', train_strat)
    print_period_row('  benchmark B&H', train_bh)
    log(f'Validation ({VAL_START.date()} .. {val_end_actual.date()}):')
    print_period_row('  strategy', val_strat)
    print_period_row('  benchmark B&H', val_bh)

    print_verdict(label, verdict_weight, train_strat, val_strat, train_bh, val_bh)

    if args.short_side:
        short_side_report(pre, all_dates, TRAIN_START, TRAIN_END, 'train window')
        short_side_report(pre, all_dates, VAL_START, val_end_actual, 'validation window')

    suffix = f'_{variant}' if variant else ''
    out_path = OUT_DIR / f'delivery_factor_results{suffix}.txt'
    flush_out(out_path)
    log(f'\n[saved output to {out_path}]')


if __name__ == '__main__':
    main()
