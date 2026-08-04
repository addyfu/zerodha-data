"""Regime Exit on the Buy-and-Hold Core -- study (pre-registered, FROZEN).

FROZEN SPEC (read this first, do not deviate without a spec amendment):
    docs/superpowers/specs/2026-08-04-regime-exit-design.md
    Status: FROZEN (2026-08-04). Origin: shortlist candidate D,
    docs/superpowers/specs/2026-08-04-entries-exits-research-shortlist.md.

WHAT THIS IS
------------
Tests whether exiting NIFTY buy-and-hold to cash when the index is below its
200-day moving average beats plain buy-and-hold, after transaction costs AND
Indian capital-gains tax on every exit. Stated prior (shortlist, verbatim):
"industry-mined to death ... Expected verdict: FAIL." This script exists to
run that funeral properly, not to save the idea -- nothing here is tuned
after seeing a result; every constant below is copied verbatim from the
frozen spec.

TWO VARIANTS ONLY (frozen):
    V1  monthly check: at each month's last close, cash if close < MA200
        else invested.
    V2  daily check, 1% hysteresis band: exit when close < 0.99*MA200,
        re-enter when close > 1.01*MA200, hold state inside the band.
    BH  buy-and-hold benchmark: always invested, pays LTCG once at the end.

MODES
-----
    python kite/research/regime_exit_study.py --fetch
        Fetches NIFTY 50 (^NSEI) daily closes from yfinance, caches to
        kite/research/regime_exit_cache.csv, prints the range obtained.
        No self-check, no simulation.

    python kite/research/regime_exit_study.py
        Runs the self-check (halts on any failed assert), then the full
        study (fetches from cache if present, else fetches fresh), writes
        kite/research/regime_exit_results.txt.

    python kite/research/regime_exit_study.py --selfcheck-only
        Runs only the self-check, no data fetch, no simulation. For fast
        iteration on the switching/tax logic.

COST + TAX CONSTANTS (verbatim from the frozen spec -- do not tune)
---------------------------------------------------------------------------
Costs, per side, on every switch:
    SELL (exit):    slippage 0.05% + STT 0.1% + exchange/SEBI 0.00317%
                    = 0.15317% of transacted value
    BUY (re-entry
    or initial):    slippage 0.05% + STT 0.1% + stamp duty 0.015%
                    (buy-side only) + exchange/SEBI 0.00317%
                    = 0.16817% of transacted value
    The initial purchase (day one, all three lines) pays the BUY side once,
    same as any other entry -- it is a real transaction with real costs even
    though it is not a "switch" away from a prior state.
Taxes (verified 2026-08-04 against the Income Tax Department's Section 112A
page + 3 independent reputable secondary sources -- see spec decision log):
    LTCG (holding_days > 365):  12.5%   (Section 112A)
    STCG (holding_days <= 365): 20.0%   (Section 111A)
    No cess/surcharge, no annual Rs 1.25L LTCG exemption, no loss carry-
    forward -- all three stated as simplifications in the frozen spec, and
    the exemption omission is a bias AGAINST the switching variants (see
    spec "Taxes" section).
Cash yield while out of the market: 0% (frozen, stated bias AGAINST the
switching variants -- see spec "Cash yield" section). Cash legs never grow.

IMPLEMENTATION CHOICES THE SPEC DOES NOT FULLY PIN DOWN (flagged, not buried)
------------------------------------------------------------------------------
(1) GAIN FOR TAX PURPOSES is computed on an economic-P&L basis: cost basis =
    capital actually deployed after buy-side costs; sale proceeds = cash
    actually received after sell-side costs; gain = proceeds - basis. Spec
    states this explicitly (not a silent choice) and notes it sidesteps a
    genuinely disputed question in Indian tax practice (is STT deductible
    from sale consideration for 111A/112A purposes) that has no bearing on
    which variant wins -- it would move rupees between the "cost" and "tax"
    buckets identically for all three lines.
(2) MARK-TO-MARKET (MTM) NOTIONAL TAX AT ERA BOUNDARIES: any position that
    is still open (not yet really sold) as of an era-boundary reporting
    date is valued at gross unrealized value minus a NOTIONAL tax (same
    LTCG/STCG rate, same >365-day rule, on any positive unrealized gain
    only) -- a paper number for reporting, not a real cash event. Applied
    uniformly to BH, V1, and V2 at every era boundary except GLOBAL_END,
    where BH alone gets a real one-time liquidation (sell-side cost + real
    tax) per the spec's literal "buy-and-hold pays LTCG once at the end."
    V1/V2 are never force-liquidated -- if either is mid-holding at
    GLOBAL_END, that boundary uses the same MTM convention as every other
    era boundary for them (they are ongoing strategies, not wound up on the
    study's last day). Full rationale in the spec's "Eras" section -- this
    choice exists because the naive alternative (dump BH's entire multi-
    decade tax bill onto whichever era happens to contain GLOBAL_END) would
    make BH look artificially undamaged in early eras and artificially
    crushed in the last one, a pure accounting artifact that could hand
    V1/V2 a false win in whichever era eats the lump sum. MTM avoids that.
(3) INITIAL STATE AT GLOBAL_START: V1 and V2 apply their OWN rule on day one
    (V1: treated as its first decision point regardless of whether it is a
    literal month-end; V2: applies the exit/re-entry thresholds directly,
    defaulting to invested if GLOBAL_START's close falls inside the dead
    band with no prior state to hold). BH always starts invested (it has no
    rule). On the actual data (probed 2026-08-04), GLOBAL_START = 2008-07-07
    lands mid-way through the 2008 crash with close well below MA200, so V1
    and V2 both start in CASH -- a real, non-contrived exercise of this
    rule, not an edge case that never fires.
(4) STOOQ FALLBACK NOT USABLE (matches the overnight-postopen study's
    finding): re-probed 2026-08-04, still returns an anti-bot JS challenge
    page, not real data. yfinance ^NSEI is the sole source, exactly as the
    spec's own text allows.

Usage:
    python kite/research/regime_exit_study.py --fetch
    python kite/research/regime_exit_study.py --selfcheck-only
    python kite/research/regime_exit_study.py
"""
import argparse
import sys
from pathlib import Path

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parents[2]
SPEC = 'docs/superpowers/specs/2026-08-04-regime-exit-design.md'
OUT_DIR = Path(__file__).resolve().parent
CACHE_FILE = OUT_DIR / 'regime_exit_cache.csv'
OUT_FILE = OUT_DIR / 'regime_exit_results.txt'

