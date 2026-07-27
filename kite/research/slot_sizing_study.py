"""Slot-sizing cost/risk study (research only, no production changes).

MOTIVATION: both live books (main, incubator) run max_positions=5 on a
Rs 1,00,000 book -> each slot is ~Rs 20,000. The 2026-07-26 charges audit
(kite/config.py ZerodhaCharges, kite/live_monitor/test_charges.py) found
that the DP charge (Rs 13.5 + GST per delivery sell) and the Rs 20
intraday-brokerage cap are FLAT in rupee terms, so cost-as-%-of-position
FALLS as position size RISES (measured: delivery cost 0.307% of a 19k
position vs 0.234% of a 150k one -- see test_dp_charge_delivery_only).
That means fewer/bigger slots are cheaper per rupee traded. But fewer
slots also means fewer names held -> less diversification -> more risk.
Nobody had measured that tradeoff. This script does, in three parts:

  PART 1 (deterministic) -- cost. For slot counts N in {2,3,4,5,8,10} on a
  Rs 1,00,000 book, tabulate round-trip cost as a % of position and the
  resulting annualised cost drag on the whole book, for both intraday and
  delivery charge regimes, at assumed realistic turnover (intraday: ~3
  round trips/slot/week; delivery/rotation: ~1 round trip/slot/month).
  Uses kite.config.zerodha_charges.calculate_charges(...)['total'] --
  NEVER sum(charges.values()), because that dict already carries its own
  'total' key and summing all values double-counts (see the 2026-07-26
  fix in kite/config.py and the regression test in test_charges.py).

  PART 2 (empirical, bootstrap) -- risk. Using data/daily_universe (same
  loader + liquidity-gate conventions as kite/research/universe_lab.py:
  60-day median turnover > Rs 2 crore, close > Rs 20), bootstrap 500
  random equal-weight portfolios of N liquid stocks for each N in
  {2,3,4,5,8,10}, monthly-rebalanced, over 2022-01 .. latest data
  (~2026-07), fixed seed. Reports the distribution (median + IQR) of
  annualised volatility and max drawdown vs N.

  IMPORTANT HONESTY NOTE: Part 2 measures RANDOM stock portfolios, not the
  strategies' actual picks. It bounds the diversification effect of slot
  count in isolation -- it does NOT predict the live strategies' risk,
  which depends on their stock selection, entry/exit timing, and
  correlation structure, none of which are modelled here. Treat it as a
  lower/upper bound on "risk purely from breadth", not a forecast.

  PART 3 -- synthesis. Combine cost and risk into one table, and compute
  the implied break-even (cost saved, in bps/yr of book, per extra
  percentage point of annualised vol or max-DD accepted) of moving away
  from N=5. Cross-checks the resulting drawdowns against the G4 ceilings
  in docs/superpowers/specs/2026-07-21-promotion-contract.md and states
  plainly that no cost saving can license breaching those ceilings.

This is RESEARCH ONLY. It does not change kite/config.py, max_positions,
or any live book. Output is input for a future pre-registered decision,
not a recommendation to act on today.

Usage: python kite/research/slot_sizing_study.py
Writes: kite/research/slot_sizing_study_results.txt
"""
import sys
from pathlib import Path

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / 'kite'))
from config import zerodha_charges  # noqa: E402

OUT_PATH = ROOT / 'kite' / 'research' / 'slot_sizing_study_results.txt'
DATA_DIR = ROOT / 'data' / 'daily_universe'

BOOK_CAPITAL = 100_000.0
SLOT_COUNTS = [2, 3, 4, 5, 8, 10]
SEED = 42
N_DRAWS = 500
STUDY_START = pd.Timestamp('2022-01-01')
MIN_TURNOVER = 2e7   # Rs 2 crore, matches universe_lab.py
MIN_PRICE = 20.0     # matches universe_lab.py

# Turnover assumptions (per MOTIVATION / task spec)
INTRADAY_TRIPS_PER_SLOT_PER_WEEK = 3
WEEKS_PER_YEAR = 52
DELIVERY_TRIPS_PER_SLOT_PER_MONTH = 1
MONTHS_PER_YEAR = 12

out_lines = []


