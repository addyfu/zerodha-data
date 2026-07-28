"""Bulk-Deal Buyer Persistence -- FROZEN pre-registered study.

Spec (frozen, read this first, do not deviate without a spec amendment):
    docs/superpowers/specs/2026-07-29-bulk-buyer-persistence-design.md

HYPOTHESIS: buyer skill persists. NSE discloses every bulk deal (>0.5% of
shares) with the buyer's NAME at end of day. If institutions/individuals whose
past bulk purchases were followed by positive abnormal returns keep doing
better than average, then following ONLY the proven buyers at T+1 captures
part of that. Information-asymmetry story, not forced-flow. The relabel risk
(this is just generic "any bulk buy" drift) is guarded by a MANDATORY CONTROL
ARM: verdict criterion 3.

DATA
    data/bulk_deals/bulk_*.csv   232k rows, 2005-2026. Columns (headers carry
        stray spaces -- stripped on load): Date, Symbol, Security Name,
        Client Name, Buy / Sell, Quantity Traded,
        Trade Price / Wght. Avg. Price, Remarks.
        BUY rows drive events; BOTH sides drive the same-day round-trip
        exclusion.
    data/bhavcopy_full/          price panel, loaded with the corp-action
        adjustment + EW-universe conventions of delivery_factor_study.py /
        amfi_band_study.py. THE PANEL, NOT THE DEAL FILE, BOUNDS THE
        MEASURABLE ERA -- outcomes exist only from 2019-10 on. Deals
        2005..2019-09 have no in-repo prices and are NOT used at all.
    data/corp_actions_adjustments.csv  back-adjustment factors.
    kite/research/bulk_buyer_aliases.csv  the EXPLICIT alias table (reviewer
        reads it in full; it is the only place two disclosed strings merge).

EVENT-TIME STRUCTURE (point-in-time, expanding)
    WARMUP  : track records accumulate from 2019-10-01.
    TEST ERA: events from 2022-01-01 to panel end. Events before 2022-01-01
              feed track records ONLY, never statistics (asserted at runtime).

ENTITY RESOLUTION (deterministic only -- NO fuzzy matching anywhere)
    normalize_entity() does, in order:
      1. NFKD -> ASCII, uppercase, strip.
      2. TRUNCATE at the first account-suffix marker: a standalone A/C, A\\C,
         A.C or AC token. Everything from that token onward is dropped
         ("HDFC MUTUAL FUND A/C HDFC SMALL CAP FUND" -> "HDFC MUTUAL FUND").
         Verified on the data: all 8 standalone bare-"AC" occurrences in the
         2019-10+ BUY set are account markers, none is part of a real name.
      3. "&" -> " AND ".
      4. Every non-alphanumeric run -> single space; collapse whitespace.
      5. Repeatedly strip a TRAILING suffix token, from this DECLARED list
         and no other:  LIMITED  LTD  PRIVATE  PVT  LLP  HUF
         TRAILING ONLY (a mid-string "PRIVATE" is left alone), and never down
         to an empty string. Tokens considered and NOT included, because
         "when in doubt DON'T strip": INC, CORP, CO, COMPANY, PTE, PLC, LLC,
         TRUST, FUND, SECURITIES, AND, THE, INDIA, ODI. Notably INC/PTE/LLC
         are real corporate suffixes but they also distinguish separately
         disclosed foreign books, so they stay.
    Then, and only then, the alias table is applied (exact dict lookup on the
    normalized string). Alias chains are rejected at load time.

INTERPRETATION CHOICES (the spec's one-liners do not pin these down; each is
flagged here so the reviewer can overrule before the verdict run)
    IC-1  LIQUIDITY GATE TIMING. Spec says "liquidity gate at entry: symbol in
          panel, turnover >= Rs 2 crore, close >= Rs 20". Evaluating turnover
          and close on the ENTRY day (E+1) would use data not known until the
          E+1 close, i.e. after the E+1 open fill -- lookahead. The gate is
          therefore evaluated on the DEAL day E's bhavcopy row (the last data
          available before the fill). Identical for both arms.
    IC-2  "20d ABNORMAL RETURN" IS THE NET ONE, EVERYWHERE. The track-record
          hit rate and the verdict quantity use the SAME definition:
          ar_net = (net-of-cost stock return, E+1 open -> E+21 open)
                   - (frictionless EW universe return over the same span).
          Using gross for the record and net for the verdict would be two
          different definitions of one spec term. ar_gross is reported
          alongside for information only.
    IC-3  QUARTILE THRESHOLD RECOMPUTED PER ISO WEEK (the spec permits "per
          event date or per week"). The threshold for an event on date t is
          computed from deals whose outcome windows completed strictly before
          the MONDAY of t's ISO week -- i.e. strictly LESS information than a
          per-event threshold would use, so the per-week relaxation cannot
          leak. FLAGGED, as instructed. The buyer's own deal count and own hit
          rate are still evaluated at t exactly, not at the week start.
    IC-4  "COMPLETED BEFORE t" IS STRICT: a prior deal counts only if its exit
          date (E+21) is < t. A deal exiting ON t is discarded even though its
          exit open precedes the next-day entry -- the strict reading, and the
          conservative one.
    IC-5  SAME-DAY-BOTH-SIDES EXCLUSION APPLIES TO TRACK RECORDS TOO, not only
          to events. An entity that bought and sold the same symbol on the
          same day held nothing for 20 days; scoring it on a 20-day outcome
          would manufacture a track record out of HFT churn (this is most of
          the top-of-table by deal count -- Graviton, HRTI, QE, NK). Both
          removal counts are reported separately.
    IC-6  ONE EVENT PER (canonical entity, symbol, deal date). NSE sometimes
          splits one client-day into multiple disclosed tranches (95 such keys
          in the 2019-10+ BUY set). Tranches are deduped AFTER canonicalization
          so a split disclosure is not five identical outcomes.
    IC-7  CONTROL ARM IS A SUPERSET of the top-quartile arm ("ALL bulk-deal
          BUYs passing the same gates, undifferentiated by buyer" -- read
          literally). The C3 difference is therefore estimated by stacking the
          two arms and regressing ar_net on a top-quartile dummy with
          week-clustered SEs; qualifying events appear in both stacks, exactly
          as the literal reading implies. The cleaner non-overlapping
          comparison (top-quartile vs everything-else) is printed alongside as
          INFORMATION ONLY and carries no verdict weight.

SIGNAL (frozen)
    A buyer QUALIFIES at event date t iff
      (a) >= 15 prior BUY deals with measurable outcomes, deal date >= 2019-10,
          outcome window complete strictly before t, AND
      (b) trailing hit rate (fraction of those prior deals with ar_net > 0) is
          in the TOP QUARTILE (>= the 75th percentile, ties included) of all
          buyers qualified under (a) as of the week start.
    Event: such a buyer's BUY bulk deal. Entry next trading day's OPEN, hold 20
    trading days, exit at open. Liquidity gate: symbol in panel, TURNOVER_LACS
    >= 200, adjusted close >= Rs 20 (see IC-1 for timing).
    Exclusion: entity on BOTH sides of the same symbol-day (see IC-5).
    Control arm: ALL gated BUY events, undifferentiated (see IC-7).

COSTS
    Rs 20,000 notional per event, 0.2%/side slippage applied to the fill price,
    then
        zerodha_charges.calculate_charges(buy_v, sell_v, is_intraday=False)
        ['total']
    NEVER sum(charges.values()) -- that dict already contains 'total'; summing
    everything double-counts (the exact bug fixed repo-wide 2026-07-26/27).

VERDICT (frozen, ALL must hold). Declared test count: 1 (the top-quartile arm).
    C1  top-quartile mean net 20d AR > 0 in BOTH era halves
        (2022-01..2023-12 and 2024-01..panel end), each with >= 40 events.
    C2  pooled cluster-robust t >= +2.0, clustered by ISO WEEK OF THE DEAL.
    C3  RELABEL GUARD: (top-quartile - control) pooled difference > 0 with
        cluster-robust t(difference) >= +1.5. If C1/C2 pass and C3 fails the
        verdict is "generic bulk-deal drift, buyer identity decorative" -- a
        FAIL for this spec.

CAVEATS (stated before results, per spec)
    - Warmup track records rest on ~2.3 years of deals; 15+ deals is a thin
      skill estimate. Stated, not patched.
    - Entity-resolution errors bias TOWARD the null (split entities dilute
      records) EXCEPT alias-table mistakes -- which is what the reviewer audit
      of bulk_buyer_aliases.csv and the top-50 table exists for.
    - The literature puts bulk-deal alpha PRE-disclosure (front-running); the
      retail-accessible T+1 residual is expected small. A null here is the
      literature's predicted outcome.

Usage:
    python kite/research/bulk_buyer_persistence.py --smoke   # 2024-01..2024-02
    python kite/research/bulk_buyer_persistence.py           # verdict run
"""
import argparse
import re
import sys
import unicodedata
from pathlib import Path

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))
from kite.config import zerodha_charges  # noqa: E402  (['total'] only -- see docstring)