# ===========================================================================
# FROZEN CONSTANTS -- verbatim from the spec, do not tune
# ===========================================================================
MA_WINDOW = 200
HYSTERESIS_BAND = 0.01          # 1%

SLIPPAGE_PCT = 0.0005           # 0.05%/side
STT_PCT = 0.001                 # 0.1%, both sides
STAMP_DUTY_BUY_PCT = 0.00015    # 0.015%, buy side only
EXCH_SEBI_PCT = 0.0000317       # ~0.00317%, both sides

SELL_COST_PCT = SLIPPAGE_PCT + STT_PCT + EXCH_SEBI_PCT                      # 0.15317%
BUY_COST_PCT = SLIPPAGE_PCT + STT_PCT + STAMP_DUTY_BUY_PCT + EXCH_SEBI_PCT  # 0.16817%

LTCG_RATE = 0.125               # 12.5%, Section 112A
STCG_RATE = 0.20                # 20.0%, Section 111A
LTCG_HOLDING_DAYS = 365         # holding_days > 365 -> LTCG, else STCG

CASH_YIELD = 0.0                # frozen, stated bias against V1/V2 -- cash legs never grow

ERA_DEFS = [
    ('2005-2015', pd.Timestamp('2005-01-01'), pd.Timestamp('2015-12-31')),
    ('2016-2020', pd.Timestamp('2016-01-01'), pd.Timestamp('2020-12-31')),
    ('2021-present', pd.Timestamp('2021-01-01'), None),  # None -> GLOBAL_END
]

_LINES = []


def log(msg=''):
    print(msg, flush=True)
    _LINES.append(str(msg))


def flush_out(path):
    path.write_text('\n'.join(_LINES) + '\n', encoding='utf-8')


def pct(x, nd=3):
    return 'n/a' if x is None or not np.isfinite(x) else f'{x * 100:+.{nd}f}%'


# ===========================================================================
# DATA FETCH / CACHE
# ===========================================================================
def fetch_nifty_daily():
    """yfinance ^NSEI daily close, auto_adjust=True. Sole source (stooq
    re-confirmed non-viable, see module docstring point 4)."""
    import yfinance as yf
    t = yf.Ticker('^NSEI')
    end = (pd.Timestamp.today() + pd.Timedelta(days=1)).strftime('%Y-%m-%d')
    h = t.history(start='1990-01-01', end=end, auto_adjust=True)
    if h is None or h.empty or 'Close' not in h.columns:
        sys.exit('HALTED: yfinance ^NSEI returned empty/invalid history. Per task instructions: STOP, do not '
                  'substitute a different index without flagging.')
    idx = pd.DatetimeIndex([pd.Timestamp(ts.date()) for ts in h.index])
    close = pd.Series(h['Close'].to_numpy(dtype=float), index=idx, name='close')
    close = close[~close.index.duplicated(keep='last')].sort_index()
    close = close[np.isfinite(close.to_numpy())]
    if len(close) < MA_WINDOW + 100:
        sys.exit(f'HALTED: only {len(close)} usable NIFTY daily rows returned -- too few to run a 200-day '
                  f'MA study meaningfully.')
    return close


def load_or_fetch(force_fetch=False):
    if not force_fetch and CACHE_FILE.exists():
        df = pd.read_csv(CACHE_FILE, parse_dates=['date'])
        close = pd.Series(df['close'].to_numpy(dtype=float), index=pd.DatetimeIndex(df['date']), name='close')
        return close, 'yfinance ^NSEI [cache]'
    close = fetch_nifty_daily()
    close.rename_axis('date').reset_index(name='close').to_csv(CACHE_FILE, index=False)
    return close, 'yfinance ^NSEI [fresh fetch]'


