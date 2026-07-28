"""AMFI Band-Crossing Study -- FROZEN pre-registered study.

FROZEN SPEC (read this first, do not deviate without a spec amendment):
    docs/superpowers/specs/2026-07-28-amfi-band-crossing-design.md

Deliverable 2 of 2. Consumes what kite/research/fetch_amfi_bands.py writes to
data/amfi_bands/ (run that FIRST -- it carries the spec's gating recon step,
which passed 18/18 reviews on 2026-07-28).

HYPOTHESIS: SEBI's 2017 fund-categorization circular pins mutual-fund category
minimums to AMFI's half-yearly market-cap ranking (top 100 large, 101-250 mid,
251+ small). A stock crossing a boundary obliges the fund industry to add or
trim it -- mandated flow, published schedule, far less watched than index
reconstitution. If that flow is real and slow, buying promotions at E+1 open
and holding 20 trading days should earn an abnormal return net of costs.

--------------------------------------------------------------------------
EVENTS (frozen cells)
--------------------------------------------------------------------------
Between consecutive lists, joined ON ISIN (not symbol -- ISIN survives ticker
renames and is present in every AMFI file):

    PROMOTION-TO-LARGE   prev != LARGE  -> cur == LARGE   (crosses into top 100)
    PROMOTION-TO-MID     prev == SMALL  -> cur == MID     ("into 101-250 from below")
    DEMOTION-FROM-LARGE  prev == LARGE  -> cur != LARGE
    DEMOTION-FROM-MID    prev == MID    -> cur == SMALL

Note the deliberate asymmetry, which is the spec's wording taken literally:
PROMOTION-TO-MID requires the stock to arrive from SMALL (a MID that came down
from LARGE is a demotion, counted in DEMOTION-FROM-LARGE, not a promotion).

Companies present in `cur` but absent from `prev` (new listings, IPOs) are NOT
events: they did not *cross* a band, they entered the ranking. They are counted
and reported, never traded. Same for companies that vanish from `cur`.

Categories come from AMFI's PUBLISHED RANK (Sr. No.), used verbatim, with the
SEBI boundaries applied as labels. AMFI does not publish a category column;
it publishes the rank, and the rank is what the circular keys off. Nothing is
recomputed from prices -- the spec forbids that (no shares-outstanding data).

--------------------------------------------------------------------------
EVENT DATE E (spec: actual publication date; else 5th trading day of Jan/Jul,
"flagged per event")
--------------------------------------------------------------------------
E is the publication date of the LATER list of the pair. fetch_amfi_bands.py
verifies a publication date only when the file's HTTP Last-Modified falls in
the month publication was actually due (Jan for a Jul-Dec list, Jul for a
Jan-Jun list). That verifies 2 of 18; the other 16 carry a bulk re-upload
timestamp from AMFI's 2025 site migration and are NOT trusted.

    pub_date_source == 'last-modified'  ->  E = first trading day >= that date
    pub_date_source == 'fallback'       ->  E = 5th trading day of the
                                             publication month (conservative,
                                             deliberately late)

Every event row prints which rule produced its E. The per-review E table is
printed before any result, so the reviewer can audit dating independently of
outcomes.

--------------------------------------------------------------------------
TRADE LEG (verdict-bearing, PROMOTIONS ONLY -- long-only constraint)
--------------------------------------------------------------------------
Long at E+1 OPEN (the first trading day strictly after E), hold 20 trading
days, exit at the OPEN of the 20th day after entry. LEAK WALL: E is a
publication date; the first tradeable action is the NEXT session's open. Never
same-day.

COSTS (frozen): full delivery charges via
    from kite.config import zerodha_charges
    zerodha_charges.calculate_charges(buy_v, sell_v, is_intraday=False)['total']
NEVER sum(charges.values()) -- that dict already contains a 'total' key equal
to the sum of the other six components; summing everything double-counts (the
exact bug fixed across this repo on 2026-07-26/27). Plus 0.2%/side slippage
applied to the fill price before the charges call.

POSITION SIZE (interpretation choice, flagged): the DP charge is a FLAT
Rs 13.5 + GST per delivery sell, so a per-event cost in percent is undefined
without a position size. This study sizes every event at a notional
Rs 25,000 -- the October Contract's first staged tranche -- and prints the
REALIZED mean round-trip cost so the reviewer can compare it against the
spec's stated 0.9% hurdle. The 0.9% figure itself is used verbatim as the
frozen hurdle constant in verdict criterion 3; it is NOT recalibrated to the
realized number, because it is frozen.

--------------------------------------------------------------------------
BENCHMARK (frozen: "equal-weight universe abnormal return")
--------------------------------------------------------------------------
Equal-weight, daily-rebalanced universe return over the SAME date span,
frictionless (no costs, no slippage -- a deliberately generous counterfactual,
same convention as delivery_factor_study.py). Universe eligibility follows the
repo convention: SERIES == EQ, TURNOVER_LACS >= 200 (Rs 2 crore), adjusted
close >= Rs 20. Daily returns clipped to +/-25% (brief rule R9), cross-
sectional mean with skipna, prefix-compounded -- same construction as
event_study.py's build_universe_returns().

ONE DOCUMENTED DEVIATION from event_study.py: that script compounds CLOSE-to-
CLOSE because its event leg is close-based. This study's leg is OPEN-to-OPEN
(entry open -> exit open), so the benchmark is built from OPEN-to-OPEN daily
returns instead. Mixing the two would silently offset the abnormal return by
one overnight gap per event. The clipping, skipna-mean and prefix-compounding
conventions are otherwise unchanged.

    AR = (net-of-cost stock return, entry open -> exit open)
         - (frictionless EW universe return over the same span)

--------------------------------------------------------------------------
VERDICT (frozen, per promotion cell, ALL must hold)
--------------------------------------------------------------------------
1. Mean 20d excess AR (net of costs) > 0 in BOTH era halves
   (reviews 2018-2021 vs 2022-2026, split on PUBLICATION year).
2. Pooled t >= +2.0, clustered BY REVIEW DATE.
3. Combined promotion cells' net edge >= 1.5x the 0.9% cost hurdle (= 1.35%).

Declared test count: 2 (the two promotion cells). Demotion cells and
pre-publication drift are INFORMATION ONLY and carry no verdict weight.

CLUSTER-ROBUST t (criterion 2) -- exact formula as implemented, because the
spec makes review-date clustering mandatory and thin (G ~ 13-16):

    x_i     = per-event AR, i = 1..N
    g       = review (publication date) each event belongs to, G clusters
    m       = (1/N) * sum_i x_i
    e_i     = x_i - m
    meat    = sum_g ( sum_{i in g} e_i )^2
    c       = [G/(G-1)] * [(N-1)/(N-k)],  k = 1  ->  c = G/(G-1)
    Var(m)  = c * meat / N^2
    se      = sqrt(Var(m))
    t       = m / se

This is the one-way Liang-Zeger cluster-robust variance for a regression of x
on a constant, with the standard Stata-style finite-sample correction. With
k = 1 the (N-1)/(N-k) term is exactly 1, so c reduces to G/(G-1); it is
written out in full anyway so the correction being applied is unambiguous.
It converges to the ordinary t only if every cluster has exactly one event.

--------------------------------------------------------------------------
CAVEATS (stated before results, per spec)
--------------------------------------------------------------------------
- ~13-16 review clusters is LOW POWER. A marginal pass is weak evidence and
  is labelled as such in the verdict block.
- SEBI allows funds +/-20% flexibility, softening the "forced" flow.
- Funds can anticipate crossings before publication; E+1 entry may be late.
  Pre-publication drift (E-20..E and E-60..E) is measured to size what we
  are missing. Information only.
- AMFI ranks use NSE+BSE combined mcap; our panel is NSE-only. Per the spec
  this affects JOINS, not ranks -- ranks are used verbatim. The top-300 join
  rate is 96-99% per review (see fetch_amfi_bands.py's report).

- BINDING DATA LIMIT, NOT ANTICIPATED BY THE SPEC: the AMFI archive goes back
  to Jul-Dec 2017, but data/bhavcopy_full/ starts 2019-10-01. Reviews
  published before that have no prices. The spec sized for "~16-17 clusters";
  the price panel, not AMFI, caps the usable count at ~13. The exact usable
  set is computed and printed at runtime rather than assumed, and the era
  split in criterion 1 becomes lopsided as a result (roughly 4 clusters in
  the 2018-2021 half vs 9 in the 2022-2026 half). This weakens power further
  and is called out in the verdict block.

Usage:
    python kite/research/amfi_band_study.py --smoke   # 2 reviews -> _smoke.txt
    python kite/research/amfi_band_study.py           # full verdict run
"""