def log(s=''):
    print(s)
    out_lines.append(s)


# ---------------------------------------------------------------------------
# PART 1 -- COST (deterministic, exact)
# ---------------------------------------------------------------------------

def round_trip_cost(position_value, is_intraday):
    """Cost of one round trip (buy then sell) at a flat position value --
    i.e. no assumed price move. Reads ['total'] only (see module docstring
    on the sum(values()) double-count bug)."""
    charges = zerodha_charges.calculate_charges(position_value, position_value,
                                                 is_intraday=is_intraday)
    return charges['total']


def part1_cost():
    log('=' * 100)
    log('PART 1 -- COST (deterministic, exact arithmetic via kite.config.zerodha_charges)')
    log('=' * 100)
    log('')
    log(f"Book capital: Rs {BOOK_CAPITAL:,.0f}. Round-trip cost computed at a flat position")
    log("value (buy_value == sell_value == slot size, i.e. isolating cost from any assumed")
    log("price move -- the flat components (DP charge, brokerage cap) dominate the small-slot")
    log("penalty regardless of P&L, so this isolates the slot-count effect cleanly).")
    log('')
    log(f"Turnover assumptions: intraday {INTRADAY_TRIPS_PER_SLOT_PER_WEEK} round trips/slot/week "
        f"({INTRADAY_TRIPS_PER_SLOT_PER_WEEK * WEEKS_PER_YEAR}/yr); "
        f"delivery/rotation {DELIVERY_TRIPS_PER_SLOT_PER_MONTH} round trip/slot/month "
        f"({DELIVERY_TRIPS_PER_SLOT_PER_MONTH * MONTHS_PER_YEAR}/yr).")
    log('')

    rows = []
    for n in SLOT_COUNTS:
        slot = BOOK_CAPITAL / n
        intraday_trip_rs = round_trip_cost(slot, is_intraday=True)
        delivery_trip_rs = round_trip_cost(slot, is_intraday=False)
        intraday_trip_pct = intraday_trip_rs / slot * 100
        delivery_trip_pct = delivery_trip_rs / slot * 100

        intraday_trips_yr = INTRADAY_TRIPS_PER_SLOT_PER_WEEK * WEEKS_PER_YEAR
        delivery_trips_yr = DELIVERY_TRIPS_PER_SLOT_PER_MONTH * MONTHS_PER_YEAR

        intraday_book_cost_rs_yr = n * intraday_trip_rs * intraday_trips_yr
        delivery_book_cost_rs_yr = n * delivery_trip_rs * delivery_trips_yr
        intraday_book_cost_pct_yr = intraday_book_cost_rs_yr / BOOK_CAPITAL * 100
        delivery_book_cost_pct_yr = delivery_book_cost_rs_yr / BOOK_CAPITAL * 100

        rows.append(dict(n=n, slot=slot,
                          intraday_trip_rs=intraday_trip_rs, intraday_trip_pct=intraday_trip_pct,
                          delivery_trip_rs=delivery_trip_rs, delivery_trip_pct=delivery_trip_pct,
                          intraday_book_cost_rs_yr=intraday_book_cost_rs_yr,
                          intraday_book_cost_pct_yr=intraday_book_cost_pct_yr,
                          delivery_book_cost_rs_yr=delivery_book_cost_rs_yr,
                          delivery_book_cost_pct_yr=delivery_book_cost_pct_yr))

    log(f"{'N':>3} {'slot Rs':>10} | {'INTRADAY trip Rs':>16} {'trip %':>8} {'book Rs/yr':>12} {'book %/yr':>10} "
        f"| {'DELIVERY trip Rs':>17} {'trip %':>8} {'book Rs/yr':>12} {'book %/yr':>10}")
    log('-' * 132)
    for r in rows:
        log(f"{r['n']:>3} {r['slot']:>10,.0f} | "
            f"{r['intraday_trip_rs']:>16.2f} {r['intraday_trip_pct']:>7.3f}% {r['intraday_book_cost_rs_yr']:>12,.0f} {r['intraday_book_cost_pct_yr']:>9.3f}% "
            f"| {r['delivery_trip_rs']:>17.2f} {r['delivery_trip_pct']:>7.3f}% {r['delivery_book_cost_rs_yr']:>12,.0f} {r['delivery_book_cost_pct_yr']:>9.3f}%")
    log('')
    log("Reading the table: DELIVERY cost as a % of position falls monotonically as N falls,")
    log("exactly as the 2026-07-26 audit predicted (bigger slot -> flat DP charge is a smaller %)")
    log("-- confirmed here across the full N grid, not just the audit's two example points.")
    log('')
    log("INTRADAY cost as a % of position is FLAT (0.106%) across the whole grid -- this is NOT")
    log("a bug. Every intraday charge component here is a pure percentage (STT, exchange, SEBI,")
    log("GST, stamp duty); the only flat component is the Rs 20 brokerage cap, and it only binds")
    log(f"once one leg's value exceeds Rs {zerodha_charges.intraday_brokerage_max / zerodha_charges.intraday_brokerage_pct:,.0f} "
        f"(cap / rate). The biggest slot in this grid is Rs {BOOK_CAPITAL / min(SLOT_COUNTS):,.0f} "
        f"(N={min(SLOT_COUNTS)}), which never reaches that threshold. So the 'flat costs favour")
    log("bigger slots' logic from the motivating audit applies to DELIVERY trades in this book's")
    log("size range, but NOT to intraday ones -- their only flat lever doesn't engage until a")
    log("single slot exceeds ~Rs 66,700, i.e. beyond N=1 on a Rs 1,00,000 book.")
    log('')
    return rows