# ===========================================================================
# CORE SWITCHING / TAX / COST ENGINE
# ===========================================================================
def realize_exit(entry_nav, entry_price, entry_date, exit_price, exit_date,
                  sell_cost_pct=SELL_COST_PCT, ltcg_rate=LTCG_RATE, stcg_rate=STCG_RATE,
                  ltcg_days=LTCG_HOLDING_DAYS):
    """Sell an ALREADY-OPEN position. `entry_nav` is the cost basis, already
    net of buy-side cost (applied once, when the position was opened -- not
    re-applied here). Returns gross_value, sale_proceeds (net of sell cost),
    gain, holding_days, is_ltcg, tax, cash_after. A loss pays zero tax (no
    rebate, no carry-forward -- frozen simplification)."""
    ratio = exit_price / entry_price
    gross_value = entry_nav * ratio
    sale_proceeds = gross_value * (1 - sell_cost_pct)
    gain = sale_proceeds - entry_nav
    holding_days = (exit_date - entry_date).days
    is_ltcg = holding_days > ltcg_days
    rate = ltcg_rate if is_ltcg else stcg_rate
    tax = max(gain, 0.0) * rate
    cash_after = sale_proceeds - tax
    return {
        'entry_nav': entry_nav, 'entry_price': entry_price, 'entry_date': entry_date,
        'exit_price': exit_price, 'exit_date': exit_date, 'gross_value': gross_value,
        'sale_proceeds': sale_proceeds, 'gain': gain, 'holding_days': holding_days,
        'is_ltcg': is_ltcg, 'tax': tax, 'cash_after': cash_after,
    }


def close_segment(cash_before, entry_price, entry_date, exit_price, exit_date,
                   buy_cost_pct=BUY_COST_PCT, sell_cost_pct=SELL_COST_PCT,
                   ltcg_rate=LTCG_RATE, stcg_rate=STCG_RATE, ltcg_days=LTCG_HOLDING_DAYS):
    """Self-check convenience only: a FULL round trip from raw un-invested
    cash -- buy (pay buy-side cost) then sell (pay sell-side cost + tax) in
    one call. Production bookkeeping (Legs, below) never calls this: it
    applies the buy-side cost once at leg-open time and calls realize_exit()
    directly at leg-close time, because in production the two events can be
    years apart and start_nav is already net of the buy-side cost by the
    time a sell happens."""
    entry_nav = cash_before * (1 - buy_cost_pct)
    return realize_exit(entry_nav, entry_price, entry_date, exit_price, exit_date,
                         sell_cost_pct, ltcg_rate, stcg_rate, ltcg_days)


def mtm_value(entry_nav, entry_price, entry_date, asof_price, asof_date,
              ltcg_rate=LTCG_RATE, stcg_rate=STCG_RATE, ltcg_days=LTCG_HOLDING_DAYS):
    """Mark-to-market notional after-tax value of a STILL-OPEN position as
    of `asof_date` -- no transaction cost (no real trade happened), notional
    tax only on a positive unrealized gain, same >365-day rule. See module
    docstring implementation choice (2)."""
    ratio = asof_price / entry_price
    gross_value = entry_nav * ratio
    holding_days = (asof_date - entry_date).days
    is_ltcg = holding_days > ltcg_days
    rate = ltcg_rate if is_ltcg else stcg_rate
    notional_gain = gross_value - entry_nav
    notional_tax = max(notional_gain, 0.0) * rate
    return gross_value - notional_tax


class Legs:
    """A chronological list of legs (invested or cash) for one strategy.
    Each leg: kind, start_date, end_date (exclusive; None = still open),
    start_nav (cash value AT leg start, already net of any buy-side cost
    for an invested leg), start_price (invested legs only).
    `value_asof(date)` returns the MTM-consistent after-tax NAV at any
    date -- flat for a cash leg, mark-to-market for an invested leg --
    used uniformly for era-boundary reporting (docstring choice 2)."""

    def __init__(self):
        self.legs = []          # list of dicts, chronological
        self.trades = []        # list of realize_exit() results (real exits only)
        self.n_buys = 0
        self.n_sells = 0

    def start(self, kind, date, nav, price=None):
        assert not self.legs or self.legs[-1]['end_date'] is not None, 'previous leg not closed'
        self.legs.append({'kind': kind, 'start_date': date, 'end_date': None,
                          'start_nav': nav, 'start_price': price})
        if kind == 'invested':
            self.n_buys += 1

    def close_current(self, date):
        self.legs[-1]['end_date'] = date

    def switch_to_cash(self, price_lookup, exit_date, sell_cost_pct=SELL_COST_PCT,
                        ltcg_rate=LTCG_RATE, stcg_rate=STCG_RATE, ltcg_days=LTCG_HOLDING_DAYS):
        cur = self.legs[-1]
        assert cur['kind'] == 'invested', 'switch_to_cash called while not invested'
        exit_price = price_lookup(exit_date)
        trade = realize_exit(cur['start_nav'], cur['start_price'], cur['start_date'], exit_price, exit_date,
                              sell_cost_pct, ltcg_rate, stcg_rate, ltcg_days)
        self.trades.append(trade)
        self.n_sells += 1
        self.close_current(exit_date)
        self.start('cash', exit_date, trade['cash_after'])

    def switch_to_invested(self, price_lookup, entry_date, buy_cost_pct=BUY_COST_PCT):
        cur = self.legs[-1]
        assert cur['kind'] == 'cash', 'switch_to_invested called while not in cash'
        entry_price = price_lookup(entry_date)
        entry_nav = cur['start_nav'] * (1 - buy_cost_pct)   # cur['start_nav'] is plain idle cash here
        self.close_current(entry_date)
        self.start('invested', entry_date, entry_nav, price=entry_price)

    def value_asof(self, price_lookup, date):
        leg = None
        for cand in self.legs:
            if cand['start_date'] <= date and (cand['end_date'] is None or date < cand['end_date']):
                leg = cand
                break
        if leg is None:
            leg = self.legs[0] if date < self.legs[0]['start_date'] else self.legs[-1]
        if leg['kind'] == 'cash':
            return leg['start_nav']   # idle at CASH_YIELD (frozen 0%) -- flat, never grows
        price_now = price_lookup(date)
        return mtm_value(leg['start_nav'], leg['start_price'], leg['start_date'], price_now, date)

    def state_at(self, date):
        for cand in self.legs:
            if cand['start_date'] <= date and (cand['end_date'] is None or date < cand['end_date']):
                return cand['kind']
        return None