BULK_DIR = ROOT / 'data' / 'bulk_deals'
BHAV_DIR = ROOT / 'data' / 'bhavcopy_full'
CORP_ACTIONS_PATH = ROOT / 'data' / 'corp_actions_adjustments.csv'
OUT_DIR = ROOT / 'kite' / 'research'
ALIAS_PATH = OUT_DIR / 'bulk_buyer_aliases.csv'

# ---------------------------------------------------------------------------
# Frozen constants
# ---------------------------------------------------------------------------
MIN_TURNOVER_LACS = 200.0        # Rs 2 crore
MIN_PRICE = 20.0                 # Rs 20 adjusted close
HOLD_DAYS = 20                   # E+1 open -> E+21 open
NOTIONAL = 20_000.0              # Rs 20k per event
SLIP = 0.002                     # 0.2% / side
CLIP = 0.25                      # +/-25% daily clip on BENCHMARK returns (brief R9)
MIN_PRIOR_DEALS = 15
TOP_QUARTILE_PCTL = 75.0

RECORD_START = pd.Timestamp('2019-10-01')   # track records accumulate from here
TEST_START = pd.Timestamp('2022-01-01')     # statistics from here
ERA_SPLIT = pd.Timestamp('2024-01-01')      # era half boundary
SMOKE_TEST_START = pd.Timestamp('2024-01-01')
SMOKE_TEST_END = pd.Timestamp('2024-02-29')

C1_MIN_EVENTS = 40
C2_MIN_T = 2.0
C3_MIN_T = 1.5

FNAME_DATE_RE = re.compile(r'sec_bhavdata_full_(\d{2})(\d{2})(\d{4})\.csv$', re.IGNORECASE)
BHAV_COLS = ['SYMBOL', 'SERIES', 'OPEN_PRICE', 'CLOSE_PRICE', 'TURNOVER_LACS']
DEAL_COLS = ['Date', 'Symbol', 'Security Name', 'Client Name', 'Buy / Sell',
             'Quantity Traded', 'Trade Price / Wght. Avg. Price', 'Remarks']

# Entity normalization -- DECLARED lists, see module docstring.
SUFFIX_TOKENS = ('LIMITED', 'LTD', 'PRIVATE', 'PVT', 'LLP', 'HUF')
ACCOUNT_MARKER_RE = re.compile(
    r'(?<![A-Z0-9])A\s*[/\\.]\s*C(?![A-Z0-9])'   # A/C, A\C, A.C, A / C
    r'|(?<![A-Z0-9])AC(?![A-Z0-9])'              # bare AC
)

_OUT_LINES = []


def log(msg=''):
    print(msg, flush=True)
    _OUT_LINES.append(str(msg))


def flush_out(path):
    path.write_text('\n'.join(_OUT_LINES) + '\n', encoding='utf-8')


def pct(x, nd=2):
    return 'n/a' if x is None or not np.isfinite(x) else f'{x * 100:+.{nd}f}%'


def num(x, nd=2):
    return 'n/a' if x is None or not np.isfinite(x) else f'{x:.{nd}f}'


# ===========================================================================
# 1. Entity resolution -- deterministic normalizer + explicit alias table
# ===========================================================================
def normalize_entity(name):
    """Deterministic only. See module docstring for the exact declared rules."""
    s = unicodedata.normalize('NFKD', str(name)).encode('ascii', 'ignore').decode('ascii')
    s = s.upper().strip()
    m = ACCOUNT_MARKER_RE.search(s)
    if m:
        s = s[:m.start()]
    s = s.replace('&', ' AND ')
    s = re.sub(r'[^A-Z0-9]+', ' ', s)
    s = re.sub(r'\s+', ' ', s).strip()
    toks = s.split()
    while len(toks) > 1 and toks[-1] in SUFFIX_TOKENS:
        toks.pop()
    return ' '.join(toks)


def load_alias_table(path=ALIAS_PATH):
    """Exact-match dict, applied AFTER normalization. Halts on malformed rows,
    self-maps, or alias chains (a canonical that is itself a variant)."""
    if not path.exists():
        sys.exit(f'HALTED: alias table {path} not found. It is a required, reviewer-audited '
                 f'input -- create it (may be header-only) before running.')
    df = pd.read_csv(path, comment='#', dtype=str).fillna('')
    need = ['normalized_variant', 'canonical_entity', 'rationale']
    missing = [c for c in need if c not in df.columns]
    if missing:
        sys.exit(f'HALTED: alias table missing columns {missing}. Required: {need}')
    df = df[need].copy()
    for c in need:
        df[c] = df[c].astype(str).str.strip()
    df = df[(df['normalized_variant'] != '') & (df['canonical_entity'] != '')]
    problems = []
    for _, r in df.iterrows():
        v, c = r['normalized_variant'], r['canonical_entity']
        if v != normalize_entity(v):
            problems.append(f'  normalized_variant is not in normalized form: {v!r} '
                            f'(normalizes to {normalize_entity(v)!r})')
        if c != normalize_entity(c):
            problems.append(f'  canonical_entity is not in normalized form: {c!r} '
                            f'(normalizes to {normalize_entity(c)!r})')
        if v == c:
            problems.append(f'  self-map: {v!r}')
        if not r['rationale']:
            problems.append(f'  missing rationale for {v!r}')
    if df['normalized_variant'].duplicated().any():
        dups = df.loc[df['normalized_variant'].duplicated(keep=False), 'normalized_variant'].tolist()
        problems.append(f'  duplicate normalized_variant rows: {sorted(set(dups))}')
    chains = set(df['canonical_entity']) & set(df['normalized_variant'])
    if chains:
        problems.append(f'  alias CHAIN (canonical is itself a variant): {sorted(chains)}')
    if problems:
        log('HALT: alias table is malformed:')
        for p in problems:
            log(p)
        sys.exit(f'HALTED: {len(problems)} problem(s) in {path}.')
    return df