import argparse
import re
import sys
from pathlib import Path

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))
from kite.config import zerodha_charges  # noqa: E402  (['total'] only -- see docstring)

BANDS_DIR = ROOT / 'data' / 'amfi_bands'
PANEL_DIR = ROOT / 'data' / 'bhavcopy_full'
CORP_ACTIONS_PATH = ROOT / 'data' / 'corp_actions_adjustments.csv'
OUT_DIR = Path(__file__).resolve().parent

# ---------------------------------------------------------------------------
# Frozen constants
# ---------------------------------------------------------------------------
HOLD_DAYS = 20                # trading days, entry open -> exit open
SLIP = 0.002                  # 0.2% per side
NOTIONAL_PER_EVENT = 25_000.0  # position size (see docstring: DP is flat)
COST_HURDLE = 0.009           # frozen 0.9% round-trip hurdle (spec)
EDGE_MULTIPLE = 1.5           # criterion 3: >= 1.5x the hurdle
T_BAR = 2.0                   # criterion 2
MIN_TURNOVER_LACS = 200.0     # Rs 2 crore  (repo convention)
MIN_PRICE = 20.0              # Rs 20 adjusted close
CLIP = 0.25                   # +/-25% daily return clip (brief R9)
FALLBACK_TRADING_DAY = 5      # spec: 5th trading day of Jan/Jul
ERA_SPLIT_PUB_YEAR = 2022     # criterion 1: <2022 vs >=2022 (publication year)
PRE_DRIFT_WINDOWS = (20, 60)  # information only

LARGE_MAX_RANK = 100
MID_MAX_RANK = 250

PROMOTION_CELLS = ['PROMOTION-TO-LARGE', 'PROMOTION-TO-MID']
DEMOTION_CELLS = ['DEMOTION-FROM-LARGE', 'DEMOTION-FROM-MID']

FNAME_DATE_RE = re.compile(r'sec_bhavdata_full_(\d{2})(\d{2})(\d{4})\.csv$', re.IGNORECASE)
NEEDED_COLS = ['SYMBOL', 'SERIES', 'OPEN_PRICE', 'CLOSE_PRICE', 'TURNOVER_LACS']

_OUT = []


def log(msg=''):
    print(msg, flush=True)
    _OUT.append(str(msg))


def flush_out(path):
    path.write_text('\n'.join(_OUT) + '\n', encoding='utf-8')


# ---------------------------------------------------------------------------
# Panel loading (same conventions as delivery_factor_study.py, restricted to
# the date window the selected events actually need so --smoke stays fast).
# ---------------------------------------------------------------------------
def panel_files_in_range(lo=None, hi=None):
    out = []
    for f in PANEL_DIR.glob('sec_bhavdata_full_*.csv'):
        m = FNAME_DATE_RE.search(f.name)
        if not m:
            continue
        d = pd.Timestamp(year=int(m.group(3)), month=int(m.group(2)), day=int(m.group(1)))
        if (lo is None or d >= lo) and (hi is None or d <= hi):
            out.append((d, f))
    return sorted(out)