def simulate_periodic(dates, closes, ma, check_dates, price_lookup, buy_cost_pct=BUY_COST_PCT,
                       sell_cost_pct=SELL_COST_PCT, ltcg_rate=LTCG_RATE, stcg_rate=STCG_RATE,
                       ltcg_days=LTCG_HOLDING_DAYS):
    """V1 engine: state decided ONLY at `check_dates` (chronological subset
    of `dates`); each check compares that SAME date's own close to that
    date's own MA (no lag). Initial state decided by applying the identical
    rule directly at dates[0] (GLOBAL_START), whether or not it is itself a
    check date -- docstring choice (3)."""
    L = Legs()
    d0 = dates[0]
    invested0 = not (closes[0] < ma[0])   # frozen rule: cash iff close < MA200, else invested
    if invested0:
        L.start('invested', d0, 1.0 * (1 - buy_cost_pct), price=closes[0])
    else:
        L.start('cash', d0, 1.0)
    idx_by_date = {d: i for i, d in enumerate(dates)}
    for cd in check_dates:
        if cd <= d0:
            continue
        i = idx_by_date[cd]
        want_invested = not (closes[i] < ma[i])
        cur = L.state_at(cd)
        if want_invested and cur == 'cash':
            L.switch_to_invested(price_lookup, cd, buy_cost_pct=buy_cost_pct)
        elif (not want_invested) and cur == 'invested':
            L.switch_to_cash(price_lookup, cd, sell_cost_pct=sell_cost_pct, ltcg_rate=ltcg_rate,
                              stcg_rate=stcg_rate, ltcg_days=ltcg_days)
    return L


def simulate_hysteresis(dates, closes, ma, band, price_lookup, buy_cost_pct=BUY_COST_PCT,
                         sell_cost_pct=SELL_COST_PCT, ltcg_rate=LTCG_RATE, stcg_rate=STCG_RATE,
                         ltcg_days=LTCG_HOLDING_DAYS):
    """V2 engine: every day, exit when close < (1-band)*MA200, re-enter when
    close > (1+band)*MA200, hold state inside the band. Initial state at
    dates[0] per docstring choice (3): invested unless dates[0]'s close is
    strictly below the lower band (default-invested inside/above the band
    on day one, since there is no prior state to hold)."""
    L = Legs()
    d0 = dates[0]
    lower0 = (1 - band) * ma[0]
    invested0 = not (closes[0] < lower0)
    if invested0:
        L.start('invested', d0, 1.0 * (1 - buy_cost_pct), price=closes[0])
    else:
        L.start('cash', d0, 1.0)
    for i in range(1, len(dates)):
        d = dates[i]
        lower, upper = (1 - band) * ma[i], (1 + band) * ma[i]
        cur = L.state_at(d)
        if cur == 'invested' and closes[i] < lower:
            L.switch_to_cash(price_lookup, d, sell_cost_pct=sell_cost_pct, ltcg_rate=ltcg_rate,
                              stcg_rate=stcg_rate, ltcg_days=ltcg_days)
        elif cur == 'cash' and closes[i] > upper:
            L.switch_to_invested(price_lookup, d, buy_cost_pct=buy_cost_pct)
    return L


def build_bh(dates, closes, buy_cost_pct=BUY_COST_PCT):
    L = Legs()
    L.start('invested', dates[0], 1.0 * (1 - buy_cost_pct), price=closes[0])
    return L


def realize_bh_final(L, price_lookup, final_date, sell_cost_pct=SELL_COST_PCT,
                      ltcg_rate=LTCG_RATE, stcg_rate=STCG_RATE, ltcg_days=LTCG_HOLDING_DAYS):
    """The one special-cased literal end-of-series liquidation, BH only.
    Real sell-side cost + real tax (certainly LTCG by GLOBAL_END, given the
    study spans decades). Does not mutate L. Returns
    (final_nav, gain, tax, holding_days)."""
    leg = L.legs[-1]
    assert leg['kind'] == 'invested' and leg['end_date'] is None, 'BH must still be open at GLOBAL_END'
    final_price = price_lookup(final_date)
    trade = realize_exit(leg['start_nav'], leg['start_price'], leg['start_date'], final_price, final_date,
                          sell_cost_pct, ltcg_rate, stcg_rate, ltcg_days)
    return trade['cash_after'], trade['gain'], trade['tax'], trade['holding_days']