# ===========================================================================
# 2. Price panel -- conventions copied from delivery_factor_study.py
# ===========================================================================
def load_panel(data_dir=BHAV_DIR):
    files = sorted(data_dir.glob('sec_bhavdata_full_*.csv'))
    frames, bad_files = [], []
    for f in files:
        m = FNAME_DATE_RE.search(f.name)
        if not m:
            bad_files.append((f.name, 'filename does not match sec_bhavdata_full_DDMMYYYY.csv'))
            continue
        file_date = pd.Timestamp(year=int(m.group(3)), month=int(m.group(2)), day=int(m.group(1)))
        try:
            df = pd.read_csv(f, dtype=str, encoding='utf-8')
        except Exception as e:
            bad_files.append((f.name, f'unreadable ({type(e).__name__})'))
            continue
        df.columns = df.columns.str.strip()
        missing = [c for c in BHAV_COLS if c not in df.columns]
        if missing:
            bad_files.append((f.name, f'missing columns {missing}'))
            continue
        df = df[BHAV_COLS].copy()
        for c in BHAV_COLS:
            df[c] = df[c].astype(str).str.strip()
        df = df[df['SERIES'] == 'EQ']
        if df.empty:
            continue
        df = df.copy()
        df['date'] = file_date
        for c in ['OPEN_PRICE', 'CLOSE_PRICE', 'TURNOVER_LACS']:
            df[c] = pd.to_numeric(df[c], errors='coerce')
        frames.append(df.rename(columns={'SYMBOL': 'symbol', 'OPEN_PRICE': 'open',
                                          'CLOSE_PRICE': 'close',
                                          'TURNOVER_LACS': 'turnover_lacs'})
                      [['symbol', 'date', 'open', 'close', 'turnover_lacs']])
    if not frames:
        sys.exit(f'HALTED: no usable files under {data_dir}. Run fetch_bhavcopy_full.py first.')
    panel = pd.concat(frames, ignore_index=True)
    panel = panel.drop_duplicates(subset=['symbol', 'date'], keep='last')
    panel = panel.sort_values(['symbol', 'date']).reset_index(drop=True)
    log(f'Panel: {len(files)} files ({len(bad_files)} unusable), {len(panel)} EQ stock-days, '
        f'{panel.symbol.nunique()} symbols, {panel.date.min().date()} -> {panel.date.max().date()}')
    if bad_files:
        log('  !! UNUSABLE BHAVCOPY FILES -- these trading days are MISSING from the panel, which')
        log('     drops any deal dated on them and shortens nothing else (windows count PANEL days):')
        for name, why in bad_files:
            log(f'       {name}: {why}')
        log('     This is a data-collection defect upstream of this study, reported not patched.')
    return panel


def load_corp_actions(path=CORP_ACTIONS_PATH):
    if not path.exists():
        sys.exit(f'HALTED: {path} not found. Run build_corp_actions.py first.')
    df = pd.read_csv(path)
    df['ex_date'] = pd.to_datetime(df['ex_date'])
    return df


def halt_on_unresolved_nan_factors(panel, corp_actions):
    """Same HALT rule as delivery_factor_study.py: an unparseable split/bonus
    factor that touches a date we actually price is fatal, not a warning."""
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
        sys.exit(f'HALTED: {len(offenders)} unresolved corp-action factor(s) affect the panel.')


def apply_corp_action_adjustments(panel, corp_actions):
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
    panel['adj_open'] = panel['open'] * mult
    panel['adj_close'] = panel['close'] * mult
    log(f'Corp-action adjustment: {int((mult != 1.0).sum())} stock-day rows scaled, '
        f'{valid["symbol"].nunique()} symbols with >=1 valid action.')
    return panel


class Panel:
    """Wide adj-open / gate matrices + the prefix-compounded EW benchmark.

    The benchmark is OPEN-to-OPEN because the event leg is open-to-open
    (entry open -> exit open); mixing in close-to-close would silently offset
    every abnormal return by one overnight gap (the documented convention in
    amfi_band_study.py). Frictionless by design -- a deliberately generous
    counterfactual.
    """

    def __init__(self, panel):
        self.open_wide = panel.pivot_table(index='date', columns='symbol',
                                            values='adj_open', aggfunc='last').sort_index()
        self.open_arr = self.open_wide.to_numpy(dtype=float)
        # The gate is built from NUMERIC pivots, deliberately NOT from a boolean
        # pivot. A boolean pivot_table comes back as OBJECT dtype, and
        # DataFrame.to_numpy(dtype=bool, na_value=False) does NOT honour
        # na_value on object dtype -- every absent (date, symbol) cell becomes
        # bool(nan) == True, i.e. a stock that did not trade in EQ that day
        # would silently PASS the liquidity gate. Verified on pandas 2.3.3.
        # (The same idiom appears in amfi_band_study.py, where it is harmless
        # because the flag is only used to mask an already-NaN return matrix.
        # Here it would be fatal, so it is done differently.)
        close_wide = panel.pivot_table(index='date', columns='symbol', values='adj_close',
                                        aggfunc='last').reindex_like(self.open_wide)
        turn_wide = panel.pivot_table(index='date', columns='symbol', values='turnover_lacs',
                                       aggfunc='last').reindex_like(self.open_wide)
        with np.errstate(invalid='ignore'):
            self.gate_arr = ((turn_wide.to_numpy(dtype=float) >= MIN_TURNOVER_LACS)
                             & (close_wide.to_numpy(dtype=float) >= MIN_PRICE)
                             & np.isfinite(self.open_arr))
        self.dates = pd.DatetimeIndex(self.open_wide.index)
        self._dvals = self.dates.values
        self.col_of = {s: i for i, s in enumerate(self.open_wide.columns)}

        raw = self.open_wide / self.open_wide.shift(1) - 1.0
        prev_gate = np.vstack([np.zeros((1, self.gate_arr.shape[1]), dtype=bool), self.gate_arr[:-1]])
        raw = raw.where(pd.DataFrame(self.gate_arr & prev_gate, index=self.open_wide.index,
                                     columns=self.open_wide.columns))
        n_valid = int(raw.notna().sum().sum())
        n_clip = int((raw.abs() > CLIP).sum().sum())
        self.clip_frac = (n_clip / n_valid) if n_valid else 0.0
        u = raw.clip(-CLIP, CLIP).mean(axis=1, skipna=True).fillna(0.0)
        self.P = (1.0 + u.values).cumprod()
        breadth = raw.notna().sum(axis=1)
        log(f'EW benchmark (open-to-open, frictionless): {n_valid} gated stock-day returns, '
            f'{n_clip} ({100 * self.clip_frac:.4f}%) hit the +/-{CLIP * 100:.0f}% clip; '
            f'median daily universe breadth = {int(breadth.median())} names.')

    def pos_exact(self, ts_values):
        """Index of each timestamp in the trading calendar, -1 if not a panel day."""
        p = np.searchsorted(self._dvals, ts_values, side='left')
        ok = (p < len(self._dvals))
        p_safe = np.where(ok, p, 0)
        exact = ok & (self._dvals[p_safe] == ts_values)
        return np.where(exact, p, -1)


def prepare_panel():
    panel = load_panel()
    corp = load_corp_actions()
    halt_on_unresolved_nan_factors(panel, corp)
    panel = apply_corp_action_adjustments(panel, corp)
    return Panel(panel)