def load_panel(lo=None, hi=None):
    files = panel_files_in_range(lo, hi)
    if not files:
        sys.exit(f'HALTED: no bhavcopy files under {PANEL_DIR} in range {lo}..{hi}. '
                 f'Run fetch_bhavcopy_full.py first.')
    frames, skipped = [], 0
    for d, f in files:
        try:
            df = pd.read_csv(f, dtype=str, encoding='utf-8')
        except Exception as e:
            log(f'  WARN: failed to read {f.name}: {type(e).__name__}: {e}, skipping')
            skipped += 1
            continue
        df.columns = df.columns.str.strip()
        missing = [c for c in NEEDED_COLS if c not in df.columns]
        if missing:
            log(f'  WARN: {f.name} missing columns {missing}, skipping file')
            skipped += 1
            continue
        df = df[NEEDED_COLS].copy()
        for c in NEEDED_COLS:
            df[c] = df[c].astype(str).str.strip()
        df = df[df['SERIES'] == 'EQ']
        if df.empty:
            continue
        df = df.assign(date=d)
        for c in ['OPEN_PRICE', 'CLOSE_PRICE', 'TURNOVER_LACS']:
            df[c] = pd.to_numeric(df[c], errors='coerce')
        frames.append(df.rename(columns={
            'SYMBOL': 'symbol', 'OPEN_PRICE': 'open', 'CLOSE_PRICE': 'close',
            'TURNOVER_LACS': 'turnover_lacs',
        })[['symbol', 'date', 'open', 'close', 'turnover_lacs']])
    if not frames:
        sys.exit('HALTED: every bhavcopy file in range was unusable.')
    panel = pd.concat(frames, ignore_index=True)
    panel = panel.drop_duplicates(subset=['symbol', 'date'], keep='last')
    panel = panel.sort_values(['symbol', 'date']).reset_index(drop=True)
    log(f'Loaded {len(files)} bhavcopy files ({skipped} skipped), {len(panel)} EQ '
        f'stock-day rows, {panel.symbol.nunique()} symbols, '
        f'{panel.date.min().date()} -> {panel.date.max().date()}')
    return panel


def load_corp_actions():
    if not CORP_ACTIONS_PATH.exists():
        sys.exit(f'HALTED: {CORP_ACTIONS_PATH} not found. Run build_corp_actions.py first.')
    df = pd.read_csv(CORP_ACTIONS_PATH)
    df['ex_date'] = pd.to_datetime(df['ex_date'])
    return df


def halt_on_unresolved_nan_factors(panel, corp_actions):
    """HALT if a NaN-factor (unparseable split/bonus) corporate action touches a
    symbol that has panel data BEFORE its ex_date -- the missing factor would
    silently corrupt a price this study actually uses. Same rule as
    delivery_factor_study.py."""
    nan_rows = corp_actions[corp_actions['factor'].isna()]
    if nan_rows.empty:
        return
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
        flush_out(OUT_DIR / 'amfi_band_results_HALTED.txt')
        sys.exit(f'HALTED: {len(offenders)} unresolved corp-action factor(s) affect the '
                 f'loaded panel. Fix build_corp_actions.py parsing before re-running.')


def apply_corp_action_adjustments(panel, corp_actions):
    """Back-adjust OPEN/CLOSE: multiply by the cumulative product of all factors
    whose ex_date is STRICTLY AFTER the row's date (compounds across multiple
    actions). Identical convention to delivery_factor_study.py."""
    valid = corp_actions.dropna(subset=['factor'])
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
    panel['adj_open'] = panel['open'] * mult
    panel['adj_close'] = panel['close'] * mult
    log(f'Corporate-action adjustment applied: {int((mult != 1.0).sum())} stock-day rows '
        f'scaled, {valid["symbol"].nunique()} symbols with >=1 valid action.')
    return panel


class Panel:
    """Wide open/eligibility matrices + the prefix-compounded EW benchmark."""

    def __init__(self, panel):
        panel = panel.copy()
        panel['eligible'] = ((panel['turnover_lacs'] >= MIN_TURNOVER_LACS)
                             & (panel['adj_close'] >= MIN_PRICE))
        self.open_wide = panel.pivot_table(index='date', columns='symbol',
                                           values='adj_open', aggfunc='last').sort_index()
        elig = (panel.pivot_table(index='date', columns='symbol', values='eligible',
                                  aggfunc='last')
                .reindex_like(self.open_wide).to_numpy(dtype=bool, na_value=False))
        self.dates = pd.DatetimeIndex(self.open_wide.index)
        self._dvals = self.dates.values
        self.symbols = set(self.open_wide.columns)

        # EW universe, OPEN-to-OPEN (see docstring for why not close-to-close).
        raw = self.open_wide / self.open_wide.shift(1) - 1.0
        # a day's return only counts if the stock was eligible on BOTH ends
        prev_elig = np.vstack([np.zeros((1, elig.shape[1]), dtype=bool), elig[:-1]])
        raw = raw.where(pd.DataFrame(elig & prev_elig, index=self.open_wide.index,
                                     columns=self.open_wide.columns))
        n_valid = int(raw.notna().sum().sum())
        n_clip = int((raw.abs() > CLIP).sum().sum())
        self.clip_frac = (n_clip / n_valid) if n_valid else 0.0
        u = raw.clip(-CLIP, CLIP).mean(axis=1, skipna=True).fillna(0.0)
        self.P = (1.0 + u.values).cumprod()
        self.n_universe = raw.notna().sum(axis=1)
        log(f'EW benchmark built: {n_valid} eligible open-to-open stock-day returns, '
            f'{n_clip} ({100 * self.clip_frac:.4f}%) hit the +/-{CLIP * 100:.0f}% clip; '
            f'median daily universe breadth = {int(self.n_universe.median())} names.')

    def pos_on_or_after(self, ts):
        p = int(np.searchsorted(self._dvals, np.datetime64(ts), side='left'))
        return p if p < len(self._dvals) else None

    def pos_after(self, ts):
        p = int(np.searchsorted(self._dvals, np.datetime64(ts), side='right'))
        return p if p < len(self._dvals) else None

    def nth_trading_day_of_month(self, year, month, n):
        sel = np.where((self.dates.year == year) & (self.dates.month == month))[0]
        return int(sel[n - 1]) if len(sel) >= n else None

    def open_at(self, sym, pos):
        if sym not in self.symbols or pos is None or pos < 0 or pos >= len(self.dates):
            return np.nan
        return self.open_wide.iat[pos, self.open_wide.columns.get_loc(sym)]

    def bench(self, a_pos, b_pos):
        """Frictionless EW universe return compounded from the OPEN of a_pos to
        the OPEN of b_pos (i.e. over daily open-to-open returns a_pos+1..b_pos)."""
        if a_pos is None or b_pos is None or a_pos < 0 or b_pos >= len(self.P):
            return np.nan
        return self.P[b_pos] / self.P[a_pos] - 1.0