# ===========================================================================
# SELF-CHECK (plain asserts, hand-computable synthetic cases)
# ===========================================================================
def selfcheck_segment_math():
    log('  [1/3] close_segment()/realize_exit() gain/tax math, round test constants (not the production ')
    log('        rates -- this isolates the FORMULA from the frozen constants, checked separately below)')
    buy_c, sell_c = 0.01, 0.01
    cash_before, entry_price, exit_price = 1000.0, 100.0, 110.0
    entry_date = pd.Timestamp('2020-01-01')
    # By hand: entry_nav = 1000*(1-0.01) = 990
    #          gross = 990 * 110/100 = 1089
    #          sale_proceeds = 1089 * (1-0.01) = 1078.11
    #          gain = 1078.11 - 990 = 88.11
    exit_date_ltcg = entry_date + pd.Timedelta(days=400)   # >365 -> LTCG @ 10% (test rate)
    exit_date_stcg = entry_date + pd.Timedelta(days=100)   # <=365 -> STCG @ 20% (test rate)
    r_ltcg = close_segment(cash_before, entry_price, entry_date, exit_price, exit_date_ltcg,
                            buy_cost_pct=buy_c, sell_cost_pct=sell_c, ltcg_rate=0.10, stcg_rate=0.20)
    r_stcg = close_segment(cash_before, entry_price, entry_date, exit_price, exit_date_stcg,
                            buy_cost_pct=buy_c, sell_cost_pct=sell_c, ltcg_rate=0.10, stcg_rate=0.20)
    assert abs(r_ltcg['entry_nav'] - 990.0) < 1e-6, r_ltcg
    assert abs(r_ltcg['gross_value'] - 1089.0) < 1e-6, r_ltcg
    assert abs(r_ltcg['sale_proceeds'] - 1078.11) < 1e-6, r_ltcg
    assert abs(r_ltcg['gain'] - 88.11) < 1e-6, r_ltcg
    assert r_ltcg['is_ltcg'] is True
    assert abs(r_ltcg['tax'] - 8.811) < 1e-6, r_ltcg           # 88.11 * 0.10
    assert abs(r_ltcg['cash_after'] - 1069.299) < 1e-6, r_ltcg  # 1078.11 - 8.811
    assert r_stcg['is_ltcg'] is False
    assert abs(r_stcg['tax'] - 17.622) < 1e-6, r_stcg          # 88.11 * 0.20
    assert abs(r_stcg['cash_after'] - 1060.488) < 1e-6, r_stcg  # 1078.11 - 17.622
    log('        LTCG case: entry_nav=990.000 gross=1089.000 proceeds=1078.110 gain=88.110 '
        'tax=8.811 cash_after=1069.299  -- PASS')
    log('        STCG case: same gain=88.110 tax=17.622 cash_after=1060.488  -- PASS')

    r_loss = close_segment(1000.0, 100.0, entry_date, 90.0, exit_date_ltcg,
                            buy_cost_pct=buy_c, sell_cost_pct=sell_c, ltcg_rate=0.10, stcg_rate=0.20)
    assert r_loss['gain'] < 0
    assert r_loss['tax'] == 0.0, r_loss
    log(f'        Loss case (exit 90 vs entry 100): gain={r_loss["gain"]:.3f} tax=0.000 (no rebate) -- PASS')

    assert abs(BUY_COST_PCT - 0.0016817) < 1e-12, BUY_COST_PCT
    assert abs(SELL_COST_PCT - 0.0015317) < 1e-12, SELL_COST_PCT
    assert LTCG_RATE == 0.125 and STCG_RATE == 0.20
    log(f'        Production constants: BUY_COST_PCT={BUY_COST_PCT:.7f} SELL_COST_PCT={SELL_COST_PCT:.7f} '
        f'LTCG={LTCG_RATE} STCG={STCG_RATE}  -- PASS (matches frozen spec verbatim)')