# ===========================================================================
# 3. Bulk deals -- load, canonicalize, dedupe, both-sides exclusion
# ===========================================================================
def load_deals(alias_df):
    files = sorted(BULK_DIR.glob('bulk_*.csv'))
    if not files:
        sys.exit(f'HALTED: no bulk_*.csv under {BULK_DIR}.')
    frames = []
    for f in files:
        df = pd.read_csv(f, dtype=str)
        df.columns = df.columns.str.strip()          # headers carry stray spaces
        missing = [c for c in DEAL_COLS if c not in df.columns]
        if missing:
            sys.exit(f'HALTED: {f.name} missing columns {missing}. Expected schema: {DEAL_COLS}')
        df = df[DEAL_COLS].copy()
        for c in DEAL_COLS:
            df[c] = df[c].astype(str).str.strip()
        frames.append(df)
    d = pd.concat(frames, ignore_index=True)
    n_raw_all = len(d)

    d['dt'] = pd.to_datetime(d['Date'], format='%d-%b-%Y', errors='coerce')
    bad = d['dt'].isna()
    if bad.any():                                     # one retry with the generic parser
        d.loc[bad, 'dt'] = pd.to_datetime(d.loc[bad, 'Date'], errors='coerce', dayfirst=True)
    still_bad = int(d['dt'].isna().sum())
    if still_bad:
        sample = d.loc[d['dt'].isna(), 'Date'].head(5).tolist()
        sys.exit(f'HALTED: {still_bad} bulk-deal rows have an unparseable Date, e.g. {sample}.')

    d['side'] = d['Buy / Sell'].str.upper().str.strip()
    bad_side = ~d['side'].isin(['BUY', 'SELL'])
    n_bad_side = int(bad_side.sum())
    d = d[~bad_side].copy()

    d['symbol'] = d['Symbol'].str.upper()
    d['entity_norm'] = d['Client Name'].map(normalize_entity)
    alias_map = dict(zip(alias_df['normalized_variant'], alias_df['canonical_entity']))
    d['entity'] = d['entity_norm'].map(lambda s: alias_map.get(s, s))
    d['alias_hit'] = d['entity_norm'].isin(alias_map)

    empty = d['entity'] == ''
    n_empty = int(empty.sum())
    d = d[~empty].copy()

    log(f'Bulk deals: {n_raw_all} raw rows from {len(files)} files, '
        f'{d["dt"].min().date()} -> {d["dt"].max().date()}; '
        f'dropped {n_bad_side} row(s) with an unrecognised Buy/Sell value, '
        f'{n_empty} row(s) whose Client Name normalized to empty.')
    log(f'  raw client-name strings: {d["Client Name"].nunique()}  ->  '
        f'normalized: {d["entity_norm"].nunique()}  ->  after alias table: {d["entity"].nunique()}')
    return d, alias_map


def both_sides_keys(deals):
    """(entity, symbol, date) triples where the SAME canonical entity is on
    both sides of the same symbol-day -- intraday round-trip, not a position."""
    sides = deals.groupby(['entity', 'symbol', 'dt'])['side'].agg(lambda s: set(s))
    both = sides[sides.map(lambda s: 'BUY' in s and 'SELL' in s)]
    return set(both.index)


# ===========================================================================
# 4. Outcomes -- 20d net abnormal return per BUY deal
# ===========================================================================
def compute_outcomes(buys, P):
    """One row per (entity, symbol, deal date). Adds ar_net / ar_gross /
    completion date, or a drop_reason. Vectorized except the fee call."""
    n = len(buys)
    dtv = buys['dt'].to_numpy()
    e_pos = P.pos_exact(dtv)
    col = buys['symbol'].map(P.col_of).to_numpy()
    in_panel = np.array([c == c for c in col])              # not-NaN test on object array
    col_safe = np.where(in_panel, np.nan_to_num(col.astype(float), nan=0.0), 0.0).astype(int)

    reason = np.full(n, '', dtype=object)
    reason[~in_panel] = 'symbol absent from bhavcopy EQ panel'
    m = (reason == '') & (e_pos < 0)
    reason[m] = 'deal date is not a panel trading day'

    entry_pos = np.where(e_pos >= 0, e_pos + 1, -1)
    exit_pos = np.where(e_pos >= 0, e_pos + 1 + HOLD_DAYS, -1)
    m = (reason == '') & (exit_pos >= len(P.dates))
    reason[m] = 'outcome window extends past the end of the panel'

    ok = reason == ''
    ep = np.where(ok, e_pos, 0)
    gate_ok = P.gate_arr[ep, col_safe]
    m = ok & ~gate_ok
    reason[m] = 'liquidity gate failed on the deal day (turnover < Rs 2cr or adj close < Rs 20)'

    ok = reason == ''
    ip = np.where(ok, entry_pos, 0)
    xp = np.where(ok, exit_pos, 0)
    o_in = np.where(ok, P.open_arr[ip, col_safe], np.nan)
    o_out = np.where(ok, P.open_arr[xp, col_safe], np.nan)
    m = ok & ~(np.isfinite(o_in) & np.isfinite(o_out) & (o_in > 0) & (o_out > 0))
    reason[m] = 'no usable open price on the entry and/or exit day'

    ok = reason == ''
    buy_px = np.where(ok, o_in * (1 + SLIP), np.nan)
    qty = np.where(ok, np.floor(NOTIONAL / np.where(buy_px > 0, buy_px, np.nan)), 0)
    m = ok & ~(qty >= 1)
    reason[m] = f'Rs {NOTIONAL:,.0f} notional buys < 1 share'

    ok = reason == ''
    sell_px = o_out * (1 - SLIP)
    buy_v = qty * buy_px
    sell_v = qty * sell_px
    fees = np.full(n, np.nan)
    idx = np.where(ok)[0]
    for i in idx:
        fees[i] = zerodha_charges.calculate_charges(float(buy_v[i]), float(sell_v[i]),
                                                    is_intraday=False)['total']
    gross_ret = np.where(ok, o_out / o_in - 1.0, np.nan)
    net_ret = np.where(ok, (sell_v - fees) / buy_v - 1.0, np.nan)
    bench = np.where(ok, P.P[np.where(ok, exit_pos, 0)] / P.P[np.where(ok, entry_pos, 0)] - 1.0, np.nan)

    out = buys.copy()
    out['e_pos'] = e_pos
    out['entry_pos'] = entry_pos
    out['exit_pos'] = exit_pos
    out['drop_reason'] = reason
    out['usable'] = ok
    out['gross_ret'] = gross_ret
    out['net_ret'] = net_ret
    out['cost_frac'] = gross_ret - net_ret
    out['bench_ret'] = bench
    out['ar_gross'] = gross_ret - bench
    out['ar_net'] = net_ret - bench
    out['completion_date'] = pd.to_datetime(
        np.where(ok, P._dvals[np.where(ok, exit_pos, 0)], np.datetime64('NaT')))
    return out