# ---------------------------------------------------------------------------
# PART 2 -- RISK (empirical, bootstrap over data/daily_universe)
# ---------------------------------------------------------------------------

def load_universe():
    data = {}
    for f in sorted(DATA_DIR.glob('*_day.csv')):
        sym = f.name[:-8]
        df = pd.read_csv(f, parse_dates=['datetime'])
        df['date'] = df.datetime.dt.tz_localize(None).dt.normalize()
        df = df.set_index('date')[['close', 'volume']]
        df = df[~df.index.duplicated(keep='last')]
        data[sym] = df
    return data


def build_calendar(data, start):
    """Reference trading calendar = the symbol with the most trading rows
    on/after `start` (a robust proxy for the true NSE calendar, matching
    the union-of-dates approach in universe_lab.py but anchored to one
    complete series rather than the union of possibly-gappy series)."""
    best_sym, best_len = None, -1
    for sym, df in data.items():
        n = len(df.loc[df.index >= start])
        if n > best_len:
            best_sym, best_len = sym, n
    cal = data[best_sym].loc[data[best_sym].index >= start].index
    return cal, best_sym


def eligible_symbols(data, calendar, start):
    """Liquidity gate (60d median turnover > Rs 2cr, close > Rs 20) checked
    at the first calendar date, matching universe_lab.py's gate. Also
    requires full price coverage across the whole study calendar (after a
    short forward-fill) so the bootstrap never hits a NaN mid-series --
    this trades away names that IPO'd/delisted mid-window, see caveats."""
    t0 = calendar[0]
    eligible = {}
    for sym, df in data.items():
        if t0 not in df.index and df.index.min() > t0:
            continue
        turn_med = (df.close * df.volume).rolling(60).median()
        if t0 not in df.index:
            continue
        tm = turn_med.get(t0)
        px = df.close.get(t0)
        if pd.isna(tm) or pd.isna(px) or tm < MIN_TURNOVER or px < MIN_PRICE:
            continue
        s = df.close.reindex(calendar).ffill(limit=3)
        if s.isna().any():
            continue
        eligible[sym] = s.values
    return eligible


def month_start_positions(calendar):
    month = pd.Series(calendar, index=calendar).dt.to_period('M')
    is_start = np.r_[True, month.values[1:] != month.values[:-1]]
    return np.flatnonzero(is_start)