def selfcheck_hysteresis():
    log('  [2/3] simulate_hysteresis() switch timing + NAV chaining, hand-traced synthetic series, MA window=3')
    dates = list(pd.date_range('2021-01-01', periods=10, freq='D'))
    closes = np.array([100, 100, 100, 90, 90, 90, 105, 105, 105, 105], dtype=float)
    ma = pd.Series(closes).rolling(3).mean().to_numpy()
    # MA3: [nan,nan,100, 96.667,93.333,90, 95,100,105,105] -- valid from day3 (idx2) onward, same as
    # production (which always slices to the first MA-valid index before calling this engine).
    # day3(idx2) price=100 MA=100 lower=99      -> invested0 = not(100<99) = True -> start INVESTED @100
    # day4(idx3) price=90  MA=96.667 lower=95.7  -> 90<95.7  -> EXIT (invested->cash)
    # day7(idx6) price=105 MA=95     upper=95.95 -> 105>95.95 -> RE-ENTER (cash->invested) @105
    # no further switches through idx9 (band tracks price back up, stays invested)
    price_lookup = lambda d: closes[dates.index(d)]
    L = simulate_hysteresis(dates[2:], closes[2:], ma[2:], HYSTERESIS_BAND, price_lookup,
                             buy_cost_pct=0.01, sell_cost_pct=0.01)
    assert L.n_buys == 2 and L.n_sells == 1, (L.n_buys, L.n_sells)   # initial buy + 1 re-entry; 1 exit
    assert len(L.trades) == 1
    t = L.trades[0]
    assert t['exit_date'] == dates[3], t['exit_date']
    assert abs(t['entry_price'] - 100.0) < 1e-9 and abs(t['exit_price'] - 90.0) < 1e-9
    # by hand (normalized starting cash=1.0): entry_nav = 1.0*0.99 = 0.99
    #   gross = 0.99*0.9 = 0.891; proceeds = 0.891*0.99 = 0.88209; gain = 0.88209-0.99 = -0.10791 (loss) -> tax=0
    assert abs(t['entry_nav'] - 0.99) < 1e-9, t
    assert abs(t['gross_value'] - 0.891) < 1e-9, t
    assert abs(t['sale_proceeds'] - 0.88209) < 1e-9, t
    assert t['gain'] < 0 and t['tax'] == 0.0, t
    assert L.legs[-1]['kind'] == 'invested' and L.legs[-1]['start_date'] == dates[6]
    assert abs(L.legs[-1]['start_price'] - 105.0) < 1e-9
    # re-entry cost basis: cash_before=0.88209 (idle, 0 yield) -> entry_nav = 0.88209*0.99 = 0.8732691
    assert abs(L.legs[-1]['start_nav'] - 0.8732691) < 1e-9, L.legs[-1]
    log('        switches: EXIT day4 (100->90, loss, tax=0.000) then RE-ENTER day7 (@105) -- PASS')
    log('        NAV chain: entry_nav=0.990000 -> cash_after_exit=0.882090 -> re-entry entry_nav=0.873269 '
        '-- PASS')


def selfcheck_periodic():
    log('  [3/3] simulate_periodic() check-only-at-check-dates + MTM at an open boundary, MA window=3')
    dates = list(pd.date_range('2021-01-01', periods=12, freq='D'))
    closes = np.array([100, 100, 100, 100, 100, 70, 70, 70, 70, 70, 70, 140], dtype=float)
    ma = pd.Series(closes).rolling(3).mean().to_numpy()
    # MA3(day3=idx2)=100  MA3(day6=idx5)=avg(100,100,70)=90  MA3(day9=idx8)=avg(70,70,70)=70
    # MA3(day12=idx11)=avg(70,70,140)=93.333
    check_dates = [dates[2], dates[5], dates[8], dates[11]]   # "day3, day6, day9, day12"
    price_lookup = lambda d: closes[dates.index(d)]
    # slice to the first MA-valid index (day3/idx2) before calling, same precondition production
    # guarantees (dates[0] passed to this engine always has a valid MA -- see run_study()).
    L = simulate_periodic(dates[2:], closes[2:], ma[2:], check_dates, price_lookup,
                           buy_cost_pct=0.01, sell_cost_pct=0.01)
    # day3(idx2): price=100 MA=100 -> invested (100 not < 100) -> start INVESTED @100
    # day6(idx5): price=70  MA=90  -> 70<90 -> EXIT @70
    # day9(idx8): price=70  MA=70  -> 70<70 is False -> invested branch -> RE-ENTER @70
    # day12(idx11): price=140 MA=93.333 -> invested, no change (already invested)
    # Interim days 4,5,7,10,11 are NOT check dates and never influence a decision -- that is the
    # point of "monthly check" being tested here, not a bug.
    assert L.n_buys == 2 and L.n_sells == 1, (L.n_buys, L.n_sells)
    t = L.trades[0]
    assert t['entry_date'] == dates[2] and t['exit_date'] == dates[5]
    assert abs(t['entry_price'] - 100.0) < 1e-9 and abs(t['exit_price'] - 70.0) < 1e-9
    # by hand: entry_nav=1*0.99=0.99; gross=0.99*0.7=0.693; proceeds=0.693*0.99=0.68607
    # gain=0.68607-0.99=-0.30393 (loss) -> tax=0
    assert abs(t['entry_nav'] - 0.99) < 1e-9 and abs(t['gross_value'] - 0.693) < 1e-9
    assert abs(t['sale_proceeds'] - 0.68607) < 1e-9 and t['tax'] == 0.0
    assert L.legs[-1]['kind'] == 'invested' and L.legs[-1]['start_date'] == dates[8]
    # re-entry: cash_before=0.68607 -> entry_nav = 0.68607*0.99 = 0.6792093
    assert abs(L.legs[-1]['start_nav'] - 0.6792093) < 1e-9, L.legs[-1]
    # MTM at day12 (idx11), still open since day9: gross = 0.6792093 * (140/70) = 1.3584186
    # holding_days = day12-day9 = 3 (<=365) -> STCG(test)=0.20 -> notional_gain=1.3584186-0.6792093
    #   = 0.6792093 -> notional_tax = 0.13584186 -> mtm = 1.3584186-0.13584186 = 1.22257674
    mtm = mtm_value(L.legs[-1]['start_nav'], L.legs[-1]['start_price'], L.legs[-1]['start_date'],
                     closes[dates.index(dates[11])], dates[11], ltcg_rate=0.10, stcg_rate=0.20)
    assert abs(mtm - 1.22257674) < 1e-8, mtm
    val = L.value_asof(price_lookup, dates[11])
    assert abs(val - mtm) < 1e-12
    log('        checks only fire at day3/6/9/12 (interim moves on days 4,5,7,10,11 ignored) -- PASS')
    log('        EXIT day6 (100->70 via check, loss, tax=0.000) then RE-ENTER day9 (@70, boundary '
        'close==MA -> invested branch, not cash) -- PASS')
    log('        MTM at still-open day12 boundary: entry_nav=0.679209 -> gross=1.358419 -> '
        'after_tax_mtm=1.222577 (STCG 20% on unrealized gain) -- PASS')