# ===========================================================================
# 5. Track records + point-in-time qualification
# ===========================================================================
class TrackRecords:
    """entity -> (completion dates ascending, cumulative hit counts).

    A deal enters a buyer's record only once its outcome window has completed;
    lookups take a timestamp and count only records completing STRICTLY before
    it (IC-4). Nothing here can see a deal's own outcome: an event on date t
    completes at t+21 trading days.
    """

    def __init__(self, usable):
        self.rec = {}
        for ent, g in usable.groupby('entity', sort=False):
            g = g.sort_values('completion_date', kind='mergesort')
            cd = g['completion_date'].to_numpy()
            hits = np.cumsum((g['ar_net'].to_numpy() > 0).astype(np.int64))
            self.rec[ent] = (cd, hits)
        # entities that ever reach MIN_PRIOR_DEALS, and when
        self.ready_at = {e: cd[MIN_PRIOR_DEALS - 1]
                         for e, (cd, _) in self.rec.items() if len(cd) >= MIN_PRIOR_DEALS}

    def state(self, entity, ts):
        """(n_prior, hit_rate) using only outcomes completed strictly before ts."""
        r = self.rec.get(entity)
        if r is None:
            return 0, np.nan
        cd, hits = r
        k = int(np.searchsorted(cd, np.datetime64(ts), side='left'))
        if k == 0:
            return 0, np.nan
        return k, float(hits[k - 1]) / k

    def qualified_hit_rates(self, ts):
        """Hit rates of every buyer with >= MIN_PRIOR_DEALS completed before ts."""
        t64 = np.datetime64(ts)
        out = []
        for e, ready in self.ready_at.items():
            if ready >= t64:                      # cannot have 15 completed before ts
                continue
            cd, hits = self.rec[e]
            k = int(np.searchsorted(cd, t64, side='left'))
            if k >= MIN_PRIOR_DEALS:
                out.append(float(hits[k - 1]) / k)
        return out


def point_in_time_wall_check(ev, usable, sample=300, seed=0):
    """Independent brute-force recomputation of the qualification state for a
    sample of classified events, straight from the deal table. Exists so the
    reviewer does not have to take the searchsorted machinery on trust: if any
    event's n_prior/hit_rate disagrees with a naive filter on
    (same entity) AND (completion_date < event date), this HALTS."""
    if len(ev) == 0:
        return
    rng = np.random.default_rng(seed)
    idx = rng.choice(len(ev), size=min(sample, len(ev)), replace=False)
    bad = []
    for i in idx:
        r = ev.iloc[int(i)]
        prior = usable[(usable['entity'] == r['entity']) & (usable['completion_date'] < r['dt'])]
        k = len(prior)
        hr = float((prior['ar_net'] > 0).mean()) if k else np.nan
        ok_k = (k == int(r['n_prior']))
        ok_h = ((not np.isfinite(hr)) and (not np.isfinite(r['hit_rate']))) or \
               (np.isfinite(hr) and np.isfinite(r['hit_rate']) and abs(hr - r['hit_rate']) < 1e-12)
        # the event's own deal must never be inside its own prior set
        own = ((prior['symbol'] == r['symbol']) & (prior['dt'] == r['dt'])).any()
        if not (ok_k and ok_h) or own:
            bad.append((r['entity'], r['dt'], k, int(r['n_prior']), hr, r['hit_rate'], bool(own)))
    log(f'POINT-IN-TIME WALL CHECK: {len(idx)} sampled events re-derived by brute force from the '
        f'deal table -> {len(bad)} mismatch(es).')
    if bad:
        for b in bad[:20]:
            log(f'    MISMATCH {b}')
        sys.exit(f'HALTED: point-in-time wall check failed on {len(bad)} sampled event(s). '
                 f'Track-record lookups are not point-in-time.')


def iso_week_start(ts):
    """Monday 00:00 of ts's ISO week."""
    ts = pd.Timestamp(ts).normalize()
    return ts - pd.Timedelta(days=int(ts.isoweekday()) - 1)


def iso_week_key(ts):
    y, w, _ = pd.Timestamp(ts).isocalendar()
    return f'{int(y)}-W{int(w):02d}'


def build_week_thresholds(records, event_dates):
    """IC-3: one top-quartile threshold per ISO week, computed from outcomes
    completed strictly before that week's Monday (strictly less information
    than a per-event threshold -- cannot leak)."""
    thr, nqual = {}, {}
    for ws in sorted({iso_week_start(t) for t in event_dates}):
        hrs = records.qualified_hit_rates(ws)
        nqual[ws] = len(hrs)
        thr[ws] = float(np.percentile(hrs, TOP_QUARTILE_PCTL)) if hrs else np.nan
    return thr, nqual


def classify_events(test_events, records, thr, nqual):
    ev = test_events.copy()
    n_prior, hit_rate, week_thr, n_qual_week = [], [], [], []
    for t, ent in zip(ev['dt'], ev['entity']):
        k, hr = records.state(ent, t)
        ws = iso_week_start(t)
        n_prior.append(k)
        hit_rate.append(hr)
        week_thr.append(thr.get(ws, np.nan))
        n_qual_week.append(nqual.get(ws, 0))
    ev['n_prior'] = n_prior
    ev['hit_rate'] = hit_rate
    ev['week_threshold'] = week_thr
    ev['n_qualified_that_week'] = n_qual_week
    ev['qualified'] = ev['n_prior'] >= MIN_PRIOR_DEALS
    ev['top_quartile'] = (ev['qualified'] & ev['week_threshold'].notna()
                          & (ev['hit_rate'] >= ev['week_threshold']))
    ev['week'] = ev['dt'].map(iso_week_key)
    ev['era'] = np.where(ev['dt'] < ERA_SPLIT, 'A 2022-01..2023-12', 'B 2024-01..panel end')
    return ev


# ===========================================================================
# 6. Statistics -- one-way cluster-robust (Liang-Zeger), k=1 and k=2
# ===========================================================================
def cluster_t(x, clusters):
    """One-way cluster-robust t for the mean of x. Same implementation as
    kite/research/amfi_band_study.py. Returns (mean, se, t, N, G)."""
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
    c = (g / (g - 1.0)) * ((n - 1.0) / (n - 1.0))   # k=1 -> second factor is 1
    var = c * meat / (n * n)
    se = float(np.sqrt(var)) if var > 0 else np.nan
    t = (m / se) if (se and np.isfinite(se) and se > 0) else np.nan
    return m, se, t, n, g


def cluster_diff_t(y, d, clusters):
    """Cluster-robust OLS of y on [1, d]; returns (beta_d, se, t, N, G).
    beta_d is exactly mean(y|d=1) - mean(y|d=0). Same Liang-Zeger sandwich as
    cluster_t, extended to k=2 (finite-sample factor G/(G-1) * (N-1)/(N-k))."""
    y = np.asarray(y, dtype=float)
    d = np.asarray(d, dtype=float)
    cl = np.asarray(clusters, dtype=object)
    keep = np.isfinite(y) & np.isfinite(d)
    y, d, cl = y[keep], d[keep], cl[keep]
    n = len(y)
    if n < 3 or len(np.unique(d)) < 2:
        return np.nan, np.nan, np.nan, n, len(set(cl))
    X = np.column_stack([np.ones(n), d])
    XtX = X.T @ X
    try:
        XtX_inv = np.linalg.inv(XtX)
    except np.linalg.LinAlgError:
        return np.nan, np.nan, np.nan, n, len(set(cl))
    beta = XtX_inv @ (X.T @ y)
    e = y - X @ beta
    sums = {}
    for gi, xi, ei in zip(cl, X, e):
        sums[gi] = sums.get(gi, np.zeros(2)) + xi * ei
    g = len(sums)
    if g < 2:
        return float(beta[1]), np.nan, np.nan, n, g
    meat = np.zeros((2, 2))
    for v in sums.values():
        meat += np.outer(v, v)
    c = (g / (g - 1.0)) * ((n - 1.0) / (n - 2.0))
    V = c * (XtX_inv @ meat @ XtX_inv)
    se = float(np.sqrt(V[1, 1])) if V[1, 1] > 0 else np.nan
    t = (float(beta[1]) / se) if (se and np.isfinite(se) and se > 0) else np.nan
    return float(beta[1]), se, t, n, g