# ---------------------------------------------------------------------------
# Reviews -> events
# ---------------------------------------------------------------------------
def load_reviews():
    man_path = BANDS_DIR / 'amfi_reviews.csv'
    if not man_path.exists():
        sys.exit(f'HALTED: {man_path} not found. Run kite/research/fetch_amfi_bands.py '
                 f'first -- it carries the spec\'s gating recon step.')
    man = pd.read_csv(man_path).sort_values(['period_year', 'period_half']).reset_index(drop=True)
    lists = {}
    for _, r in man.iterrows():
        df = pd.read_csv(BANDS_DIR / r['csv_file'],
                         dtype={'isin': str, 'nse_symbol': str, 'company_name': str})
        df['isin'] = df['isin'].fillna('').str.strip().str.upper()
        df['nse_symbol'] = df['nse_symbol'].fillna('').str.strip()
        lists[r['period']] = df
    return man, lists


def resolve_event_date(row, P):
    """E per spec. Returns (pos, source_label) or (None, reason)."""
    src = str(row['pub_date_source'])
    if src == 'last-modified' and str(row['pub_date']):
        p = P.pos_on_or_after(pd.Timestamp(str(row['pub_date'])))
        if p is not None:
            return p, 'verified(last-modified)'
        return None, 'verified date beyond panel'
    p = P.nth_trading_day_of_month(int(row['pub_year']), int(row['pub_month']),
                                   FALLBACK_TRADING_DAY)
    if p is None:
        return None, f'fallback: panel has no {FALLBACK_TRADING_DAY}th trading day in ' \
                     f'{int(row["pub_month"]):02d}/{int(row["pub_year"])}'
    return p, f'FALLBACK({FALLBACK_TRADING_DAY}th trading day)'


def classify(prev_cat, cur_cat):
    if cur_cat == 'LARGE' and prev_cat != 'LARGE':
        return 'PROMOTION-TO-LARGE'
    if cur_cat == 'MID' and prev_cat == 'SMALL':
        return 'PROMOTION-TO-MID'
    if prev_cat == 'LARGE' and cur_cat != 'LARGE':
        return 'DEMOTION-FROM-LARGE'
    if prev_cat == 'MID' and cur_cat == 'SMALL':
        return 'DEMOTION-FROM-MID'
    return None