def run_selfcheck():
    log('=' * 92)
    log('SELF-CHECK: core switching / tax / cost / mark-to-market logic vs hand-computed synthetic cases')
    log('=' * 92)
    selfcheck_segment_math()
    selfcheck_hysteresis()
    selfcheck_periodic()
    log('SELF-CHECK: ALL PASSED')
    log('=' * 92)
    log('')


# ===========================================================================
# ERA / CAGR REPORTING
# ===========================================================================
def nearest_trading_day(dates_index, target, side='forward'):
    """First date >= target (side='forward') or last date <= target
    (side='backward'), or None if out of range."""
    arr = dates_index
    if side == 'forward':
        pos = arr.searchsorted(target, side='left')
        return arr[pos] if pos < len(arr) else None
    pos = arr.searchsorted(target, side='right') - 1
    return arr[pos] if pos >= 0 else None


def cagr(nav_start, nav_end, date_start, date_end):
    days = (date_end - date_start).days
    if days <= 0 or nav_start is None or nav_end is None or nav_start <= 0:
        return np.nan
    return (nav_end / nav_start) ** (365.25 / days) - 1.0


def era_window(dates_index, era_start_decl, era_end_decl, global_start, global_end):
    lo = max(era_start_decl, global_start)
    hi = global_end if era_end_decl is None else min(era_end_decl, global_end)
    if lo > hi:
        return None
    d_lo = nearest_trading_day(dates_index, lo, side='forward')
    d_hi = nearest_trading_day(dates_index, hi, side='backward')
    if d_lo is None or d_hi is None or d_lo >= d_hi:
        return None
    return d_lo, d_hi