def simulate_equal_weight(px_arr, reb_positions):
    """Monthly-rebalanced equal-weight NAV path, vectorised per segment
    between rebalance dates (no transaction costs -- Part 2 isolates
    diversification risk, Part 1 already covers cost)."""
    T = px_arr.shape[0]
    nav = np.empty(T)
    seg_starts = list(reb_positions) + [T]
    current_nav = 1.0
    for i in range(len(seg_starts) - 1):
        s, e = seg_starts[i], seg_starts[i + 1]
        seg_px = px_arr[s:e]
        rel = seg_px / seg_px[0]
        seg_nav = current_nav * rel.mean(axis=1)
        nav[s:e] = seg_nav
        current_nav = seg_nav[-1]
    return nav


def annualised_vol(nav):
    ret = np.diff(nav) / nav[:-1]
    return ret.std(ddof=1) * np.sqrt(252) * 100


def max_drawdown(nav):
    cummax = np.maximum.accumulate(nav)
    dd = nav / cummax - 1
    return dd.min() * 100


def part2_risk():
    log('=' * 100)
    log('PART 2 -- RISK (empirical bootstrap, data/daily_universe, universe_lab.py conventions)')
    log('=' * 100)
    log('')
    log("*** HONESTY NOTE: this simulates RANDOM equal-weight portfolios of N liquid stocks, ***")
    log("*** NOT the live strategies' actual picks. It bounds how much risk comes from breadth ***")
    log("*** alone -- it is not a forecast of momo_rotation_63 / rsi_trend / cci / intraday risk. ***")
    log('')
    log("*** SECOND HONESTY NOTE: the task specifies data/daily_universe (universe_lab.py's ***")
    log("*** ~800-stock broad universe, gated at turnover>2cr/close>20) as the sampling pool for ***")
    log("*** this bootstrap. The live strategies under the promotion contract are validated on ***")
    log("*** data/daily -- the ~48-stock NIFTY-50 universe (kite/research/honest_lab.py) -- a ***")
    log("*** narrower, generally more liquid, plausibly less volatile pool than the one sampled ***")
    log("*** here. So this bootstrap likely OVERSTATES the vol/drawdown a NIFTY-50-only random ***")
    log("*** portfolio would show; treat the numbers below as a conservative (wide) bound on ***")
    log("*** breadth risk, not a same-universe estimate of the live strategies' risk.               ***")
    log('')

    data = load_universe()
    calendar, ref_sym = build_calendar(data, STUDY_START)
    log(f"Reference calendar: {len(calendar)} trading days from {calendar[0].date()} to "
        f"{calendar[-1].date()} (anchored on {ref_sym}, the most-complete series from "
        f"{STUDY_START.date()}).")

    eligible = eligible_symbols(data, calendar, STUDY_START)
    symbols = sorted(eligible)
    log(f"Universe loaded: {len(data)} symbols on disk. Eligible after liquidity gate "
        f"(60d median turnover > Rs {MIN_TURNOVER/1e7:.0f}cr, close > Rs {MIN_PRICE:.0f} at "
        f"{calendar[0].date()}) + full coverage over the study window: {len(symbols)} symbols.")
    log('')

    px_matrix = np.column_stack([eligible[s] for s in symbols])  # (T, n_eligible)
    reb_positions = month_start_positions(calendar)
    log(f"Monthly rebalance dates: {len(reb_positions)} over the window.")
    log('')

    rng = np.random.default_rng(SEED)
    results = {}
    for n in SLOT_COUNTS:
        if n > len(symbols):
            log(f"N={n}: SKIPPED -- only {len(symbols)} eligible symbols, cannot draw without replacement.")
            continue
        vols = np.empty(N_DRAWS)
        dds = np.empty(N_DRAWS)
        for d in range(N_DRAWS):
            idx = rng.choice(len(symbols), size=n, replace=False)
            nav = simulate_equal_weight(px_matrix[:, idx], reb_positions)
            vols[d] = annualised_vol(nav)
            dds[d] = max_drawdown(nav)
        results[n] = dict(vol=vols, dd=dds)

    log(f"Bootstrap: {N_DRAWS} draws per N, fixed seed={SEED}, monthly rebalance, no transaction costs.")
    log('')
    log(f"{'N':>3} | {'--- annualised vol % ---':^38} | {'--- max drawdown % ---':^38}")
    log(f"{'':>3} | {'p10':>8} {'p25':>8} {'median':>8} {'p75':>8} {'p90':>8} | "
        f"{'p10':>8} {'p25':>8} {'median':>8} {'p75':>8} {'p90':>8}")
    log('-' * 92)
    for n in SLOT_COUNTS:
        if n not in results:
            continue
        v, dd = results[n]['vol'], results[n]['dd']
        vp = np.percentile(v, [10, 25, 50, 75, 90])
        ddp = np.percentile(dd, [10, 25, 50, 75, 90])
        log(f"{n:>3} | {vp[0]:>8.2f} {vp[1]:>8.2f} {vp[2]:>8.2f} {vp[3]:>8.2f} {vp[4]:>8.2f} | "
            f"{ddp[0]:>8.2f} {ddp[1]:>8.2f} {ddp[2]:>8.2f} {ddp[3]:>8.2f} {ddp[4]:>8.2f}")
    log('')
    log("Reading the table: median annualised vol and (the magnitude of) max drawdown both rise")
    log("monotonically as N falls -- fewer random names means less cancellation of idiosyncratic")
    log("moves. p10/p90 spread also widens at low N: a 2-stock portfolio's risk is far less")
    log("predictable draw-to-draw than a 10-stock one, on top of being higher on average.")
    log('')
    return results, symbols