def build_events(man, lists, P, transitions):
    """One row per (review transition, crossing stock). Drops are counted."""
    rows, diag = [], []
    for i_cur in transitions:
        prev_p = man.iloc[i_cur - 1]['period']
        cur_p = man.iloc[i_cur]['period']
        prev, cur = lists[prev_p], lists[cur_p]

        e_pos, e_src = resolve_event_date(man.iloc[i_cur], P)
        entry_pos = (e_pos + 1) if e_pos is not None else None
        if entry_pos is not None and entry_pos >= len(P.dates):
            entry_pos = None
        exit_pos = (entry_pos + HOLD_DAYS) if entry_pos is not None else None
        if exit_pos is not None and exit_pos >= len(P.dates):
            exit_pos = None

        pv = prev[prev['isin'].str.len() == 12].drop_duplicates('isin', keep='first')
        cv = cur[cur['isin'].str.len() == 12].drop_duplicates('isin', keep='first')
        m = cv.merge(pv[['isin', 'rank', 'category']].rename(
            columns={'rank': 'prev_rank', 'category': 'prev_category'}),
            on='isin', how='left')
        n_new = int(m['prev_category'].isna().sum())
        matched = m[m['prev_category'].notna()].copy()
        matched['cell'] = [classify(a, b) for a, b in
                           zip(matched['prev_category'], matched['category'])]
        ev = matched[matched['cell'].notna()].copy()

        d = {'transition': f'{prev_p}->{cur_p}', 'pub_period': cur_p,
             'E': P.dates[e_pos].date().isoformat() if e_pos is not None else '(none)',
             'E_source': e_src,
             'entry': P.dates[entry_pos].date().isoformat() if entry_pos is not None else '(none)',
             'exit': P.dates[exit_pos].date().isoformat() if exit_pos is not None else '(none)',
             'n_prev': len(pv), 'n_cur': len(cv), 'n_matched': len(matched),
             'n_new_listings_excluded': n_new, 'n_crossings': len(ev),
             'n_no_nse': 0, 'n_not_in_panel': 0, 'n_no_price': 0,
             'n_undatable': 0, 'n_usable': 0}

        for _, r in ev.iterrows():
            sym = r['nse_symbol']
            rec = {
                'transition': d['transition'], 'pub_period': cur_p,
                'pub_year': int(man.iloc[i_cur]['pub_year']),
                'review_date': d['E'], 'E_source': e_src, 'cell': r['cell'],
                'isin': r['isin'], 'symbol': sym, 'company_name': r['company_name'],
                'prev_rank': int(r['prev_rank']), 'cur_rank': int(r['rank']),
                'prev_category': r['prev_category'], 'category': r['category'],
                'e_pos': e_pos, 'entry_pos': entry_pos, 'exit_pos': exit_pos,
                'drop_reason': '',
            }
            if e_pos is None:
                # Publication month falls entirely outside the price panel --
                # this is the 2018-2019 reviews, where AMFI has data but
                # data/bhavcopy_full/ does not. Reported separately from a
                # genuine missing-price drop so the two are never conflated.
                rec['drop_reason'] = f'E undatable: {e_src}'
                d['n_undatable'] += 1
            elif not sym:
                rec['drop_reason'] = 'no NSE symbol in AMFI list (BSE-only)'
                d['n_no_nse'] += 1
            elif sym not in P.symbols:
                rec['drop_reason'] = 'symbol absent from bhavcopy EQ panel'
                d['n_not_in_panel'] += 1
            elif entry_pos is None or exit_pos is None:
                rec['drop_reason'] = 'hold window extends past the end of the panel'
                d['n_no_price'] += 1
            else:
                o_in = P.open_at(sym, entry_pos)
                o_out = P.open_at(sym, exit_pos)
                if not (np.isfinite(o_in) and np.isfinite(o_out) and o_in > 0 and o_out > 0):
                    rec['drop_reason'] = 'no open price on entry and/or exit day'
                    d['n_no_price'] += 1
                else:
                    rec.update(compute_legs(P, sym, entry_pos, exit_pos, e_pos, o_in, o_out))
                    d['n_usable'] += 1
            rows.append(rec)
        diag.append(d)
    return pd.DataFrame(rows), pd.DataFrame(diag)