# ===========================================================================
# MAIN STUDY
# ===========================================================================
def run_study():
    close_s, source = load_or_fetch()
    dates_all = close_s.index
    closes_all = close_s.to_numpy()
    log(f'Data source: {source}')
    log(f'Range obtained: {dates_all.min().date()} -> {dates_all.max().date()}  ({len(close_s):,} trading days)')
    if dates_all.min() > pd.Timestamp('2005-06-01'):
        short_yrs = (dates_all.min() - pd.Timestamp('2005-01-01')).days // 365
        log(f'NOTE: target was 2005-present; actual yfinance ^NSEI history starts {dates_all.min().date()} '
            f'(~{short_yrs} yrs short of target). Documented in the frozen spec as a known yfinance limit, '
            f'not a scraping failure -- stooq re-confirmed non-viable (anti-bot JS challenge).')
    log('')

    ma_full = pd.Series(closes_all).rolling(MA_WINDOW).mean().to_numpy()
    valid_from = MA_WINDOW - 1
    dates = dates_all[valid_from:]
    closes = closes_all[valid_from:]
    ma = ma_full[valid_from:]
    global_start, global_end = dates[0], dates[-1]
    log(f'GLOBAL_START (first {MA_WINDOW}-day-MA-valid trading day): {global_start.date()}  '
        f'close={closes[0]:.2f}  MA200={ma[0]:.2f}  ({"below" if closes[0] < ma[0] else "at/above"} MA)')
    log(f'GLOBAL_END (last trading day obtained): {global_end.date()}  close={closes[-1]:.2f}')
    log('')

    price_lookup_full = lambda d: closes_all[dates_all.get_loc(d)]

    dseries = pd.Series(dates)
    month_ends = pd.DatetimeIndex(dseries.groupby([dseries.dt.year, dseries.dt.month]).max().to_numpy())
    check_dates = [d for d in month_ends if d >= global_start]

    L_bh = build_bh(dates, closes)
    L_v1 = simulate_periodic(list(dates), closes, ma, check_dates, price_lookup_full)
    L_v2 = simulate_hysteresis(list(dates), closes, ma, HYSTERESIS_BAND, price_lookup_full)

    bh_final_nav, bh_final_gain, bh_final_tax, bh_final_days = realize_bh_final(L_bh, price_lookup_full, global_end)

    log(f'Switch counts (full period): BH buys=1 sells=1 (the one bookend liquidation)   '
        f'V1 buys={L_v1.n_buys} sells={L_v1.n_sells}   V2 buys={L_v2.n_buys} sells={L_v2.n_sells}')
    v1_tax_total = sum(t['tax'] for t in L_v1.trades)
    v2_tax_total = sum(t['tax'] for t in L_v2.trades)
    log(f'Realized tax paid, mid-period exits only (full period): V1={v1_tax_total:.6f}  V2={v2_tax_total:.6f}  '
        f'(units of starting capital = 1.0; BH pays its one LTCG bill of {bh_final_tax:.6f} only at '
        f'GLOBAL_END, on a final gain of {bh_final_gain:.6f}, holding_days={bh_final_days})')
    log('')

    dates_index = pd.DatetimeIndex(dates)

    def value_of(strat, label, date):
        if label == 'BH' and date == global_end:
            return bh_final_nav
        return strat.value_asof(price_lookup_full, date)

    def era_row(name, d_lo, d_hi):
        row = {'era': name, 'window': f'{d_lo.date()} -> {d_hi.date()}'}
        for label, strat in (('BH', L_bh), ('V1', L_v1), ('V2', L_v2)):
            v_lo = value_of(strat, label, d_lo)
            v_hi = value_of(strat, label, d_hi)
            row[f'{label}_cagr'] = cagr(v_lo, v_hi, d_lo, d_hi)
            row[f'{label}_nav_lo'] = v_lo
            row[f'{label}_nav_hi'] = v_hi
        for label, strat in (('V1', L_v1), ('V2', L_v2)):
            era_trades = [t for t in strat.trades if d_lo < t['exit_date'] <= d_hi]
            row[f'{label}_switches'] = len(era_trades)
            row[f'{label}_tax'] = sum(t['tax'] for t in era_trades)
        return row

    rows = []
    for name, s, e in ERA_DEFS:
        win = era_window(dates_index, s, e, global_start, global_end)
        if win is None:
            rows.append({'era': name, 'window': 'N/A (no overlap with obtained data range)',
                        'BH_cagr': np.nan, 'V1_cagr': np.nan, 'V2_cagr': np.nan,
                        'V1_switches': 0, 'V2_switches': 0, 'V1_tax': 0.0, 'V2_tax': 0.0})
            continue
        rows.append(era_row(name, *win))
    rows.append(era_row('FULL PERIOD', global_start, global_end))

    log(f'{"ERA":<14}{"WINDOW":<26}{"BH CAGR":>10}{"V1 CAGR":>10}{"V2 CAGR":>10}'
        f'{"V1 switch":>11}{"V2 switch":>11}{"V1 tax":>10}{"V2 tax":>10}')
    log('-' * 112)
    for r in rows:
        log(f'{r["era"]:<14}{r["window"]:<26}{pct(r["BH_cagr"]):>10}{pct(r["V1_cagr"]):>10}'
            f'{pct(r["V2_cagr"]):>10}{r.get("V1_switches", 0):>11}{r.get("V2_switches", 0):>11}'
            f'{r.get("V1_tax", 0.0):>10.5f}{r.get("V2_tax", 0.0):>10.5f}')
    log('')

    full = rows[-1]
    era_rows = rows[:-1]

    def beats(v_key):
        full_pass = np.isfinite(full[v_key]) and np.isfinite(full['BH_cagr']) and full[v_key] > full['BH_cagr']
        era_wins, era_considered = 0, 0
        for r in era_rows:
            if not np.isfinite(r[v_key]) or not np.isfinite(r['BH_cagr']):
                continue
            era_considered += 1
            if r[v_key] > r['BH_cagr']:
                era_wins += 1
        return full_pass, era_wins, era_considered, (full_pass and era_wins >= 2)

    v1_full_pass, v1_era_wins, v1_era_n, v1_pass = beats('V1_cagr')
    v2_full_pass, v2_era_wins, v2_era_n, v2_pass = beats('V2_cagr')

    log('PASS BAR (frozen): V1 or V2 after-tax CAGR strictly exceeds BH after-tax CAGR over the FULL period '
        'AND in >=2 of the 3 declared eras (an era missing data cannot be won -- counts against the bar, '
        'not around it).')
    log(f'  V1: full-period beats BH = {v1_full_pass}   eras won = {v1_era_wins}/3 declared '
        f'({v1_era_n} had data in both series)   => {"PASS" if v1_pass else "FAIL"}')
    log(f'  V2: full-period beats BH = {v2_full_pass}   eras won = {v2_era_wins}/3 declared '
        f'({v2_era_n} had data in both series)   => {"PASS" if v2_pass else "FAIL"}')
    log('')
    overall = 'PASS' if (v1_pass or v2_pass) else 'FAIL'
    reason = ('at least one variant cleared the frozen bar' if overall == 'PASS'
              else "neither variant cleared the frozen bar (matches the shortlist's stated prior)")
    log(f'VERDICT: {overall} -- {reason}.')
    return overall


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--fetch', action='store_true', help='fetch + cache only, no self-check, no simulation')
    ap.add_argument('--selfcheck-only', action='store_true', help='run only the self-check')
    args = ap.parse_args()

    if args.fetch:
        close_s = fetch_nifty_daily()
        close_s.rename_axis('date').reset_index(name='close').to_csv(CACHE_FILE, index=False)
        print(f'Fetched + cached {len(close_s):,} rows, {close_s.index.min().date()} -> '
              f'{close_s.index.max().date()} -> {CACHE_FILE}')
        return

    run_selfcheck()
    if args.selfcheck_only:
        return

    log('=' * 92)
    log('REGIME EXIT ON THE BUY-AND-HOLD CORE -- FROZEN SPEC (2026-08-04)')
    log('=' * 92)
    log(f'Spec: {SPEC}')
    log('Stated prior (shortlist, verbatim): "industry-mined to death ... Expected verdict: FAIL."')
    log('')
    run_study()
    flush_out(OUT_FILE)
    print(f'\nResults written to {OUT_FILE}')


if __name__ == '__main__':
    main()