def describe(v):
    v = np.asarray(v, dtype=float)
    v = v[np.isfinite(v)]
    if len(v) == 0:
        return dict(n=0, mean=np.nan, median=np.nan, std=np.nan, hit=np.nan)
    return dict(n=len(v), mean=float(v.mean()), median=float(np.median(v)),
                std=float(v.std(ddof=1)) if len(v) > 1 else np.nan,
                hit=float((v > 0).mean()))


# ===========================================================================
# 7. Reporting
# ===========================================================================
def print_header(smoke, alias_df):
    log('=' * 100)
    log('BULK-DEAL BUYER PERSISTENCE -- FROZEN RULES (stated before any result below was computed)')
    log('=' * 100)
    log('Spec      : docs/superpowers/specs/2026-07-29-bulk-buyer-persistence-design.md')
    log(f'Mode      : {"SMOKE (2 test-era months) -- NO VERDICT, NO EVIDENTIAL WEIGHT" if smoke else "FULL VERDICT RUN"}')
    log('')
    log('Entity    : deterministic normalizer only (uppercase; truncate at a standalone A/C|A\\C|A.C|AC')
    log('            account marker; & -> AND; punctuation -> space; strip TRAILING tokens from the')
    log(f'            declared list {list(SUFFIX_TOKENS)}), then an EXPLICIT alias')
    log(f'            table ({ALIAS_PATH.name}, {len(alias_df)} rows) applied AFTER normalization.')
    log('            NO fuzzy matching anywhere.')
    log('Records   : buyer track records accumulate from 2019-10-01. Outcome of a BUY deal =')
    log(f'            {HOLD_DAYS}d NET abnormal return, E+1 open -> E+{HOLD_DAYS + 1} open, vs the EW universe over')
    log('            the same span (IC-2). Computable only when the whole window fits in the panel.')
    log(f'Qualify   : at event date t, buyer needs >= {MIN_PRIOR_DEALS} prior deals whose outcome windows')
    log('            COMPLETED STRICTLY BEFORE t (IC-4), and a trailing hit rate at or above the')
    log(f'            {TOP_QUARTILE_PCTL:.0f}th percentile of all such qualified buyers, threshold recomputed per ISO')
    log('            week from information available at that week\'s Monday (IC-3, flagged).')
    log(f'Gate      : symbol in panel, TURNOVER_LACS >= {MIN_TURNOVER_LACS:.0f}, adjusted close >= Rs {MIN_PRICE:.0f},')
    log('            evaluated on the DEAL day E -- the last data before the E+1 open fill (IC-1).')
    log('Exclusion : entity on BOTH sides of the same symbol-day is dropped from events AND from')
    log('            track records (IC-5). One event per (entity, symbol, date) (IC-6).')
    log(f'Costs     : Rs {NOTIONAL:,.0f} notional, {SLIP * 100:.1f}%/side slippage on the fill price, then')
    log("            zerodha_charges.calculate_charges(buy_v, sell_v, is_intraday=False)['total']")
    log('            (never sum(.values()) -- that double-counts).')
    log('Benchmark : EW, daily-rebalanced, OPEN-to-OPEN, gated universe, returns clipped +/-25%,')
    log('            FRICTIONLESS (deliberately generous counterfactual).')
    log(f'Test era  : events from {TEST_START.date()} only. Earlier events feed records ONLY (asserted).')
    log('Arms      : TOP-QUARTILE (the one declared test) and CONTROL = all gated BUY events,')
    log('            undifferentiated -- a SUPERSET of the top-quartile arm (IC-7).')
    log('Verdict   : ALL of --')
    log(f'            C1  top-quartile mean net AR > 0 in BOTH era halves, each with >= {C1_MIN_EVENTS} events')
    log(f'            C2  pooled cluster-robust t >= +{C2_MIN_T:.1f}, clustered by ISO WEEK OF THE DEAL')
    log(f'            C3  (top-quartile - control) difference > 0 with cluster t >= +{C3_MIN_T:.1f}')
    log('            C1+C2 pass but C3 fail => "generic bulk-deal drift, buyer identity decorative"')
    log('            => FAIL for this spec. Declared test count: 1.')
    log('Caveats   : warmup records rest on ~2.3y of deals (thin); entity-resolution errors bias')
    log('            TOWARD the null except alias mistakes; the literature puts bulk-deal alpha')
    log('            PRE-disclosure, so a null here is the predicted outcome.')
    log('')


def print_alias_report(alias_df, deals, alias_map):
    log('=' * 100)
    log('ALIAS TABLE APPLICATION (reviewer audit material -- read every row of '
        f'{ALIAS_PATH.name})')
    log('=' * 100)
    used = deals.loc[deals['alias_hit'] & (deals['dt'] >= RECORD_START)]
    counts = used.groupby(['entity_norm', 'side']).size().unstack(fill_value=0)
    log(f'{len(alias_df)} alias rows loaded. Deal rows remapped (2019-10 onward, both sides): '
        f'{len(used)}.')
    log(f'{"normalized_variant":<62} {"->":2} {"canonical":<38} {"BUY":>5} {"SELL":>5}')
    n_dead = 0
    for _, r in alias_df.iterrows():
        v, c = r['normalized_variant'], r['canonical_entity']
        nb = int(counts.loc[v, 'BUY']) if (v in counts.index and 'BUY' in counts.columns) else 0
        ns = int(counts.loc[v, 'SELL']) if (v in counts.index and 'SELL' in counts.columns) else 0
        if nb + ns == 0:
            n_dead += 1
        log(f'{v[:62]:<62} {"->":2} {c[:38]:<38} {nb:>5} {ns:>5}')
    log(f'({n_dead} alias row(s) matched no deal in the 2019-10+ window -- harmless, kept for the '
        f'record.)')
    log('')


def print_top_entities(outcomes, deals, n=50, label='TOP-50 CANONICAL ENTITIES BY BUY-DEAL COUNT'):
    log('=' * 100)
    log(f'{label} (2019-10 onward, deduped per IC-6) -- reviewer audit for entity resolution')
    log('=' * 100)
    g = outcomes.groupby('entity')
    in_record = outcomes['usable'] & ~outcomes['both_sides']
    tbl = pd.DataFrame({
        'buy_deals': g.size(),
        'both_sides_excl': g['both_sides'].sum(),
        'raw_variants': g['Client Name'].nunique(),
        'in_records': outcomes.assign(ir=in_record).groupby('entity')['ir'].sum(),
    })
    tbl['full_sample_hit'] = (outcomes[in_record].groupby('entity')['ar_net']
                              .apply(lambda s: float((s > 0).mean())))
    tbl = tbl.sort_values('buy_deals', ascending=False).head(n)
    log(f'{"#":>3} {"canonical entity":<50} {"buys":>6} {"2sided":>7} {"recs":>6} {"vars":>5} '
        f'{"hit%":>6}  example raw name')
    for i, (ent, r) in enumerate(tbl.iterrows(), 1):
        ex = deals.loc[deals['entity'] == ent, 'Client Name'].iloc[0]
        h = f'{r["full_sample_hit"] * 100:5.1f}' if np.isfinite(r['full_sample_hit']) else '  n/a'
        log(f'{i:>3} {str(ent)[:50]:<50} {int(r["buy_deals"]):>6} '
            f'{int(r["both_sides_excl"]):>7} {int(r["in_records"]):>6} {int(r["raw_variants"]):>5} '
            f'{h:>6}  {ex[:42]}')
    log('  buys   = deduped BUY deals, 2019-10 onward     2sided = of those, excluded by IC-5')
    log('  recs   = deals that actually feed this entity\'s track record (gated, priced, not 2sided)')
    log('  vars   = distinct RAW disclosed strings folded into this canonical entity (entity-')
    log('           resolution audit: a big number here means the normalizer/alias table merged a lot)')
    log('  hit%   = FULL-SAMPLE hit rate over "recs" -- INFORMATION ONLY, not what the point-in-time')
    log('           qualifier uses. Printed so the reviewer can see whether the top of the table is')
    log('           HFT churn (huge buys, ~0 recs) or real position-takers.')
    log('')