def compute_legs(P, sym, entry_pos, exit_pos, e_pos, o_in, o_out):
    """Net trade return, benchmark, AR, plus information-only drift windows."""
    buy_px = o_in * (1 + SLIP)
    sell_px = o_out * (1 - SLIP)
    qty = int(NOTIONAL_PER_EVENT // buy_px)
    if qty < 1:
        return {'drop_reason': f'notional Rs{NOTIONAL_PER_EVENT:,.0f} buys <1 share '
                               f'at Rs{buy_px:,.2f}'}
    buy_v = qty * buy_px
    sell_v = qty * sell_px
    fees = zerodha_charges.calculate_charges(buy_v, sell_v, is_intraday=False)['total']
    gross_ret = o_out / o_in - 1.0
    net_ret = (sell_v - fees) / buy_v - 1.0
    bench = P.bench(entry_pos, exit_pos)
    out = {
        'qty': qty, 'entry_open': o_in, 'exit_open': o_out,
        'gross_ret': gross_ret, 'net_ret': net_ret,
        'cost_frac': gross_ret - net_ret,        # slippage + charges, in return units
        'fees': fees, 'bench_ret': bench,
        'ar_net': net_ret - bench,               # VERDICT quantity
        'ar_gross': gross_ret - bench,
    }
    # Pre-publication drift (information only): stock vs EW universe over the
    # k trading days ending AT E -- i.e. what we would have missed by waiting.
    for k in PRE_DRIFT_WINDOWS:
        a = e_pos - k
        val = np.nan
        if a >= 0:
            oa, ob = P.open_at(sym, a), P.open_at(sym, e_pos)
            if np.isfinite(oa) and np.isfinite(ob) and oa > 0:
                b = P.bench(a, e_pos)
                if np.isfinite(b):
                    val = (ob / oa - 1.0) - b
        out[f'pre_ar_{k}d'] = val
    return out


# ---------------------------------------------------------------------------
# Statistics
# ---------------------------------------------------------------------------
def cluster_t(x, clusters):
    """One-way cluster-robust t for the mean of x, clustered on `clusters`.

    See the module docstring for the frozen formula. Returns
    (mean, se, t, N, G); NaNs when undefined (N<2 or G<2).
    """
    x = np.asarray(x, dtype=float)
    keep = np.isfinite(x)
    x, cl = x[keep], np.asarray(clusters, dtype=object)[keep]
    n = len(x)
    if n < 2:
        return (float(x.mean()) if n else np.nan), np.nan, np.nan, n, len(set(cl))
    m = float(x.mean())
    e = x - m
    groups = {}
    for gi, ei in zip(cl, e):
        groups[gi] = groups.get(gi, 0.0) + ei
    g = len(groups)
    if g < 2:
        return m, np.nan, np.nan, n, g
    meat = float(sum(v * v for v in groups.values()))
    c = (g / (g - 1.0)) * ((n - 1.0) / (n - 1.0))  # k=1 -> second factor is 1
    var = c * meat / (n * n)
    se = float(np.sqrt(var)) if var > 0 else np.nan
    t = (m / se) if (se and np.isfinite(se) and se > 0) else np.nan
    return m, se, t, n, g


def describe(sub, col='ar_net'):
    v = sub[col].dropna().to_numpy()
    if len(v) == 0:
        return dict(n=0, mean=np.nan, median=np.nan, std=np.nan, hit=np.nan)
    return dict(n=len(v), mean=float(v.mean()), median=float(np.median(v)),
                std=float(v.std(ddof=1)) if len(v) > 1 else np.nan,
                hit=float((v > 0).mean()))


def pct(x, nd=2):
    return 'n/a' if x is None or not np.isfinite(x) else f'{x * 100:+.{nd}f}%'


def num(x, nd=2):
    return 'n/a' if x is None or not np.isfinite(x) else f'{x:.{nd}f}'


# ---------------------------------------------------------------------------
# Reporting
# ---------------------------------------------------------------------------
def print_header(smoke, n_reviews, n_transitions):
    log('=' * 78)
    log('AMFI BAND-CROSSING STUDY -- FROZEN RULES (stated before any result)')
    log('=' * 78)
    log('Spec      : docs/superpowers/specs/2026-07-28-amfi-band-crossing-design.md')
    log(f'Mode      : {"SMOKE (2 reviews only -- NO VERDICT WEIGHT)" if smoke else "FULL VERDICT RUN"}')
    log('')
    log('Cells (frozen, joined between consecutive AMFI lists ON ISIN):')
    log('  PROMOTION-TO-LARGE   prev != LARGE -> cur == LARGE      [verdict-bearing]')
    log('  PROMOTION-TO-MID     prev == SMALL -> cur == MID        [verdict-bearing]')
    log('  DEMOTION-FROM-LARGE  prev == LARGE -> cur != LARGE      [information only]')
    log('  DEMOTION-FROM-MID    prev == MID   -> cur == SMALL      [information only]')
    log('  Categories from AMFI\'s PUBLISHED RANK, used verbatim:')
    log(f'    rank 1-{LARGE_MAX_RANK} LARGE | {LARGE_MAX_RANK + 1}-{MID_MAX_RANK} MID | '
        f'{MID_MAX_RANK + 1}+ SMALL. Nothing recomputed from prices.')
    log('  New listings (absent from the previous list) are NOT events.')
    log('')
    log('Trade leg (PROMOTIONS ONLY, long-only constraint):')
    log(f'  long at E+1 OPEN, hold {HOLD_DAYS} trading days, exit at OPEN')
    log(f'  slippage {SLIP * 100:.1f}%/side; charges via')
    log('    zerodha_charges.calculate_charges(buy_v, sell_v, is_intraday=False)[\'total\']')
    log(f'  position notional Rs {NOTIONAL_PER_EVENT:,.0f}/event (DP charge is flat, so a')
    log('    percent cost is undefined without a size -- flagged interpretation choice)')
    log('')
    log('Benchmark : equal-weight universe, daily-rebalanced, FRICTIONLESS,')
    log(f'            OPEN-to-OPEN over the same span, returns clipped +/-{CLIP * 100:.0f}%,')
    log(f'            universe = EQ & turnover >= Rs {MIN_TURNOVER_LACS:.0f}L & adj close >= Rs {MIN_PRICE:.0f}')
    log('  AR = net-of-cost stock return - frictionless EW universe return')
    log('')
    log('Verdict (frozen, per promotion cell, ALL must hold):')
    log('  1. Mean 20d excess AR (net) > 0 in BOTH era halves')
    log(f'     (publication year < {ERA_SPLIT_PUB_YEAR} vs >= {ERA_SPLIT_PUB_YEAR})')
    log(f'  2. Pooled t >= +{T_BAR:.1f}, CLUSTERED BY REVIEW DATE')
    log(f'  3. Combined promotion cells\' net edge >= {EDGE_MULTIPLE}x the '
        f'{COST_HURDLE * 100:.1f}% cost hurdle = {EDGE_MULTIPLE * COST_HURDLE * 100:.2f}%')
    log('  Declared test count: 2 (the two promotion cells).')
    log('  Demotion cells + pre-publication drift: INFORMATION ONLY, no verdict weight.')
    log('')
    log('Cluster-robust t formula (as implemented):')
    log('  m = mean(x); e_i = x_i - m; meat = sum_g (sum_{i in g} e_i)^2')
    log('  c = [G/(G-1)] * [(N-1)/(N-k)], k=1  ->  c = G/(G-1)')
    log('  Var(m) = c * meat / N^2;  se = sqrt(Var(m));  t = m / se')
    log('')
    log('Caveats (stated BEFORE results, per spec):')
    log('  - Low power: G is ~13-16 review clusters. A marginal pass is WEAK evidence.')
    log('  - SEBI allows funds +/-20% flexibility, softening the "forced" flow.')
    log('  - Funds can anticipate crossings; E+1 entry may be late (drift measured).')
    log('  - AMFI ranks are NSE+BSE combined; our panel is NSE-only. Affects joins,')
    log('    not ranks. Top-300 join rate is 96-99%/review (fetch_amfi_bands.py).')
    log('  - BENCHMARK SIZE TILT (observed, not a bug, NOT adjusted for -- the EW')
    log('    universe is frozen by the spec): every event here sits in roughly the')
    log('    top 300 by mcap, while the EW universe is ~1,100+ names dominated by')
    log('    much smaller ones. When small caps run, ALL FOUR cells will show')
    log('    negative AR for reasons that have nothing to do with band crossings.')
    log('    Read the promotion-vs-demotion SPREAD, not the level, when this bites.')
    log('  - E is a VERIFIED publication date for only 2 of 18 lists; the rest use the')
    log('    spec fallback (5th trading day of Jan/Jul). Flagged per event below.')
    log('  - BINDING LIMIT: AMFI archive starts Jul-Dec 2017 but data/bhavcopy_full/')
    log('    starts 2019-10-01, so the PRICE PANEL (not AMFI) caps usable reviews.')
    log(f'    Reviews loaded: {n_reviews}; transitions selected this run: {n_transitions}.')
    log('=' * 78)
    log('')


def print_diagnostics(diag):
    log('--- PER-REVIEW EVENT CONSTRUCTION (audit this before reading results) ---')
    log(f'  {"transition":<17} {"E":<11} {"entry":<11} {"exit":<11} {"cross":>6} {"usable":>7}  E source')
    for _, r in diag.iterrows():
        log(f'  {r["transition"]:<17} {r["E"]:<11} {r["entry"]:<11} {r["exit"]:<11} '
            f'{r["n_crossings"]:>6} {r["n_usable"]:>7}  {r["E_source"]}')
    log('')
    log('  Drop accounting per transition (why a crossing did not become a trade):')
    log(f'  {"transition":<17} {"prevN":>6} {"curN":>6} {"newLst":>7} {"noDate":>7} '
        f'{"noNSE":>6} {"notPanel":>9} {"noPrice":>8}')
    for _, r in diag.iterrows():
        log(f'  {r["transition"]:<17} {r["n_prev"]:>6} {r["n_cur"]:>6} '
            f'{r["n_new_listings_excluded"]:>7} {r["n_undatable"]:>7} {r["n_no_nse"]:>6} '
            f'{r["n_not_in_panel"]:>9} {r["n_no_price"]:>8}')
    n_dead = int((diag['n_usable'] == 0).sum())
    if n_dead:
        log(f'  NOTE: {n_dead} transition(s) produced ZERO usable events -- almost always '
            f'because the review predates data/bhavcopy_full/ (starts 2019-10-01).')
    log('')


def cell_block(ev, cell, verdict_bearing):
    sub = ev[(ev['cell'] == cell) & ev['ar_net'].notna()]
    tag = '[VERDICT]' if verdict_bearing else '[INFO ONLY]'
    log(f'--- {cell}  {tag} ---')
    if sub.empty:
        log('  no usable events')
        log('')
        return None
    d = describe(sub, 'ar_net')
    dg = describe(sub, 'ar_gross')
    m, se, t, n, g = cluster_t(sub['ar_net'], sub['review_date'])
    log(f'  events N={d["n"]}   review clusters G={g}   '
        f'mean events/cluster={d["n"] / max(g, 1):.1f}')
    log(f'  20d AR gross : mean {pct(dg["mean"])}  median {pct(dg["median"])}')
    log(f'  20d AR net   : mean {pct(d["mean"])}  median {pct(d["median"])}  '
        f'std {pct(d["std"])}  hit-rate {pct(d["hit"], 1) if np.isfinite(d["hit"]) else "n/a"}')
    log(f'  mean round-trip cost drag: {pct(sub["cost_frac"].mean())} '
        f'(frozen hurdle for criterion 3 is {COST_HURDLE * 100:.1f}%)')
    log(f'  cluster-by-review-date t = {num(t)}   (se {pct(se, 3)}, N={n}, G={g})')
    if g < 5:
        log(f'      !! G={g} clusters. A cluster-robust t is NOT INTERPRETABLE at this')
        log(f'         few clusters -- the cluster sums can nearly cancel and drive the')
        log(f'         se toward zero, inflating |t| arbitrarily. DO NOT read this t as')
        log(f'         evidence. (Expected in --smoke, which uses 2 reviews by design.)')
    era_a = sub[sub['pub_year'] < ERA_SPLIT_PUB_YEAR]
    era_b = sub[sub['pub_year'] >= ERA_SPLIT_PUB_YEAR]
    ma = era_a['ar_net'].mean() if len(era_a) else np.nan
    mb = era_b['ar_net'].mean() if len(era_b) else np.nan
    log(f'  era half A (pub < {ERA_SPLIT_PUB_YEAR}): N={len(era_a)}  '
        f'clusters={era_a["review_date"].nunique()}  mean AR {pct(ma)}')
    log(f'  era half B (pub >= {ERA_SPLIT_PUB_YEAR}): N={len(era_b)}  '
        f'clusters={era_b["review_date"].nunique()}  mean AR {pct(mb)}')
    for k in PRE_DRIFT_WINDOWS:
        col = f'pre_ar_{k}d'
        log(f'  pre-publication drift E-{k}d..E (INFO ONLY, not tradeable): '
            f'mean AR {pct(sub[col].mean())}  N={int(sub[col].notna().sum())}')
    log('')
    return {'cell': cell, 'n': d['n'], 'mean': d['mean'], 't': t, 'G': g,
            'era_a_n': len(era_a), 'era_b_n': len(era_b), 'era_a': ma, 'era_b': mb}


def print_verdict(stats, ev, smoke):
    log('=' * 78)
    log('VERDICT')
    log('=' * 78)
    if smoke:
        log('SMOKE RUN -- 2 reviews only. NO VERDICT. This run exists to prove the')
        log('pipeline executes end-to-end; the numbers above carry no evidential')
        log('weight and must not be quoted. Run without --smoke for the verdict.')
        log('=' * 78)
        return

    promo = ev[ev['cell'].isin(PROMOTION_CELLS) & ev['ar_net'].notna()]
    combined = promo['ar_net'].mean() if len(promo) else np.nan
    bar3 = EDGE_MULTIPLE * COST_HURDLE
    c3 = bool(np.isfinite(combined) and combined >= bar3)
    log(f'Criterion 3 (shared): combined promotion-cell net edge {pct(combined)} '
        f'vs required {pct(bar3)}  -> {"PASS" if c3 else "FAIL"}')
    log(f'  (combined over N={len(promo)} promotion events, '
        f'G={promo["review_date"].nunique()} review clusters)')
    log('')
    any_pass = False
    for s in stats:
        if s is None or s['cell'] not in PROMOTION_CELLS:
            continue
        c1 = bool(np.isfinite(s['era_a']) and np.isfinite(s['era_b'])
                  and s['era_a'] > 0 and s['era_b'] > 0)
        c2 = bool(np.isfinite(s['t']) and s['t'] >= T_BAR)
        ok = c1 and c2 and c3
        any_pass = any_pass or ok
        log(f'{s["cell"]}:')
        log(f'  1. mean AR > 0 in BOTH era halves : A {pct(s["era_a"])} (N={s["era_a_n"]}), '
            f'B {pct(s["era_b"])} (N={s["era_b_n"]})  -> {"PASS" if c1 else "FAIL"}')
        if not (s['era_a_n'] and s['era_b_n']):
            log('     NOTE: an era half is EMPTY -- criterion 1 cannot be satisfied.')
        log(f'  2. cluster-by-review t >= +{T_BAR:.1f}     : t = {num(s["t"])} '
            f'(G={s["G"]})  -> {"PASS" if c2 else "FAIL"}')
        log(f'  3. combined edge >= {pct(bar3)}       : {"PASS" if c3 else "FAIL"} (shared)')
        log(f'  => {s["cell"]}: {"PASS" if ok else "FAIL"}')
        log('')
    log(f'OVERALL: {"PASS" if any_pass else "FAIL"} '
        f'({"at least one" if any_pass else "no"} promotion cell met all three criteria)')
    if any_pass:
        gmin = min((s['G'] for s in stats if s and s['cell'] in PROMOTION_CELLS), default=0)
        log('')
        log(f'POWER WARNING (spec, mandatory): this pass rests on G={gmin} review')
        log('clusters. The spec pre-declared that "a marginal pass is weak evidence')
        log('and will be labeled as such". Treat it as such. Per the spec, a pass')
        log('leads ONLY to a phase-2 incubator-swing spec requiring separate')
        log('approval -- never straight to live.')
    log('=' * 78)


# ---------------------------------------------------------------------------
def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--smoke', action='store_true',
                    help='2 consecutive reviews only (the 2 most recent usable); '
                         'writes amfi_band_results_smoke.txt and issues NO verdict')
    args = ap.parse_args()

    man, lists = load_reviews()

    # Which transitions are even candidates? Transition i needs list i-1 and i.
    all_tr = list(range(1, len(man)))
    # Panel window: earliest candidate publication month minus a buffer for the
    # E-60d drift window, through the end of the panel.
    first_pub = pd.Timestamp(year=int(man.iloc[1]['pub_year']),
                             month=int(man.iloc[1]['pub_month']), day=1)
    lo = first_pub - pd.Timedelta(days=140)

    if args.smoke:
        # Pick the 2 most recent transitions whose full hold window can close
        # inside the panel. Determined from the panel calendar, not assumed.
        cal = [d for d, _ in panel_files_in_range()]
        if not cal:
            sys.exit(f'HALTED: no bhavcopy files under {PANEL_DIR}.')
        cal = pd.DatetimeIndex(sorted(cal))
        usable = []
        for i in all_tr:
            r = man.iloc[i]
            sel = np.where((cal.year == int(r['pub_year'])) & (cal.month == int(r['pub_month'])))[0]
            if len(sel) < FALLBACK_TRADING_DAY:
                continue
            e = int(sel[FALLBACK_TRADING_DAY - 1])
            if e + 1 + HOLD_DAYS < len(cal):
                usable.append(i)
        if len(usable) < 2:
            sys.exit(f'HALTED: fewer than 2 transitions have a complete hold window '
                     f'inside the panel (found {len(usable)}).')
        transitions = usable[-2:]
        lo = pd.Timestamp(year=int(man.iloc[transitions[0]]['pub_year']),
                          month=int(man.iloc[transitions[0]]['pub_month']),
                          day=1) - pd.Timedelta(days=140)
    else:
        transitions = all_tr

    panel = load_panel(lo=lo)
    corp = load_corp_actions()
    halt_on_unresolved_nan_factors(panel, corp)
    panel = apply_corp_action_adjustments(panel, corp)
    P = Panel(panel)

    print_header(args.smoke, len(man), len(transitions))
    if args.smoke:
        log('SMOKE SELECTION: the 2 most recent transitions with a complete '
            f'{HOLD_DAYS}-day hold window inside the panel:')
        for i in transitions:
            log(f'  {man.iloc[i - 1]["period"]} -> {man.iloc[i]["period"]} '
                f'(published {int(man.iloc[i]["pub_month"]):02d}/{int(man.iloc[i]["pub_year"])})')
        log('')

    ev, diag = build_events(man, lists, P, transitions)
    print_diagnostics(diag)

    if ev.empty or 'ar_net' not in ev.columns or ev['ar_net'].notna().sum() == 0:
        log('NO USABLE EVENTS -- nothing to report. Check the drop accounting above.')
        out = OUT_DIR / ('amfi_band_results_smoke.txt' if args.smoke else 'amfi_band_results.txt')
        flush_out(out)
        log(f'\nWrote {out}')
        return

    log(f'--- CELL COUNTS (crossings found / usable after price join) ---')
    for c in PROMOTION_CELLS + DEMOTION_CELLS:
        s = ev[ev['cell'] == c]
        log(f'  {c:<22} {len(s):>5} crossings, {int(s["ar_net"].notna().sum()):>5} usable')
    log('')

    stats = [cell_block(ev, c, True) for c in PROMOTION_CELLS]
    for c in DEMOTION_CELLS:
        cell_block(ev, c, False)

    print_verdict(stats, ev, args.smoke)

    suffix = '_smoke' if args.smoke else ''
    ev_out = OUT_DIR / f'amfi_band_events{suffix}.csv'
    ev.drop(columns=[c for c in ('e_pos', 'entry_pos', 'exit_pos') if c in ev.columns]) \
      .to_csv(ev_out, index=False)
    out = OUT_DIR / f'amfi_band_results{suffix}.txt'
    log('')
    log(f'Per-event detail (every event, including dropped ones): {ev_out}')
    flush_out(out)
    print(f'Wrote {out}')


if __name__ == '__main__':
    main()
