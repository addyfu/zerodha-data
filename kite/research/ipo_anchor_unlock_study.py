"""IPO Anchor-Investor Lock-in Unlock Study -- FROZEN pre-registered study.

Spec (frozen, read this first, do not deviate without a spec amendment):
    docs/superpowers/specs/2026-07-28-ipo-anchor-unlock-design.md

HYPOTHESIS: on an anchor-investor lock-in expiry a block of float becomes
sellable at once with no obligated buyer. Unlock days should show mechanical
selling pressure; the tradeable leg for a long-only cash account is buying the
post-unlock dip once the overhang clears.

============================================================================
R1 -- REGULATORY DATE PIN (the spec's HALT-if-unresolved requirement)
============================================================================
PRIMARY SOURCE (SEBI, not a secondary/news write-up):
  Landing page (notification dated Jan 14, 2022):
    https://www.sebi.gov.in/legal/regulations/jan-2022/securities-and-exchange-board-of-india-issue-of-capital-and-disclosure-requirements-amendment-regulations-2022_55351.html
  Gazette PDF attached to that page (the text quoted below was extracted from
  this file on 2026-07-28):
    https://www.sebi.gov.in/sebi_data/attachdocs/jan-2022/1642395606006.pdf

Instrument: "Securities and Exchange Board of India (Issue of Capital and
Disclosure Requirements) (Amendment) Regulations, 2022", notified 2022-01-14.

(a) The operative amendment (Schedule XIII, Part A, clause (10), sub-clause
    (j) substituted) -- verbatim from the gazette PDF:
        "There shall be a lock-in of 90 days on fifty per cent of the shares
         allotted to the anchor investors from the date of allotment, and a
         lock-in of 30 days on the remaining fifty per cent of the shares
         allotted to the anchor investors from the date of allotment"
    (Before this: the whole anchor allocation was locked in for 30 days.)

(b) The commencement clause -- verbatim from the same PDF, regulation 2:
        "They shall come into force on the date of their publication in the
         Official Gazette. Provided that the amendments to sub-regulation (3A)
         of regulation 32, regulation 49, regulation 129, regulation 145,
         clause (10) and clause (15) of Part A of Schedule XIII and Schedule
         XIV shall come into force from April 1, 2022, for issues opening on
         or after April 1, 2022"

    The anchor lock-in change lives in "clause (10) ... of Part A of Schedule
    XIII", which is explicitly named in that proviso. So the pinned date is:

        *** EFFECTIVE FOR ISSUES OPENING ON OR AFTER 2022-04-01 ***

    (not the 2022-01-14 notification date -- the notification date is a
    distractor and using it would misclassify every Jan-Mar 2022 IPO.)

ERA SPLIT APPLIED TO LISTING DATE (documented approximation, per the build
instruction that listing ~= issue_open + ~6-10 days is acceptable if
documented). We only observe listing dates in the bhavcopy panel; the
regulation keys off the ISSUE OPENING date. In force during 2022 the timeline
was: issue open -> issue close (typically open + 2 working days) -> listing on
T+6 working days from close (SEBI's T+3 listing timeline only became
voluntary from 2023-09-01 and mandatory from 2023-12-01, i.e. well after the
boundary). So listing ~= issue_open + 8 working days ~= issue_open + 10 to 14
calendar days in the Apr-2022 neighbourhood. Rather than assume a point
mapping we carve out an explicit ambiguity band:

    ERA_PRE       : listing_date <  2022-04-01   (issue must have opened
                    before 2022-04-01 -> old 30-day-for-100% regime)
    ERA_AMBIGUOUS : 2022-04-01 <= listing_date < 2022-04-18  (issue could have
                    opened on either side of the boundary)
    ERA_POST      : listing_date >= 2022-04-18   (a listing on/after this date
                    implies an issue opening on/after ~2022-04-04 under the
                    then-current T+6 timeline -> new 50%/50% regime)

Handling of ERA_AMBIGUOUS (frozen here, stated before results):
  - its regulatory regime is unknown, so NO +90 unlock event is generated for
    it (a +90 unlock only exists post-amendment);
  - its +30 unlock (which exists under BOTH regimes) IS generated, is INCLUDED
    in the pooled statistics (verdict criteria 2 and 3, which do not depend on
    the regulatory date) and is EXCLUDED from the per-era cells (verdict
    criterion 1, which does).
  The count of ambiguous listings is printed so the reviewer can see how much
  this convention can possibly matter.

KNOWN BIAS, STATED UP FRONT: the lock-in runs from the date of ALLOTMENT, not
from listing. Allotment precedes listing by ~2-4 calendar days. The spec
FREEZES the event as listing_date + 30/+90 calendar days rolled forward, so
that is what is implemented -- but it means the modelled unlock day sits ~2-4
calendar days AFTER the true unlock day. If the effect is concentrated in the
first day or two it will be partly outside our [0,+1] window. This is a
spec-level bias, not an implementation bug, and it is not tuned away here.

============================================================================
DATA + LISTING DETECTOR
============================================================================
Panel: data/bhavcopy_full/sec_bhavdata_full_DDMMYYYY.csv (fetch_bhavcopy_full.py)
       + data/corp_actions_adjustments.csv (build_corp_actions.py).
Loader conventions, corp-action back-adjustment, +/-25% return clip, EW
daily-rebalanced frictionless benchmark and the costs call are all taken from
kite/research/delivery_factor_study.py and kite/research/event_study.py --
this file deliberately does not invent new conventions for those.

Listing date = a symbol's FIRST APPEARANCE IN ANY SERIES in the panel (not
first EQ appearance). Using any-series is what stops 522 series-migration
artifacts (a stock that traded in BE/SM/T for years and only later moved to
EQ is not a new listing) from being scored as IPOs.

Analysis price frame = series EQ + BE (some genuine IPOs list into BE, e.g.
NUVAMA). Benchmark ELIGIBLE universe = EQ only, turnover >= Rs 2 crore,
adjusted close >= Rs 20 -- the repo's existing universe convention.

EXCLUSIONS (all documented, first matching reason is reported per symbol; the
full list is printed in the results file because the spec makes the exclusion
list part of the reviewed deliverable):

  PANEL_EDGE            first appearance < 2019-11-01. The panel starts
                        2019-10-01, so every symbol already trading then has a
                        fake "first appearance" on the window edge.
  RIGHTS_ENTITLEMENT    symbol matches -RE / -RE<n> (rights entitlements are
                        temporary instruments, not listings).
  NON_MAINBOARD_SERIES  listing-day series not in {EQ, BE}: SM/ST = NSE Emerge
                        (SME), GS/GB/N* = debt, MF/IV/E1 = funds, RR = rights.
  FUND_OR_ETF           symbol is in the hand-reviewed ETF / index-fund /
                        commodity-fund exclusion set below. ETFs list on the
                        EQ series and have no anchor book at all, so they are
                        pure contamination. THIS IS THE WEAKEST HEURISTIC IN
                        THE FILE -- it is a curated name list, not a
                        structural test (the bhavcopy carries no ISIN or
                        instrument-type column). To make the gap visible
                        rather than silent, any surviving symbol that matches
                        a broad fund-name REGEX but is NOT in the curated set
                        is printed as an explicit reviewer warning.
  RENAME_TWIN_PRICE     a different symbol vanished from the panel in the 15
                        trading days before this listing and its last close
                        EQUALS this symbol's listing-day PREV_CLOSE exactly.
                        That is NSE carrying a renamed ticker's close over to
                        the new ticker (IIFLWAM->360ONE, CENTURYTEX->ABREL,
                        ADANITRANS->ADANIENSOL, GATI->ACLGATI, ...). Exact
                        equality is required: a 2% tolerance was tried during
                        construction and produced false positives against
                        genuine IPOs (ACMESOLAR, ATHERENERG) whose issue price
                        happened to sit near an unrelated delisting's close.
  RENAME_TWIN_NAME      a different symbol vanished within +/-15 trading days
                        of this listing and shares a >= 5 character common
                        prefix (MOTHERSUMI->MOTHERSON, ANGELBRKG->ANGELONE,
                        COSMOFILMS->COSMOFIRST, ...).
  CORP_ACTION_SCHEME    data/corp_actions_adjustments.csv has a row for this
                        symbol whose subject matches scheme / arrangement /
                        demerger / amalgamation / merger within +/-180 days of
                        the listing date.
  NO_ISSUE_PRICE        listing-day PREV_CLOSE is missing, <= 0, or is NOT a
                        whole rupee.
                        RATIONALE (the main demerger/spin-off filter, and the
                        heuristic the reviewer should scrutinise hardest): on
                        an IPO's first bhavcopy row NSE puts the ISSUE PRICE in
                        PREV_CLOSE, and Indian issue prices are always whole
                        rupees (Rs 76, Rs 315, Rs 1080, ...). On a spin-off /
                        scheme-of-arrangement / rename listing PREV_CLOSE is
                        instead a market-derived price carrying paise (JIOFIN
                        261.85, GMRP&UI 48.45, NSLNISP 130.75, GHCLTEXTIL
                        543.25, BAJEL 130.95, DIGIDRIVE 1347.50, NUVAMA
                        2822.10, ...). Validated during construction against a
                        hand-listed set of 35 well-known mainboard IPOs
                        (TATATECH 500, MANKIND 1080, ZOMATO 76, NYKAA 1125,
                        LICI 949, HYUNDAI 1960, SWIGGY 390, ...): all 35
                        passed. FALSE-NEGATIVE COST: NSE ticks are 5 paise, so
                        roughly 1 in 20 non-IPO listings will have a whole-
                        rupee reference price and leak through (EXXARO 120.00
                        and GSLSU 140.00 are two observed leaks) -- the twin
                        and corp-action rules are the second net for those.
                        FALSE-POSITIVE COST: any genuine IPO whose true day-1
                        bhavcopy row is missing from the panel is dropped,
                        because we then read a later day's PREV_CLOSE (CAMS is
                        the one observed case: its 2020-10-01 listing row is
                        absent from NSE's own 2020-10-01 file, so its first
                        panel row is 2020-10-05 with PREV_CLOSE 1401.60). That
                        direction costs sample size, it does not contaminate.
  SME_LIQUIDITY         listing-day TURNOVER_LACS < 200 (Rs 2 crore). This is
                        the spec's stated SME approximation AND the study's
                        liquidity bar, in one gate.
  BAD_LISTING_PRICES    listing-day open/close missing or <= 0.
  INSUFFICIENT_FORWARD  fewer than 60 forward trading days for that symbol in
                        the panel (the spec's >= 60 forward-trading-day bar).

INFO-ONLY REVIEW FLAG (printed, NOT excluded): a surviving symbol sharing a
>= 5 character prefix with a still-trading symbol that pre-dates the panel
(possible group / demerger listing). This was tried as an exclusion during
construction and rejected: it kills genuine IPOs (BAJAJHFL vs BAJAJHIND,
BHARTIHEXA vs BHARTIARTL, CONCORDBIO vs CONCOR, INDIGOPNTS vs INDIGO,
CYIENTDLM vs CYIENT, ...) at a rate that is not worth its demerger yield now
that NO_ISSUE_PRICE carries that load. It is reported so the reviewer can
overrule.

============================================================================
EVENTS, WINDOWS AND THE TRADEABLE LEG (frozen)
============================================================================
Unlock events per qualifying listing L:
  E30 = first trading day on/after L + 30 calendar days   (both eras)
  E90 = first trading day on/after L + 90 calendar days   (ERA_POST only)

Information windows (NO verdict weight):
  [-5,-1] pre-unlock drift : stock adj_close[E-1]/adj_close[E-6] - 1
  [0,+1]  unlock reaction  : stock adj_close[E+1]/adj_close[E-1] - 1
  both minus the equal-weight universe compounded over the SAME calendar span
  (close-to-close on both legs, so there is no open/close basis mismatch).

PRIMARY leg (the ONE declared verdict-bearing test):
  IF cumulative [0,+1] abnormal return <= -2.0% (the overhang materialised)
  AND the liquidity gate holds at E (turnover >= Rs 2 crore, adj close >= Rs 20
  -- gated at E, whose data is fully known before the E+2 entry; gating on the
  entry day's own turnover would be lookahead)
  THEN BUY at E+2 OPEN, hold 10 trading days, EXIT at the E+12 OPEN.
  Costs: 0.2%/side slippage applied to the fill price, then
  zerodha_charges.calculate_charges(buy_v, sell_v, is_intraday=False)['total']
  (NEVER sum(charges.values()) -- that dict already contains 'total' equal to
  the sum of the other six components; summing everything double-counts, the
  exact bug fixed across this repo on 2026-07-26/27).
  Zerodha's DP charge is FLAT per delivery sell, so the net percentage return
  depends on trade size: a fixed notional of Rs 100,000 per trade is assumed
  and stated (qty = floor(notional / buy price), qty >= 1 required).

Declared test count: 1. The two information windows and every diagnostic below
carry no verdict weight.

============================================================================
VERDICT (frozen, ALL THREE must hold)
============================================================================
1. Mean net trade return > 0 in BOTH regulatory eras, each era with >= 15
   trades. An era with < 15 trades is recorded as NODATA/underpowered, which
   is a recorded OUTCOME, not a pass.
2. Pooled cluster-robust t >= +2.0.
3. Win rate >= 55%.

CLUSTERING (interpretation choice, flagged for review -- the reviewer should
check this paragraph). The spec freezes two sentences that can conflict:
"clustered by calendar month of the unlock" and "the two unlocks of one IPO
share a cluster". An IPO's +30 and +90 unlocks are ~2 calendar months apart,
so they normally fall in DIFFERENT months and the two sentences cannot both
hold under a naive month key.

PRIMARY (used by the verdict) -- ANCHOR-MONTH clustering: the cluster key is
the calendar month of that IPO's EARLIEST unlock (its +30), applied to BOTH of
its events. This makes both frozen sentences literally true (the key is a
calendar month of an unlock, and one IPO's two unlocks always share it), keeps
roughly one cluster per calendar month, and absorbs both the IPO-wave
correlation the spec names and the within-IPO correlation.

REJECTED ALTERNATIVE, recorded because it was the first thing tried: a
union-find that starts from month clusters and unions the months touched by
the same IPO. It DEGENERATES -- IPO waves overlap, so IPO A links months
(m1,m2), IPO B links (m2,m3), ... and the transitive closure collapses the
entire sample into G=1 or G=2 clusters, which makes the cluster-robust t
undefined or wildly unstable (on the 2023 smoke set it gave G=1 for the event
windows and G=5 / t=+2.41 for the trades, versus t=+1.0 under every
non-degenerate scheme). It is not used and not reported.

DIAGNOSTICS, printed but carrying no verdict weight: pure month-of-that-event
(splits an IPO's two unlocks apart, violating the second frozen sentence) and
pure by-IPO (many small clusters -- discards exactly the IPO-wave correlation
the spec names as the reason for clustering, so it is the LEAST conservative
of the three).
  t = mean / sqrt(V),
  V = (G/(G-1)) * (1/N^2) * sum_over_clusters( sum_in_cluster(x_i - mean) )^2

Usage:
    python kite/research/ipo_anchor_unlock_study.py --smoke   # 2023 listings
    python kite/research/ipo_anchor_unlock_study.py           # full + verdict
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

DATA_DIR = ROOT / 'data' / 'bhavcopy_full'
CORP_ACTIONS_PATH = ROOT / 'data' / 'corp_actions_adjustments.csv'
OUT_DIR = ROOT / 'kite' / 'research'

# ---------------------------------------------------------------------------
# Frozen constants
# ---------------------------------------------------------------------------
PANEL_EDGE_CUTOFF = pd.Timestamp('2019-11-01')  # first appearance before this = window artifact
MIN_TURNOVER_LACS = 200.0     # Rs 2 crore -- liquidity bar AND the spec's SME approximation
MIN_PRICE = 20.0              # Rs 20 adjusted close (universe eligibility)
MIN_FORWARD_DAYS = 60         # spec: require >= 60 forward trading days
CLIP = 0.25                   # +/-25% daily return clip (repo convention)

UNLOCK_30 = 30                # calendar days from listing
UNLOCK_90 = 90                # calendar days from listing (ERA_POST only)

TRIGGER_CAR = -0.02           # [0,+1] cumulative abnormal <= -2.0%
ENTRY_OFFSET = 2              # BUY at E+2 open
HOLD_DAYS = 10                # hold 10 trading days -> exit at E+12 open
SLIP = 0.002                  # 0.2% per side
TRADE_NOTIONAL = 100_000.0    # Rs per trade (flat DP charge makes size matter)

PRE_WINDOW = 5                # information window [-5,-1]

# SEBI ICDR (Amendment) Regulations, 2022 -- see the module docstring for the
# verbatim commencement clause and the primary-source URLs.
SEBI_ISSUE_OPEN_EFFECTIVE = pd.Timestamp('2022-04-01')
ERA_AMBIGUOUS_END = pd.Timestamp('2022-04-18')  # listings >= this date are unambiguously post
ERA_PRE, ERA_POST, ERA_AMBIG = 'PRE', 'POST', 'AMBIGUOUS'

MIN_TRADES_PER_ERA = 15
T_BAR = 2.0
WIN_RATE_BAR = 0.55

SMOKE_YEAR = 2023

MAINBOARD_SERIES = ('EQ', 'BE')
RIGHTS_RE = re.compile(r'-RE\d*$')
SCHEME_RE = re.compile(r'scheme|arrangement|demerg|amalgamat|merger', re.IGNORECASE)
TWIN_NAME_PREFIX = 5
TWIN_WINDOW_TD = 15

# Hand-reviewed ETF / index-fund / commodity-fund exclusions (see docstring:
# weakest heuristic in the file, curated because the bhavcopy has no
# instrument-type column). Every symbol here was eyeballed against the
# surviving candidate list during construction.
FUND_EXCLUSIONS = {
    'AONEGOLD', 'AONESILVER', 'AONETOTAL', 'ALPL30IETF', 'AUTOIETF', 'AXISBNKETF',
    'BANKADD', 'BANKETF', 'BANKIETF', 'BBNPNBETF', 'BBNPPGOLD', 'BSE500IETF',
    'CASHIETF', 'COMMOIETF', 'CONSUMIETF', 'DECNGOLD', 'DSPBANKETF', 'DSPGOLDETF',
    'DSPITETF', 'DSPPSBKETF', 'DSPPVBKETF', 'DSPSENXETF', 'EBBETF0425', 'EBBETF0430',
    'EBBETF0431', 'EBGNG', 'EGOLD', 'ESILVER', 'FINIETF', 'FMCGIETF', 'GOLDETF',
    'GOLDIETF', 'GROWWCAPM', 'GROWWDEFNC', 'GROWWHOSPI', 'GROWWLIQID', 'GROWWMOM50',
    'GROWWN200', 'GROWWNET', 'GROWWPOWER', 'GROWWPSE', 'GROWWRAIL', 'GROWWSLVR',
    'GSEC10IETF', 'GSEC10YEAR', 'GSEC5IETF', 'HDFCBSE500', 'HDFCGOLD', 'HDFCLIQUID',
    'HDFCMID150', 'HDFCNIFBAN', 'ICICISILVE', 'LIQUID', 'LIQUIDCASE', 'NIFMID150',
    'TATAGOLD', 'VLEGOV', 'ABSLLIQUID', 'ABSL10BANK', 'ABSLMSCIN', 'ABSLPSE',
    'ALPHAETF', 'AXSENSEX', 'AUTOBEES', 'BFSI', 'ESG', 'ALPHA',
}
# Broad fund-name regex used ONLY to warn about symbols the curated set may
# have missed. Deliberately over-broad (it also hits e.g. SHANTIGOLD, a real
# IPO) -- that is why it warns instead of excluding.
FUND_WARN_RE = re.compile(
    r'(ETF|BEES|IETF|LIQUID|LIQID|GSEC|GILT|BOND|SENSEX|SENSX|NIFTY|MID150|TOP100'
    r'|LOWVOL|SLVR|SILVE|GOLD$|N50$|N100$|N200$|^EB[BG]|^GROWW.+|PSE$|PSU$)')

FNAME_DATE_RE = re.compile(r'sec_bhavdata_full_(\d{2})(\d{2})(\d{4})\.csv$', re.IGNORECASE)
NEEDED_COLS = ['SYMBOL', 'SERIES', 'DATE1', 'PREV_CLOSE', 'OPEN_PRICE',
               'CLOSE_PRICE', 'TTL_TRD_QNTY', 'TURNOVER_LACS']

_OUT_LINES = []


def log(msg=''):
    print(msg, flush=True)
    _OUT_LINES.append(str(msg))


def flush_out(path):
    path.write_text('\n'.join(_OUT_LINES) + '\n', encoding='utf-8')


# ---------------------------------------------------------------------------
# Loading (delivery_factor_study.py conventions: strip headers AND string
# values, trading day taken from the FILENAME rather than parsing DATE1).
# Difference from that file: ALL series are kept, because the listing detector
# needs to know whether a symbol pre-existed in BE/SM/T before appearing in EQ.
# ---------------------------------------------------------------------------
def load_panel(data_dir=DATA_DIR):
    files = sorted(data_dir.glob('sec_bhavdata_full_*.csv'))
    frames, skipped = [], []
    for f in files:
        m = FNAME_DATE_RE.search(f.name)
        if not m:
            skipped.append((f.name, 'filename pattern'))
            continue
        file_date = pd.Timestamp(year=int(m.group(3)), month=int(m.group(2)), day=int(m.group(1)))
        df = None
        for enc in ('utf-8', 'latin-1'):
            try:
                df = pd.read_csv(f, dtype=str, encoding=enc)
                break
            except Exception as e:  # noqa: BLE001
                err = f'{type(e).__name__}'
        if df is None:
            skipped.append((f.name, err))
            continue
        df.columns = df.columns.str.strip()
        missing = [c for c in NEEDED_COLS if c not in df.columns]
        if missing:
            skipped.append((f.name, f'missing columns {missing}'))
            continue
        df = df[NEEDED_COLS].copy()
        for c in NEEDED_COLS:
            df[c] = df[c].astype(str).str.strip()
        df['date'] = file_date
        for c in ['PREV_CLOSE', 'OPEN_PRICE', 'CLOSE_PRICE', 'TTL_TRD_QNTY', 'TURNOVER_LACS']:
            df[c] = pd.to_numeric(df[c], errors='coerce')
        frames.append(df.rename(columns={
            'SYMBOL': 'symbol', 'SERIES': 'series', 'PREV_CLOSE': 'prev_close',
            'OPEN_PRICE': 'open', 'CLOSE_PRICE': 'close', 'TTL_TRD_QNTY': 'ttl_qty',
            'TURNOVER_LACS': 'turnover_lacs',
        })[['symbol', 'series', 'date', 'prev_close', 'open', 'close',
            'ttl_qty', 'turnover_lacs']])
    if not frames:
        sys.exit(f'HALTED: no usable files found under {data_dir}. Run fetch_bhavcopy_full.py first.')
    allp = pd.concat(frames, ignore_index=True)
    allp = allp.drop_duplicates(subset=['symbol', 'series', 'date'], keep='last')
    allp = allp.sort_values(['symbol', 'date']).reset_index(drop=True)

    log(f'Loaded {len(files)} bhavcopy files ({len(skipped)} unusable), '
        f'{len(allp)} all-series stock-day rows, {allp.symbol.nunique()} symbols, '
        f'{allp.date.min().date()} -> {allp.date.max().date()}, '
        f'{allp.date.nunique()} trading days.')
    for name, why in skipped:
        log(f'  WARN unusable file: {name} ({why}) -- that trading day is absent from the panel.')
    return allp


def build_price_frame(allp):
    """Analysis price frame: mainboard series only (EQ + BE), one row per
    (symbol, date) with EQ winning if both ever collide."""
    p = allp[allp['series'].isin(MAINBOARD_SERIES)].copy()
    p['_pri'] = (p['series'] != 'EQ').astype(int)  # EQ first
    p = p.sort_values(['symbol', 'date', '_pri']).drop_duplicates(['symbol', 'date'], keep='first')
    return p.drop(columns='_pri').reset_index(drop=True)


# ---------------------------------------------------------------------------
# Corporate actions -- lifted from delivery_factor_study.py (same convention:
# multiply every price STRICTLY BEFORE an ex_date by that action's factor,
# compounding across multiple actions).
# ---------------------------------------------------------------------------
def load_corp_actions(path=CORP_ACTIONS_PATH):
    if not path.exists():
        sys.exit(f'HALTED: {path} not found. Run build_corp_actions.py first.')
    df = pd.read_csv(path)
    df['ex_date'] = pd.to_datetime(df['ex_date'])
    return df


def halt_on_unresolved_nan_factors(panel, corp_actions):
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
        sys.exit(f'HALTED: {len(offenders)} unresolved corp-action factor(s) affect the loaded panel.')


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
    panel['adj_mult'] = mult
    panel['adj_open'] = panel['open'] * panel['adj_mult']
    panel['adj_close'] = panel['close'] * panel['adj_mult']
    log(f'Corporate-action adjustment applied: {int((mult != 1.0).sum())} stock-day rows scaled, '
        f'{valid["symbol"].nunique()} symbols with >=1 valid action.')
    return panel


# ---------------------------------------------------------------------------
# Benchmark: EW daily-rebalanced, frictionless, clip-guarded, EQ-only eligible
# universe (turnover >= Rs 2cr, adj close >= Rs 20). Prefix-product form from
# event_study.py: compounded universe return over global positions [a, b] is
# P[b] / P[a-1] - 1, with P[-1] := 1.
# ---------------------------------------------------------------------------
def build_benchmark(panel):
    panel = panel.sort_values(['symbol', 'date']).reset_index(drop=True)
    panel['prev_adj_close'] = panel.groupby('symbol')['adj_close'].shift(1)
    panel['raw_ret'] = panel['adj_close'] / panel['prev_adj_close'] - 1
    panel['ret'] = panel['raw_ret'].clip(-CLIP, CLIP)
    panel['eligible'] = ((panel['series'] == 'EQ')
                         & (panel['turnover_lacs'] >= MIN_TURNOVER_LACS)
                         & (panel['adj_close'] >= MIN_PRICE))
    elig_ret = panel['ret'].where(panel['eligible'])
    u = pd.DataFrame({'date': panel['date'], 'r': elig_ret}).dropna()
    all_dates = pd.DatetimeIndex(sorted(panel['date'].unique()))
    u_ret = u.groupby('date')['r'].mean().reindex(all_dates).fillna(0.0)
    P = (1.0 + u_ret.to_numpy()).cumprod()
    log(f'Benchmark: EW daily-rebalanced frictionless universe over {int(panel["eligible"].sum())} '
        f'eligible EQ stock-days ({len(all_dates)} trading days), returns clipped +/-{CLIP:.0%}.')
    return panel, all_dates, P


def market_leg(P, a_pos, b_pos):
    """Compounded universe return over global positions [a_pos, b_pos] inclusive."""
    denom = P[a_pos - 1] if a_pos >= 1 else 1.0
    return P[b_pos] / denom - 1.0


# ---------------------------------------------------------------------------
# Listing detector
# ---------------------------------------------------------------------------
def _lcp(a, b):
    n = 0
    for x, y in zip(a, b):
        if x != y:
            break
        n += 1
    return n


def detect_listings(allp, price, all_dates, corp_actions):
    """Returns (listings_df, exclusions_df, warn_dicts)."""
    date_pos = {d: i for i, d in enumerate(all_dates)}
    end_pos = len(all_dates) - 1

    first_any = allp.groupby('symbol')['date'].min()
    n_raw = len(first_any)

    # listing-day row (from the all-series frame; if a symbol debuts in more
    # than one series on the same day, take the higher-turnover row)
    fa = allp.merge(first_any.rename('L').reset_index(), on='symbol')
    fday = (fa[fa['date'] == fa['L']]
            .sort_values(['symbol', 'turnover_lacs'], ascending=[True, False])
            .groupby('symbol').first())

    # symbols that vanished from the mainboard frame (last row well before panel end)
    last_row = price.sort_values(['symbol', 'date']).groupby('symbol').last()
    van = pd.DataFrame({'symbol': last_row.index,
                        'last_date': last_row['date'].values,
                        'last_close': last_row['close'].values})
    van['last_pos'] = van['last_date'].map(date_pos)
    van = van[van['last_pos'] < end_pos - 5].reset_index(drop=True)

    # still-trading symbols that pre-date the panel edge (for the info-only flag)
    last_any = allp.groupby('symbol')['date'].max()
    preexisting_alive = sorted(s for s in first_any.index
                               if first_any[s] < PANEL_EDGE_CUTOFF
                               and last_any[s] >= all_dates[end_pos - 5])

    # forward trading-day count per symbol in the mainboard frame
    fwd_rows = price.groupby('symbol')['date'].count()

    # corp-action scheme hits
    ca_scheme = corp_actions[corp_actions['subject'].astype(str).str.contains(SCHEME_RE)]

    van_pos = van['last_pos'].to_numpy()
    van_sym = van['symbol'].to_numpy()
    van_close = van['last_close'].to_numpy()
    van_last = pd.DatetimeIndex(van['last_date'])

    rows = []
    for sym in first_any.index:
        L = first_any[sym]
        r = fday.loc[sym]
        reasons = []

        if L < PANEL_EDGE_CUTOFF:
            reasons.append(('PANEL_EDGE', f'first appearance {L.date()} < {PANEL_EDGE_CUTOFF.date()}'))
        if RIGHTS_RE.search(sym):
            reasons.append(('RIGHTS_ENTITLEMENT', 'symbol matches -RE<n>'))
        if r['series'] not in MAINBOARD_SERIES:
            reasons.append(('NON_MAINBOARD_SERIES', f'listing-day series={r["series"]}'))
        if sym in FUND_EXCLUSIONS:
            reasons.append(('FUND_OR_ETF', 'in curated ETF/index-fund exclusion set'))

        Lp = date_pos.get(L)
        pc = r['prev_close']
        if Lp is not None:
            lo, hi = Lp - TWIN_WINDOW_TD, Lp + TWIN_WINDOW_TD
            m = (van_pos >= lo) & (van_pos <= hi) & (van_sym != sym)
            if m.any():
                if pd.notna(pc) and pc > 0:
                    mp = m & (van_pos < Lp) & (np.abs(van_close / pc - 1.0) < 1e-9)
                    if mp.any():
                        twins = ', '.join(f'{van_sym[i]}(last {van_last[i].date()}'
                                          f' @{van_close[i]})' for i in np.where(mp)[0][:3])
                        reasons.append(('RENAME_TWIN_PRICE',
                                        f'prev_close {pc} == vanished twin last close: {twins}'))
                cand_idx = np.where(m)[0]
                namey = [i for i in cand_idx if _lcp(sym, van_sym[i]) >= TWIN_NAME_PREFIX]
                if namey:
                    twins = ', '.join(f'{van_sym[i]}(last {van_last[i].date()})'
                                      for i in namey[:3])
                    reasons.append(('RENAME_TWIN_NAME',
                                    f'>= {TWIN_NAME_PREFIX}-char prefix with vanished: {twins}'))

        ca = ca_scheme[ca_scheme['symbol'] == sym]
        if len(ca):
            near = ca[(ca['ex_date'] - L).abs() <= pd.Timedelta(days=180)]
            if len(near):
                reasons.append(('CORP_ACTION_SCHEME',
                                f'{near.iloc[0]["subject"]!r} ex {near.iloc[0]["ex_date"].date()}'))

        if pd.isna(pc) or pc <= 0:
            reasons.append(('NO_ISSUE_PRICE', 'listing-day prev_close missing/<=0'))
        elif abs(pc - round(pc)) > 1e-9:
            reasons.append(('NO_ISSUE_PRICE', f'listing-day prev_close {pc} is not a whole rupee'))

        if pd.isna(r['turnover_lacs']) or r['turnover_lacs'] < MIN_TURNOVER_LACS:
            reasons.append(('SME_LIQUIDITY',
                            f'listing-day turnover {r["turnover_lacs"]} lacs < {MIN_TURNOVER_LACS:.0f}'))
        if pd.isna(r['open']) or pd.isna(r['close']) or r['open'] <= 0 or r['close'] <= 0:
            reasons.append(('BAD_LISTING_PRICES', f'open={r["open"]} close={r["close"]}'))

        n_fwd = int(fwd_rows.get(sym, 0)) - 1
        if Lp is None or (end_pos - Lp) < MIN_FORWARD_DAYS or n_fwd < MIN_FORWARD_DAYS:
            reasons.append(('INSUFFICIENT_FORWARD',
                            f'{max(n_fwd, 0)} own forward trading days '
                            f'(panel allows {max(end_pos - (Lp or end_pos), 0)})'))

        rows.append(dict(symbol=sym, listing_date=L, series=r['series'],
                         prev_close=pc, open=r['open'], close=r['close'],
                         turnover_lacs=r['turnover_lacs'],
                         reason=(reasons[0][0] if reasons else ''),
                         detail=(reasons[0][1] if reasons else ''),
                         all_reasons='|'.join(x[0] for x in reasons)))

    det = pd.DataFrame(rows)
    excl = det[det['reason'] != ''].copy()
    keep = det[det['reason'] == ''].copy().sort_values('listing_date').reset_index(drop=True)

    # info-only review flags on SURVIVORS
    warn_fund = sorted(s for s in keep['symbol'] if FUND_WARN_RE.search(s))
    warn_related = {}
    for s in keep['symbol']:
        best = None
        for p in preexisting_alive:
            n = _lcp(s, p)
            if n >= TWIN_NAME_PREFIX and (best is None or n > best[1]):
                best = (p, n)
        if best:
            warn_related[s] = best
    return n_raw, keep, excl, warn_fund, warn_related


def era_of(listing_date):
    if listing_date < SEBI_ISSUE_OPEN_EFFECTIVE:
        return ERA_PRE
    if listing_date >= ERA_AMBIGUOUS_END:
        return ERA_POST
    return ERA_AMBIG


# ---------------------------------------------------------------------------
# Event construction + the conditional long leg
# ---------------------------------------------------------------------------
def build_events(keep, price, all_dates, P, smoke):
    date_pos = {d: i for i, d in enumerate(all_dates)}
    by_sym = {s: g.sort_values('date').reset_index(drop=True)
              for s, g in price.groupby('symbol', sort=False)}

    funnel = dict(listings=0, listings_smoke_dropped=0, events_planned=0,
                  no_unlock_day=0, no_pre_window=0, no_post_window=0,
                  bad_prices=0, kept=0, triggered=0, gate_failed=0,
                  no_entry_exit=0, trades=0)
    events = []
    for _, lr in keep.iterrows():
        sym, L = lr['symbol'], lr['listing_date']
        era = era_of(L)
        if smoke and L.year != SMOKE_YEAR:
            funnel['listings_smoke_dropped'] += 1
            continue
        funnel['listings'] += 1
        g = by_sym.get(sym)
        if g is None or g.empty:
            continue
        sdates = g['date'].to_numpy()
        aclose = g['adj_close'].to_numpy()
        aopen = g['adj_open'].to_numpy()
        turn = g['turnover_lacs'].to_numpy()
        n = len(g)

        offsets = [(UNLOCK_30, 'U30')]
        if era == ERA_POST:
            offsets.append((UNLOCK_90, 'U90'))
        for cal_days, tag in offsets:
            funnel['events_planned'] += 1
            target = np.datetime64((L + pd.Timedelta(days=cal_days)).to_datetime64())
            ep = int(np.searchsorted(sdates, target, side='left'))
            if ep >= n:
                funnel['no_unlock_day'] += 1
                continue
            E = pd.Timestamp(sdates[ep])
            if ep - (PRE_WINDOW + 1) < 0:
                funnel['no_pre_window'] += 1
                continue
            if ep + 1 >= n:
                funnel['no_post_window'] += 1
                continue

            c_m6, c_m1, c_p1 = aclose[ep - PRE_WINDOW - 1], aclose[ep - 1], aclose[ep + 1]
            if not (np.isfinite(c_m6) and np.isfinite(c_m1) and np.isfinite(c_p1)
                    and c_m6 > 0 and c_m1 > 0):
                funnel['bad_prices'] += 1
                continue

            g_m6 = date_pos[pd.Timestamp(sdates[ep - PRE_WINDOW - 1])]
            g_m1 = date_pos[pd.Timestamp(sdates[ep - 1])]
            g_p1 = date_pos[pd.Timestamp(sdates[ep + 1])]
            car_pre = (c_m1 / c_m6 - 1.0) - market_leg(P, g_m6 + 1, g_m1)
            car_01 = (c_p1 / c_m1 - 1.0) - market_leg(P, g_m1 + 1, g_p1)
            funnel['kept'] += 1

            ev = dict(symbol=sym, listing_date=L, era=era, unlock_tag=tag,
                      unlock_date=E, unlock_month=f'{E.year:04d}-{E.month:02d}',
                      car_pre=car_pre, car_01=car_01,
                      triggered=False, traded=False, net_ret=np.nan,
                      entry_date=pd.NaT, exit_date=pd.NaT, drop=None)

            if car_01 <= TRIGGER_CAR:
                funnel['triggered'] += 1
                ev['triggered'] = True
                if not (np.isfinite(turn[ep]) and turn[ep] >= MIN_TURNOVER_LACS
                        and np.isfinite(aclose[ep]) and aclose[ep] >= MIN_PRICE):
                    funnel['gate_failed'] += 1
                    ev['drop'] = 'liquidity gate at E'
                elif ep + ENTRY_OFFSET + HOLD_DAYS >= n:
                    funnel['no_entry_exit'] += 1
                    ev['drop'] = 'no E+2 / E+12 bar'
                else:
                    o_in = aopen[ep + ENTRY_OFFSET]
                    o_out = aopen[ep + ENTRY_OFFSET + HOLD_DAYS]
                    if not (np.isfinite(o_in) and np.isfinite(o_out) and o_in > 0 and o_out > 0):
                        funnel['no_entry_exit'] += 1
                        ev['drop'] = 'non-finite entry/exit open'
                    else:
                        buy_px = o_in * (1 + SLIP)
                        sell_px = o_out * (1 - SLIP)
                        qty = int(TRADE_NOTIONAL // buy_px)
                        if qty < 1:
                            funnel['no_entry_exit'] += 1
                            ev['drop'] = f'notional {TRADE_NOTIONAL:.0f} buys < 1 share at {buy_px:.2f}'
                        else:
                            buy_v, sell_v = qty * buy_px, qty * sell_px
                            fees = zerodha_charges.calculate_charges(
                                buy_v, sell_v, is_intraday=False)['total']
                            ev['traded'] = True
                            ev['net_ret'] = (sell_v - buy_v - fees) / buy_v
                            ev['entry_date'] = pd.Timestamp(sdates[ep + ENTRY_OFFSET])
                            ev['exit_date'] = pd.Timestamp(sdates[ep + ENTRY_OFFSET + HOLD_DAYS])
                            funnel['trades'] += 1
            events.append(ev)
    return pd.DataFrame(events), funnel


# ---------------------------------------------------------------------------
# Clustering + cluster-robust t
# ---------------------------------------------------------------------------
def cluster_keys(df):
    """PRIMARY cluster key: the calendar month of that IPO's EARLIEST unlock,
    applied to both of its events. Satisfies both frozen sentences without the
    degeneration of the union-find alternative (see module docstring)."""
    anchor = df.sort_values('unlock_date').groupby('symbol')['unlock_month'].first()
    return df['symbol'].map(anchor)


def cluster_t(x, clusters):
    """t = mean / sqrt(V), V = (G/(G-1)) * (1/N^2) * sum_g (sum_i resid)^2."""
    x = np.asarray(x, dtype=float)
    n = len(x)
    if n < 2:
        return np.nan, (1 if n else 0)
    mean = x.mean()
    resid = x - mean
    s = pd.Series(resid).groupby(np.asarray(clusters)).sum().to_numpy()
    G = len(s)
    if G < 2:
        return np.nan, G
    V = (G / (G - 1.0)) * (s ** 2).sum() / (n ** 2)
    return (mean / np.sqrt(V) if V > 0 else np.nan), G


def describe(x, clusters_anchor, clusters_month, clusters_ipo, label, pct=True):
    x = np.asarray(x, dtype=float)
    n = len(x)
    if n == 0:
        log(f'  {label:32}: N=0')
        return None
    mul = 100.0 if pct else 1.0
    t_an, g_an = cluster_t(x, clusters_anchor)
    t_mo, g_mo = cluster_t(x, clusters_month)
    t_ip, g_ip = cluster_t(x, clusters_ipo)
    sd = x.std(ddof=1) * mul if n > 1 else float('nan')
    log(f'  {label:32}: N={n:4}  mean={x.mean() * mul:+7.3f}%  median={np.median(x) * mul:+7.3f}%  '
        f'sd={sd:6.3f}%  win={100 * (x > 0).mean():5.1f}%')
    log(f'  {"":32}  PRIMARY t(anchor-month,G={g_an})={t_an:+.3f}   '
        f'[diag: t(event-month,G={g_mo})={t_mo:+.3f}, t(IPO,G={g_ip})={t_ip:+.3f}]')
    return dict(n=n, mean=x.mean(), median=float(np.median(x)),
                win=float((x > 0).mean()), t=t_an, G=g_an)


# ---------------------------------------------------------------------------
# Reporting
# ---------------------------------------------------------------------------
def print_header(smoke):
    log('=' * 100)
    log('IPO ANCHOR-INVESTOR LOCK-IN UNLOCK STUDY (pre-registered, FROZEN)')
    log('Spec: docs/superpowers/specs/2026-07-28-ipo-anchor-unlock-design.md')
    log('=' * 100)
    log('')
    log('FROZEN RULES (restated before any results below were computed):')
    log('  Regulatory pin (R1, primary source -- SEBI gazette notification, not a news write-up):')
    log('    SEBI (ICDR) (Amendment) Regulations, 2022, notified 2022-01-14.')
    log('    https://www.sebi.gov.in/legal/regulations/jan-2022/securities-and-exchange-board-of-india'
        '-issue-of-capital-and-disclosure-requirements-amendment-regulations-2022_55351.html')
    log('    https://www.sebi.gov.in/sebi_data/attachdocs/jan-2022/1642395606006.pdf')
    log('    Schedule XIII Part A clause (10)(j) substituted: "There shall be a lock-in of 90 days on')
    log('    fifty per cent of the shares allotted to the anchor investors from the date of allotment,')
    log('    and a lock-in of 30 days on the remaining fifty per cent ...".')
    log('    Commencement proviso names clause (10) of Part A of Schedule XIII and says it "shall come')
    log('    into force from April 1, 2022, FOR ISSUES OPENING ON OR AFTER APRIL 1, 2022".')
    log(f'    => EFFECTIVE DATE PINNED: issues opening on/after {SEBI_ISSUE_OPEN_EFFECTIVE.date()}.')
    log('  Era split on LISTING date (approximation, listing ~= issue_open + 10-14 calendar days under')
    log(f'    the T+6 timeline then in force): PRE = listing < {SEBI_ISSUE_OPEN_EFFECTIVE.date()}; '
        f'AMBIGUOUS = [{SEBI_ISSUE_OPEN_EFFECTIVE.date()}, {ERA_AMBIGUOUS_END.date()});')
    log(f'    POST = listing >= {ERA_AMBIGUOUS_END.date()}. AMBIGUOUS gets NO +90 event, is included in')
    log('    pooled stats (criteria 2/3) and excluded from the per-era cells (criterion 1).')
    log('  Listings : first appearance in ANY series in data/bhavcopy_full; >= 60 forward trading days;')
    log('             exclusions PANEL_EDGE / RIGHTS_ENTITLEMENT / NON_MAINBOARD_SERIES / FUND_OR_ETF /')
    log('             RENAME_TWIN_PRICE / RENAME_TWIN_NAME / CORP_ACTION_SCHEME / NO_ISSUE_PRICE /')
    log('             SME_LIQUIDITY / BAD_LISTING_PRICES / INSUFFICIENT_FORWARD (all listed below).')
    log(f'  Unlocks  : listing + {UNLOCK_30} and (POST era only) listing + {UNLOCK_90} CALENDAR days, '
        f'rolled to the next trading day.')
    log('             KNOWN BIAS: lock-in runs from ALLOTMENT (~2-4 days before listing); the spec')
    log('             freezes the listing-date anchor, so the modelled unlock sits a few days late.')
    log(f'  Windows  : info [-{PRE_WINDOW},-1] and [0,+1], abnormal vs EW daily-rebalanced frictionless')
    log(f'             universe (EQ, turnover >= Rs {MIN_TURNOVER_LACS / 100:.0f}cr, adj close >= Rs '
        f'{MIN_PRICE:.0f}), returns clipped +/-{CLIP:.0%}. No verdict weight.')
    log(f'  PRIMARY  : IF [0,+1] cumulative abnormal <= {TRIGGER_CAR:+.1%} AND liquidity gate holds at E,')
    log(f'             BUY E+{ENTRY_OFFSET} OPEN, hold {HOLD_DAYS} trading days, EXIT E+'
        f'{ENTRY_OFFSET + HOLD_DAYS} OPEN.')
    log(f'  Costs    : {SLIP:.1%}/side slippage on the fill price + zerodha_charges.calculate_charges(')
    log("             buy_v, sell_v, is_intraday=False)['total'] (never sum(.values()) -- double-counts).")
    log(f'             Fixed notional Rs {TRADE_NOTIONAL:,.0f}/trade (the DP charge is FLAT, so net %')
    log('             return depends on trade size -- stated, not tuned).')
    log('  Verdict  : ALL THREE must hold --')
    log(f'             1) mean net > 0 in BOTH eras, each with >= {MIN_TRADES_PER_ERA} trades')
    log(f'                (< {MIN_TRADES_PER_ERA} => that era is NODATA/underpowered, a recorded OUTCOME,')
    log('                 not a pass)')
    log(f'             2) pooled cluster-robust t >= {T_BAR:+.1f}')
    log(f'             3) win rate >= {WIN_RATE_BAR:.0%}')
    log('  Clusters : PRIMARY = anchor-month (calendar month of that IPO\'s EARLIEST unlock, applied to')
    log('             both of its events) -- satisfies both frozen sentences ("calendar month of the')
    log('             unlock" AND "the two unlocks of one IPO share a cluster") without degenerating.')
    log('             The union-find alternative was tried and REJECTED: overlapping IPO waves chain')
    log('             every month together (G=1). Event-month and by-IPO t printed as diagnostics only.')
    log('  Declared test count: 1 (the conditional long leg). Everything else is information only.')
    if smoke:
        log('')
        log(f'  *** SMOKE MODE: restricted to listings in calendar {SMOKE_YEAR} only. ***')
        log('  *** No verdict is computed or printed in smoke mode. ***')
    log('')


def report_detector(n_raw, keep, excl, warn_fund, warn_related):
    log('=' * 100)
    log('LISTING DETECTOR')
    log('=' * 100)
    log(f'Raw first-appearance symbols in panel : {n_raw}')
    log(f'Excluded                              : {len(excl)}')
    log(f'Qualifying listings                   : {len(keep)}')
    log('')
    log('Exclusions by primary reason (first matching rule wins; a symbol can trip several):')
    counts = excl['reason'].value_counts()
    for reason, c in counts.items():
        log(f'  {reason:24} {c:6}')
    log('')
    log('Top 10 exclusion examples per reason (symbol | listing date | reason detail):')
    for reason in counts.index:
        sub = excl[excl['reason'] == reason].sort_values('listing_date')
        log(f'  --- {reason} (n={len(sub)}) ---')
        for _, r in sub.head(10).iterrows():
            log(f'      {r["symbol"]:<14} {r["listing_date"].date()}  {r["detail"]}')
    log('')
    log('REVIEWER WARNINGS (info only -- these symbols were KEPT):')
    log(f'  (a) survivors matching the broad fund-name regex but NOT in the curated FUND_EXCLUSIONS set')
    log(f'      -- the curated set is the weakest heuristic in this file, so its gap is made explicit.')
    log(f'      n={len(warn_fund)}: {", ".join(warn_fund) if warn_fund else "(none)"}')
    log(f'  (b) survivors sharing a >= {TWIN_NAME_PREFIX}-char prefix with a still-trading pre-panel symbol')
    log('      (possible group / demerger listing; NOT excluded, see module docstring for why).')
    log(f'      n={len(warn_related)}: '
        + (', '.join(f'{s}~{p}' for s, (p, _) in sorted(warn_related.items())) if warn_related else '(none)'))
    log('')
    eras = keep['listing_date'].map(era_of).value_counts()
    log('Qualifying listings by regulatory era: '
        + ', '.join(f'{k}={eras.get(k, 0)}' for k in (ERA_PRE, ERA_AMBIG, ERA_POST)))
    log('Qualifying listings by year         : '
        + ', '.join(f'{y}={c}' for y, c in sorted(keep['listing_date'].dt.year.value_counts().items())))
    log('')


def report_events(ev, funnel):
    log('=' * 100)
    log('EVENT FUNNEL')
    log('=' * 100)
    for k, v in funnel.items():
        log(f'  {k:26} {v:7}')
    log('')
    if ev.empty:
        log('No usable unlock events -- nothing further to report.')
        return None

    ev = ev.copy()
    # Computed ONCE on the full event frame so an IPO's anchor month is a
    # property of the IPO, not of whichever subset is being printed.
    ev['cl_anchor'] = cluster_keys(ev)
    log('=' * 100)
    log('INFORMATION WINDOWS (abnormal vs EW universe) -- NO VERDICT WEIGHT')
    log('=' * 100)
    log('  CAVEAT, stated before the numbers: newly listed Indian IPOs are known to underperform the')
    log('  broad market over their first months regardless of any unlock. The spec defines no non-unlock')
    log('  control window, so a negative [-5,-1] or [0,+1] abnormal return here CANNOT be attributed to')
    log('  the unlock as opposed to general post-IPO drift. These windows are descriptive only; the')
    log('  verdict rests solely on the conditional long leg below.')
    log('')
    for era_label, sub in [('ALL', ev)] + [(e, ev[ev['era'] == e]) for e in (ERA_PRE, ERA_AMBIG, ERA_POST)]:
        if sub.empty:
            log(f'  [{era_label}] no events')
            continue
        log(f'  [{era_label}] n={len(sub)} events '
            f'({(sub["unlock_tag"] == "U30").sum()} x +30d, {(sub["unlock_tag"] == "U90").sum()} x +90d), '
            f'{sub["symbol"].nunique()} IPOs')
        cu, cm, ci = sub['cl_anchor'], sub['unlock_month'], sub['symbol']
        describe(sub['car_pre'], cu, cm, ci, 'CAR [-5,-1] pre-unlock drift')
        describe(sub['car_01'], cu, cm, ci, 'CAR [0,+1] unlock reaction')
        log(f'  {"":32}: trigger rate ([0,+1] <= {TRIGGER_CAR:+.1%}) = '
            f'{100 * (sub["car_01"] <= TRIGGER_CAR).mean():.1f}%')
        log('')
    for tag in ('U30', 'U90'):
        sub = ev[ev['unlock_tag'] == tag]
        if sub.empty:
            continue
        log(f'  [by unlock type: {tag}] n={len(sub)}')
        describe(sub['car_01'], sub['cl_anchor'], sub['unlock_month'], sub['symbol'], 'CAR [0,+1]')
        log('')

    log('=' * 100)
    log('PRIMARY LEG -- conditional post-unlock long (THE ONE DECLARED TEST)')
    log('=' * 100)
    tr = ev[ev['traded']].copy()
    if tr.empty:
        log('  No trades fired.')
        return None
    stats = {}
    for era_label, sub in [('POOLED (incl AMBIGUOUS)', tr)] + \
                          [(e, tr[tr['era'] == e]) for e in (ERA_PRE, ERA_AMBIG, ERA_POST)]:
        if sub.empty:
            log(f'  [{era_label}] N=0 trades')
            stats[era_label] = None
            continue
        log(f'  [{era_label}] {sub["symbol"].nunique()} IPOs, '
            f'{(sub["unlock_tag"] == "U30").sum()} x +30d / {(sub["unlock_tag"] == "U90").sum()} x +90d')
        stats[era_label] = describe(sub['net_ret'], sub['cl_anchor'], sub['unlock_month'],
                                    sub['symbol'], 'NET trade return (after costs)')
        log('')
    log('  First 15 trades (symbol | era | unlock | E | entry | exit | CAR[0,+1] | net):')
    for _, r in tr.sort_values('unlock_date').head(15).iterrows():
        log(f'    {r["symbol"]:<12} {r["era"]:<9} {r["unlock_tag"]} {r["unlock_date"].date()} '
            f'{r["entry_date"].date()} {r["exit_date"].date()} '
            f'{r["car_01"] * 100:+7.2f}% {r["net_ret"] * 100:+7.2f}%')
    log('')
    return stats


def print_verdict(stats):
    log('=' * 100)
    log('VERDICT (frozen criteria)')
    log('=' * 100)
    if stats is None:
        log('  Cannot compute -- no trades.')
        log('  OVERALL: FAIL (no evidence) -> dead, recorded, no re-tuning.')
        return False
    pre, post, pooled = stats.get(ERA_PRE), stats.get(ERA_POST), stats.get('POOLED (incl AMBIGUOUS)')

    def era_line(name, s):
        if s is None or s['n'] < MIN_TRADES_PER_ERA:
            n = 0 if s is None else s['n']
            log(f'     {name:5}: N={n} < {MIN_TRADES_PER_ERA} -> NODATA / UNDERPOWERED (recorded outcome)')
            return False
        ok = s['mean'] > 0
        log(f'     {name:5}: N={s["n"]}  mean={s["mean"] * 100:+.3f}%  -> {"PASS" if ok else "FAIL"}')
        return ok

    log(f'  1. Mean net > 0 in BOTH eras, each with >= {MIN_TRADES_PER_ERA} trades:')
    c1 = era_line(ERA_PRE, pre) & era_line(ERA_POST, post)
    log(f'     -> criterion 1: {"PASS" if c1 else "FAIL"}')
    t = pooled['t'] if pooled else float('nan')
    c2 = bool(pooled) and np.isfinite(t) and t >= T_BAR
    log(f'  2. Pooled cluster-robust t >= {T_BAR:+.1f} (anchor-month clusters): '
        f'{t:+.3f} -> {"PASS" if c2 else "FAIL"}')
    w = pooled['win'] if pooled else float('nan')
    c3 = bool(pooled) and w >= WIN_RATE_BAR
    log(f'  3. Win rate >= {WIN_RATE_BAR:.0%}: {w:.1%} -> {"PASS" if c3 else "FAIL"}')
    overall = bool(c1 and c2 and c3)
    log('')
    log(f'  OVERALL: {"PASS -> earns a phase-2 spec discussion (not a deployment)" if overall else "FAIL -> dead, recorded, no re-tuning"}')
    return overall


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------
def main():
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument('--smoke', action='store_true',
                    help=f'Restrict to listings in calendar {SMOKE_YEAR}, write to a separate '
                         f'_smoke.txt, print no verdict.')
    args = ap.parse_args()

    print_header(args.smoke)

    allp = load_panel()
    price = build_price_frame(allp)
    corp_actions = load_corp_actions()
    halt_on_unresolved_nan_factors(price, corp_actions)
    price = apply_corp_action_adjustments(price, corp_actions)
    price, all_dates, P = build_benchmark(price)
    log('')

    n_raw, keep, excl, warn_fund, warn_related = detect_listings(allp, price, all_dates, corp_actions)
    report_detector(n_raw, keep, excl, warn_fund, warn_related)

    ev, funnel = build_events(keep, price, all_dates, P, args.smoke)
    stats = report_events(ev, funnel)

    if args.smoke:
        log('')
        log('NO VERDICT IN SMOKE MODE (per spec -- smoke is a plumbing check only, not evidence).')
        out = OUT_DIR / 'ipo_anchor_unlock_results_smoke.txt'
    else:
        print_verdict(stats)
        out = OUT_DIR / 'ipo_anchor_unlock_results.txt'
    flush_out(out)
    log(f'\n[saved output to {out}]')


if __name__ == '__main__':
    main()