def print_arm(label, sub, note=''):
    d = describe(sub['ar_net'])
    dg = describe(sub['ar_gross'])
    m, se, t, nn, gg = cluster_t(sub['ar_net'], sub['week'])
    log(f'-- {label}{note}')
    if d['n'] == 0:
        log('   no events with a computable outcome')
        log('')
        return dict(n=0, mean=np.nan, t=np.nan, G=0)
    log(f'   events N={d["n"]}   ISO-week clusters G={gg}   mean events/cluster='
        f'{d["n"] / max(gg, 1):.1f}   distinct entities={sub["entity"].nunique()}')
    log(f'   {HOLD_DAYS}d AR gross : mean {pct(dg["mean"])}  median {pct(dg["median"])}')
    log(f'   {HOLD_DAYS}d AR net   : mean {pct(d["mean"])}  median {pct(d["median"])}  '
        f'std {pct(d["std"])}  hit-rate {pct(d["hit"], 1)}')
    log(f'   mean round-trip cost drag: {pct(sub["cost_frac"].mean())}')
    log(f'   cluster-by-ISO-week t = {num(t)}   (se {pct(se, 3)}, N={nn}, G={gg})')
    if gg < 5:
        log(f'   !! G={gg} clusters -- a cluster-robust t is NOT INTERPRETABLE this few clusters.')
        log('      Cluster sums can nearly cancel, driving se toward 0 and |t| to nonsense.')
        log('      Expected in --smoke, which spans ~9 weeks by design. DO NOT read it as evidence.')
    for era, e in sub.groupby('era'):
        de = describe(e['ar_net'])
        log(f'   era {era}: N={de["n"]:<5} mean AR {pct(de["mean"])}  '
            f'weeks={e["week"].nunique()}')
    log('')
    return dict(n=d['n'], mean=d['mean'], t=t, G=gg)


def print_verdict(ev, smoke):
    log('=' * 100)
    log('VERDICT')
    log('=' * 100)
    if smoke:
        log('SMOKE RUN -- 2 test-era months only. NO VERDICT, NO EVIDENTIAL WEIGHT. This run exists')
        log('to prove the pipeline executes end-to-end and the point-in-time walls hold; the numbers')
        log('above are a plumbing check, not a result. Run without --smoke for the verdict.')
        log('')
        return None

    tq = ev[ev['top_quartile'] & ev['ar_net'].notna()]
    ctrl = ev[ev['ar_net'].notna()]
    era_a = tq[tq['dt'] < ERA_SPLIT]
    era_b = tq[tq['dt'] >= ERA_SPLIT]
    ma, mb = describe(era_a['ar_net']), describe(era_b['ar_net'])
    c1 = (ma['n'] >= C1_MIN_EVENTS and mb['n'] >= C1_MIN_EVENTS
          and np.isfinite(ma['mean']) and np.isfinite(mb['mean'])
          and ma['mean'] > 0 and mb['mean'] > 0)
    log(f'C1  both era halves mean net AR > 0, each N >= {C1_MIN_EVENTS}')
    log(f'      era A 2022-01..2023-12 : N={ma["n"]:<5} mean {pct(ma["mean"])}')
    log(f'      era B 2024-01..panel   : N={mb["n"]:<5} mean {pct(mb["mean"])}')
    log(f'      -> {"PASS" if c1 else "FAIL"}')

    _, _, t2, n2, g2 = cluster_t(tq['ar_net'], tq['week'])
    c2 = bool(np.isfinite(t2) and t2 >= C2_MIN_T)
    log(f'C2  pooled ISO-week cluster t >= +{C2_MIN_T:.1f}')
    log(f'      t = {num(t2)}  (N={n2}, G={g2})   -> {"PASS" if c2 else "FAIL"}')

    y = np.concatenate([ctrl['ar_net'].to_numpy(), tq['ar_net'].to_numpy()])
    dm = np.concatenate([np.zeros(len(ctrl)), np.ones(len(tq))])
    wk = np.concatenate([ctrl['week'].to_numpy(), tq['week'].to_numpy()])
    beta, se3, t3, n3, g3 = cluster_diff_t(y, dm, wk)
    c3 = bool(np.isfinite(beta) and beta > 0 and np.isfinite(t3) and t3 >= C3_MIN_T)
    log(f'C3  RELABEL GUARD: (top-quartile - control) > 0 with cluster t >= +{C3_MIN_T:.1f}')
    log(f'      difference = {pct(beta)}  se {pct(se3, 3)}  t = {num(t3)}  '
        f'(stacked N={n3}, G={g3})   -> {"PASS" if c3 else "FAIL"}')

    overall = c1 and c2 and c3
    log('')
    if overall:
        log('OVERALL: PASS -> earns an incubator discussion, NOT a deployment. October Contract')
        log('         gate still applies (N>=60 paper trades, staged capital, 20% lifetime cap).')
    elif c1 and c2 and not c3:
        log('OVERALL: FAIL -- and specifically the RELABEL outcome the spec named in advance:')
        log('         "generic bulk-deal drift, buyer identity decorative". The top-quartile arm')
        log('         did not separate from the undifferentiated control.')
        cm, _, ct, cn, cg = cluster_t(ctrl['ar_net'], ctrl['week'])
        log(f'         Note on whether the CONTROL arm is itself a candidate: mean {pct(cm)}, '
            f't={num(ct)} (N={cn}, G={cg}).')
        log('         If that looks live it needs its OWN pre-registered spec -- it is not this one.')
    else:
        log('OVERALL: FAIL -> dead, recorded, no re-tuning. (Declared test count was 1.)')
    log('')
    return overall


# ===========================================================================
# 8. Main
# ===========================================================================
def parse_args():
    p = argparse.ArgumentParser(description='Bulk-deal buyer persistence (frozen spec).')
    p.add_argument('--smoke', action='store_true',
                   help=f'Restrict TEST-ERA events to {SMOKE_TEST_START.date()}..'
                        f'{SMOKE_TEST_END.date()} (track records still accumulate from '
                        f'{RECORD_START.date()}). Writes _smoke.txt, prints no verdict.')
    return p.parse_args()