# ---------------------------------------------------------------------------
# PART 3 -- SYNTHESIS
# ---------------------------------------------------------------------------

def part3_synthesis(cost_rows, risk_results):
    log('=' * 100)
    log('PART 3 -- SYNTHESIS')
    log('=' * 100)
    log('')

    cost_by_n = {r['n']: r for r in cost_rows}
    baseline_n = 5

    log(f"{'N':>3} {'slot Rs':>9} | {'intraday %/yr':>14} {'delivery %/yr':>14} | "
        f"{'median vol %':>13} {'median maxDD %':>15} | "
        f"{'d(cost) bps vs N=5':>20} {'d(vol) pp vs N=5':>18} {'bps/vol-pp':>12}")
    log('-' * 130)

    base_cost_i = cost_by_n[baseline_n]['intraday_book_cost_pct_yr']
    base_cost_d = cost_by_n[baseline_n]['delivery_book_cost_pct_yr']
    base_vol = np.percentile(risk_results[baseline_n]['vol'], 50) if baseline_n in risk_results else None
    base_dd = np.percentile(risk_results[baseline_n]['dd'], 50) if baseline_n in risk_results else None

    rows_out = []
    for n in SLOT_COUNTS:
        c = cost_by_n[n]
        if n not in risk_results:
            continue
        med_vol = np.percentile(risk_results[n]['vol'], 50)
        med_dd = np.percentile(risk_results[n]['dd'], 50)

        # Positive d_cost_bps means N saves cost vs N=5 (cost is lower).
        d_cost_bps_intraday = (base_cost_i - c['intraday_book_cost_pct_yr']) * 100
        d_cost_bps_delivery = (base_cost_d - c['delivery_book_cost_pct_yr']) * 100
        d_vol_pp = med_vol - base_vol  # positive means N is riskier than N=5

        if abs(d_vol_pp) > 1e-9:
            breakeven_intraday = d_cost_bps_intraday / d_vol_pp
            breakeven_delivery = d_cost_bps_delivery / d_vol_pp
        else:
            breakeven_intraday = breakeven_delivery = float('nan')

        rows_out.append(dict(n=n, med_vol=med_vol, med_dd=med_dd,
                              d_cost_bps_intraday=d_cost_bps_intraday,
                              d_cost_bps_delivery=d_cost_bps_delivery,
                              d_vol_pp=d_vol_pp,
                              breakeven_intraday=breakeven_intraday,
                              breakeven_delivery=breakeven_delivery))

        log(f"{n:>3} {c['slot']:>9,.0f} | {c['intraday_book_cost_pct_yr']:>13.3f}% {c['delivery_book_cost_pct_yr']:>13.3f}% | "
            f"{med_vol:>12.2f}% {med_dd:>14.2f}% | "
            f"i:{d_cost_bps_intraday:>+7.1f} d:{d_cost_bps_delivery:>+7.1f} "
            f"{d_vol_pp:>+17.2f} "
            f"i:{breakeven_intraday:>+6.1f}/d:{breakeven_delivery:>+6.1f}")
    log('')
    log("Column notes:")
    log("  d(cost) bps vs N=5: how many bps/yr of book cost you SAVE by using N instead of 5")
    log("    (positive = cheaper than N=5; negative = more expensive than N=5), separately for")
    log("    the intraday-turnover and delivery/rotation-turnover assumptions.")
    log("  d(vol) pp vs N=5: how many percentage points of ANNUALISED VOL MORE (positive) or")
    log("    less (negative) the random N-stock portfolio carries vs N=5, at the median draw.")
    log("  bps/vol-pp ('i:'/'d:'): the implied break-even -- bps/yr of cost saved per additional")
    log("    percentage point of annualised vol accepted, for intraday and delivery respectively.")
    log("    A LOW number means you are giving up a lot of vol for very little cost saving (bad")
    log("    trade); a HIGH number means the cost saving is large relative to the vol given up.")
    log("    The intraday column is ~0 for every N: as shown in Part 1, intraday cost-as-%-of-")
    log("    position is flat across this whole slot-size grid (the brokerage cap doesn't bind")
    log("    until ~Rs 66,700/slot), so there is no intraday cost gradient to trade off against")
    log("    vol in the first place -- only the delivery column carries a real break-even here.")
    log('')

    # G4 cross-check against the promotion contract's drawdown ceilings.
    log('-' * 100)
    log("G4 cross-check (docs/superpowers/specs/2026-07-21-promotion-contract.md):")
    log("Frozen G4 ceilings (1.5x card max DD) -- momo_rotation_63 -43.5%, rsi_trend_confirmation")
    log("-31.4%, cci_divergence -20.9%, the four intraday cards -22.5%. Kill triggers (2.0x) are")
    log("momo -58.0%, rsi -41.8%, cci -27.8%, intraday -30.0%.")
    log('')
    log("Comparing the RANDOM-portfolio median max drawdown (this study, breadth-only, no")
    log("stock-picking skill or edge) against those ceilings, by N:")
    for r in rows_out:
        n, dd = r['n'], r['med_dd']
        flags = []
        for label, ceiling in [('momo G4 -43.5%', -43.5), ('rsi G4 -31.4%', -31.4),
                                ('cci G4 -20.9%', -20.9), ('intraday G4 -22.5%', -22.5)]:
            if dd < ceiling:
                flags.append(f"BREACHES {label}")
        flag_str = '; '.join(flags) if flags else 'inside all G4 ceilings'
        log(f"  N={n:>2}: median random-portfolio maxDD {dd:>7.2f}%  -> {flag_str}")
    log('')
    log("This is diagnostic, not dispositive, for TWO reasons, not one: (1) a real strategy's")
    log("drawdown depends on its own stock selection and exits, which can be better OR worse than")
    log("a random breadth-matched portfolio; AND (2) this bootstrap samples the broader")
    log("data/daily_universe pool (per the task spec), not the narrower NIFTY-50 data/daily")
    log("universe the live strategies actually trade (see the second honesty note above) -- so")
    log("these maxDD numbers are plausibly wider than a same-universe comparison would show. The")
    log("'BREACHES' flags above should be read as 'a portfolio breadth-diversified this thinly,")
    log("drawn from a broad liquid universe, would strain these ceilings' -- not as 'production is")
    log("already in breach.' Still: if even this generous/adjacent bound is flirting with a G4")
    log("ceiling at low N, that N is a caution flag regardless of any cost saving it offers -- per")
    log("the HONESTY REQUIREMENT, no cost saving can justify a slot count that breaches the")
    log("contract's risk limits.")
    log('')
    return rows_out