def main():
    args = parse_args()
    alias_df = load_alias_table()
    print_header(args.smoke, alias_df)

    P = prepare_panel()
    deals, alias_map = load_deals(alias_df)
    print_alias_report(alias_df, deals, alias_map)

    # --- restrict to the measurable era, flag both-sides round trips ---------
    era = deals[deals['dt'] >= RECORD_START].copy()
    excl_keys = both_sides_keys(era)
    era['both_sides'] = list(zip(era['entity'], era['symbol'], era['dt']))
    era['both_sides'] = era['both_sides'].isin(excl_keys)

    buys = era[era['side'] == 'BUY'].copy()
    n_buy_rows = len(buys)
    buys = buys.drop_duplicates(subset=['entity', 'symbol', 'dt'], keep='first')   # IC-6
    n_dedup = n_buy_rows - len(buys)

    log('=' * 100)
    log('EXCLUSIONS AND DROPS')
    log('=' * 100)
    log(f'BUY rows with deal date >= {RECORD_START.date()}: {n_buy_rows}')
    log(f'  - {n_dedup} dropped as same-day tranche duplicates of an existing '
        f'(entity, symbol, date) [IC-6]')
    n_2s = int(buys['both_sides'].sum())
    log(f'  - {n_2s} SAME-DAY-BOTH-SIDES round trips excluded from BOTH events and track '
        f'records [IC-5]')
    log(f'    (affecting {buys.loc[buys["both_sides"], "entity"].nunique()} distinct entities; '
        f'the largest by count:)')
    top2s = buys.loc[buys['both_sides'], 'entity'].value_counts().head(8)
    for e, c in top2s.items():
        log(f'      {c:>6}  {e}')

    outcomes = compute_outcomes(buys, P)
    kept = outcomes[~outcomes['both_sides']].copy()
    log(f'  => {len(kept)} BUY deals survive the both-sides exclusion and enter outcome '
        f'computation.')
    log('  Drop reasons among those (a dropped deal enters NEITHER the track records NOR the arms):')
    rc = kept['drop_reason'].value_counts()
    for r, c in rc.items():
        log(f'      {c:>7}  {r if r else "(kept: outcome computable)"}')
    usable = kept[kept['usable']].copy()
    n_nan = int(usable['ar_net'].isna().sum())
    log(f'  => {len(usable)} deals with a computable {HOLD_DAYS}d outcome; NaN ar_net among them: '
        f'{n_nan} (must be 0)')
    if n_nan:
        sys.exit(f'HALTED: {n_nan} usable deals have a NaN ar_net -- outcome computation is broken.')
    log('')

    print_top_entities(outcomes, deals)

    # --- track records ------------------------------------------------------
    records = TrackRecords(usable)
    log('=' * 100)
    log('TRACK RECORDS (point-in-time)')
    log('=' * 100)
    log(f'{len(records.rec)} canonical entities have >= 1 deal with a computed outcome; '
        f'{len(records.ready_at)} ever reach {MIN_PRIOR_DEALS} completed outcomes.')
    n_pre_excl = int((buys.groupby('entity').size() >= MIN_PRIOR_DEALS).sum())
    log(f'For scale, BEFORE the both-sides exclusion and the price/liquidity gates, '
        f'{n_pre_excl} entities have >= {MIN_PRIOR_DEALS} BUY deals in the era. IC-5 plus the gates')
    log(f'are what collapse that to {len(records.ready_at)} -- the single most consequential '
        f'mechanic in this study.')
    warm = usable[usable['dt'] < TEST_START]
    log(f'Warmup deals (deal date {RECORD_START.date()}..{(TEST_START - pd.Timedelta(days=1)).date()}) '
        f'feeding records only: {len(warm)}')

    # --- test-era events ----------------------------------------------------
    test_lo = SMOKE_TEST_START if args.smoke else TEST_START
    test_hi = SMOKE_TEST_END if args.smoke else usable['dt'].max()
    test_events = usable[(usable['dt'] >= test_lo) & (usable['dt'] <= test_hi)].copy()
    assert len(test_events) == 0 or test_events['dt'].min() >= TEST_START, (
        'TEST-ERA WALL VIOLATED: an event dated before 2022-01-01 reached the statistics.')
    if len(test_events) == 0:
        sys.exit('HALTED: no test-era events with a computable outcome. Nothing to report.')

    thr, nqual = build_week_thresholds(records, test_events['dt'])
    ev = classify_events(test_events, records, thr, nqual)
    point_in_time_wall_check(ev, usable)

    log(f'Test-era window used: {test_lo.date()} .. {test_hi.date()}  '
        f'({"SMOKE" if args.smoke else "FULL"})')
    log(f'Qualified-buyer count at the week starts inside that window '
        f'(>= {MIN_PRIOR_DEALS} completed outcomes):')
    for ws in sorted(nqual):
        log(f'    week starting {pd.Timestamp(ws).date()}: {nqual[ws]:>4} qualified buyers, '
            f'top-quartile hit-rate threshold = '
            f'{num(thr[ws], 4) if np.isfinite(thr[ws]) else "n/a"}')
    log('')

    # --- arms ---------------------------------------------------------------
    log('=' * 100)
    log(f'ERA TABLES -- {HOLD_DAYS}d NET ABNORMAL RETURN BY ARM')
    log('=' * 100)
    tq = ev[ev['top_quartile']]
    ctrl = ev
    rest = ev[~ev['top_quartile']]
    print_arm('TOP-QUARTILE ARM  (the one declared test)', tq)
    print_arm('CONTROL ARM       (ALL gated BUY events, undifferentiated -- superset)', ctrl)
    print_arm('non-top-quartile  (complement)', rest, '   [INFORMATION ONLY, no verdict weight]')

    log(f'Event accounting: {len(ev)} gated test-era events; {int(ev["qualified"].sum())} by a buyer '
        f'with >= {MIN_PRIOR_DEALS} completed prior outcomes; {len(tq)} of those in the top quartile; '
        f'{len(ev) - len(tq)} not.')
    log(f'Distinct top-quartile entities firing at least one event: {tq["entity"].nunique()}')
    if len(tq):
        log('Top-quartile arm, most frequent entities:')
        for e, c in tq['entity'].value_counts().head(10).items():
            log(f'    {c:>5}  {e}')
    log('')

    if len(tq):
        beta, se3, t3, n3, g3 = cluster_diff_t(
            np.concatenate([ctrl['ar_net'].to_numpy(), tq['ar_net'].to_numpy()]),
            np.concatenate([np.zeros(len(ctrl)), np.ones(len(tq))]),
            np.concatenate([ctrl['week'].to_numpy(), tq['week'].to_numpy()]))
        log(f'Difference (top-quartile - control, stacked, week-clustered): {pct(beta)}  '
            f'se {pct(se3, 3)}  t = {num(t3)}  (N={n3}, G={g3})')
        b2, s2, t2b, n2b, g2b = cluster_diff_t(
            np.concatenate([rest['ar_net'].to_numpy(), tq['ar_net'].to_numpy()]),
            np.concatenate([np.zeros(len(rest)), np.ones(len(tq))]),
            np.concatenate([rest['week'].to_numpy(), tq['week'].to_numpy()]))
        log(f'  [INFO ONLY, non-overlapping variant] top-quartile - complement: {pct(b2)}  '
            f'se {pct(s2, 3)}  t = {num(t2b)}  (N={n2b}, G={g2b})')
        log('')

    print_verdict(ev, args.smoke)

    out_path = OUT_DIR / ('bulk_buyer_results_smoke.txt' if args.smoke else 'bulk_buyer_results.txt')
    flush_out(out_path)
    print(f'\n[saved output to {out_path}]')


if __name__ == '__main__':
    main()