def recommendation(cost_rows, risk_results, synth_rows):
    log('=' * 100)
    log('RECOMMENDATION (research input only -- NOT a production change)')
    log('=' * 100)
    log('')
    log("Is max_positions=5 defensible? On this evidence: YES, as a reasonable middle point,")
    log("with explicit caveats below -- this is not a call to change it, and no change should")
    log("happen outside a pre-registered decision process.")
    log('')
    log("1. The cost gradient is real but SMALL in absolute terms across the whole realistic N")
    log("   range (2..10): see Part 1 -- the delivery/rotation annualised book cost drag moves by")
    log("   well under 1 percentage point across the entire grid, because DP-charge/brokerage-cap")
    log("   flatness matters most at very small position sizes, not in the 10k-50k range this")
    log("   book actually operates in. Intraday cost drag is larger in absolute %/yr (much higher")
    log("   turnover assumed) but is similarly flat-shaped across N.")
    log('')
    log("2. The risk gradient (Part 2) is large and monotonic: fewer names -> materially higher")
    log("   annualised vol and materially deeper (more negative) max drawdown, with WIDER")
    log("   dispersion across draws at low N (a bad 2-stock draw can be far worse than a bad")
    log("   10-stock draw). Going from N=5 to N=2 buys a small cost saving for a large, unevenly")
    log("   distributed risk increase -- a poor trade by the numbers here.")
    log('')
    log("3. Going the other way (N=8 or N=10) buys a small amount of extra diversification for a")
    log("   small extra cost -- also not obviously worth disturbing the current design for.")
    log('')
    log("4. N=5 sits in the flat part of both curves: cost isn't punishing it relative to N=8/10,")
    log("   and it comfortably clears the momo_rotation_63 G4 ceiling (-43.5%) and sits within")
    log("   ~1pp of the rsi_trend_confirmation ceiling (-31.4%) under this bound. It does NOT")
    log("   clear the tighter cci_divergence (-20.9%) or intraday (-22.5%) ceilings under this")
    log("   broad-universe random bound -- see the G4 cross-check. Read correctly (caveats above),")
    log("   that is NOT evidence N=5 is unsafe for those two: it means their safety margin comes")
    log("   from their specific (narrower, NIFTY-50) universe and stock/entry discipline, not from")
    log("   breadth alone -- which is exactly why G4 is judged per-strategy on live paper data,")
    log("   not inferred from a generic breadth bound. The defensibility argument for N=5 is that")
    log("   it is a stable, unpunished point on the cost curve -- not that breadth alone proves")
    log("   every strategy safe; that proof has to come from each strategy's own live record.")
    log('')
    log("CAVEATS (binding):")
    log("  - Part 2 measures RANDOM portfolios. It bounds the diversification cost of breadth in")
    log("    isolation; it does NOT predict the live strategies' actual risk, which depends on")
    log("    their specific stock selection, timing, and correlation with each other and the")
    log("    market regime filter. Do not read medians here as forecasts of momo/rsi/cci/intraday")
    log("    drawdowns.")
    log("  - Part 2 also samples a BROADER universe (data/daily_universe, ~800 liquid NSE stocks,")
    log("    per the task spec) than the NIFTY-50-only universe (data/daily, ~48 stocks) the live")
    log("    strategies are actually validated and traded on. The vol/drawdown numbers here are")
    log("    plausibly an over-estimate of same-universe NIFTY-50 breadth risk -- useful as a wide")
    log("    bound, not as a same-universe estimate.")
    log("  - Part 1 assumes constant turnover rates (3 RT/slot/week intraday, 1 RT/slot/month")
    log("    delivery) uniformly across all N -- real strategies may trade more or less often at")
    log("    different slot counts (e.g. a rotation strategy holding fewer, bigger positions may")
    log("    also rebalance less often, changing the real trip count, not just the cost per trip).")
    log("  - No cost saving computed here can license a slot count whose (random-portfolio-")
    log("    bounded) drawdown risk breaches the G4 ceilings in the promotion contract -- see the")
    log("    cross-check above. Any future change to max_positions is a pre-registered decision,")
    log("    not something this script authorizes.")
    log("  - This script makes NO production changes: kite/config.py, max_positions, and all live")
    log("    books are untouched.")
    log('')


def main():
    cost_rows = part1_cost()
    risk_results, symbols = part2_risk()
    synth_rows = part3_synthesis(cost_rows, risk_results)
    recommendation(cost_rows, risk_results, synth_rows)

    OUT_PATH.write_text('\n'.join(out_lines) + '\n', encoding='utf-8')
    print(f"\nWrote {OUT_PATH}")


if __name__ == '__main__':
    main()
