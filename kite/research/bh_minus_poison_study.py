"""B&H MINUS POISON — pre-registered synthesis test.

================================ FROZEN DESIGN ================================
THE QUESTION: does "B&H minus poison" -- holding the liquid universe EXCEPT
temporarily-flagged names -- beat plain buy-and-hold after costs? The project's
only unbeaten baseline is B&H of the liquid universe; the only replicated real
findings are AVOID-signals (4 announcement categories with negative 5d drift,
and results-miss reactions with negative 20d drift). This asks whether those
avoid-signals, applied as a passive exclusion overlay, upgrade the baseline.

- Data: data/daily_universe/*.csv via kite/research/universe_lab.py conventions
  (same loader; >=300 rows; 60d median turnover; daily returns clipped +/-25%;
  turnover gate 2cr; price gate 20; SLIP=0.002 convention). Delivery-cost model:
  vectorized 0.4% round-trip charged on the turnover FRACTION at each rebalance
  (== 0.2%/side on weight changes, coherent with SLIP=0.002/side).
- Portfolio: monthly-rebalanced equal-weight of ALL liquid-gated symbols (not
  top-N) -- approximates B&H EW. BASELINE = that portfolio, no exclusions.
  TREATMENT = same, but at each monthly rebalance EXCLUDE any symbol flagged in
  the past 20 trading days by (a) any of the 4 red-flag desc categories, or
  (b) a results-miss event (pead_events.csv bucket=='NEGATIVE', by symbol+E_date).
  Flags only affect ENTRY at rebalance; a name flagged mid-month is sold at the
  NEXT rebalance (no intramonth churn).
- Red-flag categories (exact desc strings):
    'Change in Director(s)'
    'Disclosure under SEBI Takeover Regulations'
    'Spurt in Volume'
    'Statement of deviation(s) or variation(s) under Reg. 32'
- Window: 2020-2026. Split: 2020-2022 DEVELOP / 2023-2026 VERDICT.
- Cost honesty: EW of ~300-500 names monthly has real turnover cost. Charged
  via vectorized weight-change model (below). Both baseline & treatment pay it;
  treatment pays extra for flag churn.
- FROZEN VERDICT (all three, else TOMBSTONE):
    (1) treatment CAGR beats baseline in 2023-2026 by >= 0.5 points net, AND
    (2) treatment maxDD no worse than baseline + 1 point, AND
    (3) same-direction (treatment beats baseline) in the 2020-2022 develop window.
  On failure: avoid-signals stay entry-gates for active strategies only, not
  worth a passive overlay.

Lookahead audit: both flag types are known at flag time. Red-flag = announcement
receipt timestamp (mapped to first trading day >= its date). Results-miss bucket
NEGATIVE derives from R = close[E]/close[E-1]-1 - marketEW, which uses ONLY data
through close[E] (see pead_conditioned.py). Flags remove names going FORWARD.

Cost model detail: at each rebalance turnover fraction f = 0.5 * sum|w_new-w_old|
over drifted-vs-target weights; cost = 0.004 * f applied as a return hit on the
rebalance day. Between rebalances weights drift with returns (true B&H drift).

Usage: python kite/research/bh_minus_poison_study.py
=============================================================================="""
import sys
import glob
from pathlib import Path

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parents[2]
DATA_DIR = ROOT / 'data' / 'daily_universe'
ANN_DIR = ROOT / 'data' / 'announcements'
PEAD = ROOT / 'kite' / 'research' / 'pead_events.csv'
OUT = ROOT / 'kite' / 'research' / 'bh_minus_poison_study.txt'

SLIP = 0.002                 # universe_lab convention (per side)
ROUND_TRIP = 0.004           # 0.4% round-trip charged on turnover fraction
MIN_TURNOVER = 2e7           # 2cr 60d-median turnover gate
MIN_PRICE = 20.0             # price gate
CLIP = 0.25                  # daily return clip +/-25%
FLAG_LOOKBACK = 20           # trading days a flag stays active
START = pd.Timestamp('2020-01-01')
END = pd.Timestamp('2026-12-31')
DEV_END = pd.Timestamp('2022-12-31')   # develop 2020-2022 / verdict 2023-2026

RED_FLAGS = {
    'Change in Director(s)',
    'Disclosure under SEBI Takeover Regulations',
    'Spurt in Volume',
    'Statement of deviation(s) or variation(s) under Reg. 32',
}

_lines = []
def out(s=''):
    print(s, flush=True)
    _lines.append(s)


def load():
    """universe_lab.load conventions: normalize dates, dedupe, >=300 rows,
    60d median turnover. Returns close & turnover-median frames."""
    closes, turns = {}, {}
    for f in sorted(DATA_DIR.glob('*_day.csv')):
        sym = f.name[:-8]
        df = pd.read_csv(f, parse_dates=['datetime'])
        df['date'] = df.datetime.dt.tz_localize(None).dt.normalize()
        df = df.set_index('date')[['close', 'volume']]
        df = df[~df.index.duplicated(keep='last')]
        if len(df) < 300:
            continue
        closes[sym] = df.close
        turns[sym] = (df.close * df.volume).rolling(60).median()
    C = pd.DataFrame(closes).sort_index()
    TM = pd.DataFrame(turns).reindex_like(C)
    return C, TM


def load_flags(dates, symbols):
    """Boolean flag-event matrix F (n_dates x n_sym). A True at [p, s] means a
    flag EVENT for symbol s landed on trading-day position p."""
    col = {s: i for i, s in enumerate(symbols)}
    dvals = dates.values
    F = np.zeros((len(dates), len(symbols)), dtype=bool)
    n_red = n_pead = 0

    # (a) red-flag announcement categories
    for f in sorted(ANN_DIR.glob('ann_*.csv')):
        a = pd.read_csv(f, usecols=['sort_date', 'symbol', 'desc'])
        a = a[a['desc'].isin(RED_FLAGS)]
        a = a[a['symbol'].isin(col)]
        if a.empty:
            continue
        d = pd.to_datetime(a['sort_date'], errors='coerce').dt.normalize()
        a = a.assign(d=d).dropna(subset=['d'])
        pos = np.searchsorted(dvals, a['d'].values, side='left')  # first trading day >= ann date
        for p, s in zip(pos, a['symbol'].values):
            if 0 <= p < len(dates):
                F[p, col[s]] = True
                n_red += 1

    # (b) results-miss (pead NEGATIVE) keyed by symbol + E_date
    p = pd.read_csv(PEAD, parse_dates=['E_date'])
    p = p[(p['bucket'] == 'NEGATIVE') & (p['symbol'].isin(col))]
    ed = p['E_date'].dt.normalize()
    pos = np.searchsorted(dvals, ed.values, side='left')
    for pp, s in zip(pos, p['symbol'].values):
        if 0 <= pp < len(dates):
            F[pp, col[s]] = True
            n_pead += 1
    return F, n_red, n_pead


def run_portfolio(dates, Rmat, Lgate, reb_pos, exclude_mask=None):
    """Vectorized monthly-rebalanced EW portfolio with weight-drift between
    rebalances and turnover cost at each rebalance.

    Rmat      : (D x S) daily returns, NaN->0.
    Lgate     : (D x S) bool liquid-gate mask.
    reb_pos   : sorted list of rebalance date positions.
    exclude_mask: (D x S) bool; if given, symbols True at a rebalance row are
                  excluded from that rebalance's constituents (treatment).
    Returns (port_ret series over dates, list of (date, n_liquid, n_excluded)).
    """
    D, S = Rmat.shape
    port_ret = np.zeros(D)
    w_prev = np.zeros(S)
    excl_log = []

    for i, p0 in enumerate(reb_pos):
        p1 = reb_pos[i + 1] if i + 1 < len(reb_pos) else D - 1
        liquid = Lgate[p0]
        n_liq = int(liquid.sum())
        held = liquid.copy()
        n_excl = 0
        if exclude_mask is not None:
            ex = liquid & exclude_mask[p0]
            n_excl = int(ex.sum())
            held = liquid & ~exclude_mask[p0]
        excl_log.append((dates[p0], n_liq, n_excl))
        idx = np.flatnonzero(held)
        if idx.size == 0:                       # degenerate: stay in cash
            w_prev = np.zeros(S)
            continue
        w_new = np.zeros(S)
        w_new[idx] = 1.0 / idx.size
        # turnover cost charged on the rebalance day
        turnover = 0.5 * np.abs(w_new - w_prev).sum()
        port_ret[p0] -= ROUND_TRIP * turnover
        # drift weights across the segment (p0, p1]
        v = w_new[idx].copy()
        prev_sum = v.sum()
        for d in range(p0 + 1, p1 + 1):
            v *= (1.0 + Rmat[d, idx])
            cur = v.sum()
            port_ret[d] += cur / prev_sum - 1.0
            prev_sum = cur
        w_prev = np.zeros(S)
        w_prev[idx] = v / v.sum()
    return pd.Series(port_ret, index=dates), excl_log


def metrics(port_ret, lo, hi):
    r = port_ret[(port_ret.index >= lo) & (port_ret.index <= hi)]
    r = r[r.index >= START]
    if len(r) < 2:
        return dict(cagr=float('nan'), sharpe=float('nan'), maxdd=float('nan'), n=len(r))
    eq = (1 + r).cumprod()
    yrs = len(r) / 252.0
    cagr = (eq.iloc[-1] ** (1 / yrs) - 1) * 100
    sharpe = r.mean() / r.std() * np.sqrt(252) if r.std() > 0 else 0.0
    maxdd = ((eq / eq.cummax()) - 1).min() * 100
    return dict(cagr=round(cagr, 2), sharpe=round(sharpe, 2), maxdd=round(maxdd, 1), n=len(r))


def main():
    C, TM = load()
    C = C[(C.index >= START) & (C.index <= END)]
    TM = TM.reindex(C.index)
    dates = C.index
    symbols = list(C.columns)
    D, Snum = C.shape
    out(f'universe loaded: {Snum} symbols, {D} trading days '
        f'{dates[0].date()} -> {dates[-1].date()}')

    Rmat = C.pct_change().clip(-CLIP, CLIP).fillna(0.0).values
    Lgate = ((TM.values > MIN_TURNOVER) & (C.values > MIN_PRICE) & C.notna().values)

    # rebalance = first trading day of each month
    ym = pd.Series(dates.year * 100 + dates.month, index=range(D))
    reb_pos = [0] + [i for i in range(1, D) if ym.iloc[i] != ym.iloc[i - 1]]

    # flags -> active-window mask
    F, n_red, n_pead = load_flags(dates, symbols)
    active = np.zeros((D, Snum), dtype=bool)     # active[p] = flagged in past 20 td incl p
    for p in range(D):
        active[p] = F[max(0, p - FLAG_LOOKBACK + 1):p + 1].any(axis=0)
    out(f'flag events placed: {n_red} red-flag (4 categories), {n_pead} results-miss NEGATIVE')
    out(f'rebalances: {len(reb_pos)} (monthly, first trading day)')

    base_ret, base_log = run_portfolio(dates, Rmat, Lgate, reb_pos, exclude_mask=None)
    treat_ret, treat_log = run_portfolio(dates, Rmat, Lgate, reb_pos, exclude_mask=active)

    windows = [('FULL 2020-2026', START, END),
               ('DEVELOP 2020-2022', START, DEV_END),
               ('VERDICT 2023-2026', pd.Timestamp('2023-01-01'), END)]

    out('')
    out('=' * 74)
    out('RESULTS: BASELINE (plain B&H EW)  vs  TREATMENT (B&H minus poison)')
    out('=' * 74)
    hdr = f'{"window":20} | {"BASE cagr  shrp   dd%":22} | {"TREAT cagr  shrp   dd%":22} | dCAGR'
    out(hdr)
    out('-' * len(hdr))
    wmetrics = {}
    for nm, lo, hi in windows:
        b = metrics(base_ret, lo, hi)
        t = metrics(treat_ret, lo, hi)
        wmetrics[nm] = (b, t)
        out(f'{nm:20} | {b["cagr"]:8} {b["sharpe"]:6} {b["maxdd"]:7} '
            f'| {t["cagr"]:8} {t["sharpe"]:6} {t["maxdd"]:7} '
            f'| {round(t["cagr"] - b["cagr"], 2):+}')

    # excluded-name counts per rebalance
    out('')
    out('EXCLUDED-NAME COUNTS PER REBALANCE (treatment): date | n_liquid | n_excluded | %')
    for (dt, nl, _), (_, _, ne) in zip(base_log, treat_log):
        pct = (100 * ne / nl) if nl else 0
        out(f'  {dt.date()} | {nl:4d} | {ne:4d} | {pct:5.1f}%')
    excl_counts = [ne for _, _, ne in treat_log]
    liq_counts = [nl for _, nl, _ in base_log]
    out(f'  excluded per rebalance: mean {np.mean(excl_counts):.1f}, '
        f'min {min(excl_counts)}, max {max(excl_counts)} '
        f'(of mean {np.mean(liq_counts):.0f} liquid names)')

    # ---------------- FROZEN VERDICT ----------------
    bd, td = wmetrics['DEVELOP 2020-2022']
    bv, tv = wmetrics['VERDICT 2023-2026']
    d_cagr_v = tv['cagr'] - bv['cagr']
    d_cagr_d = td['cagr'] - bd['cagr']
    dd_ok = tv['maxdd'] >= bv['maxdd'] - 1.0          # not worse than baseline +1pt
    c1 = d_cagr_v >= 0.5
    c2 = dd_ok
    c3 = d_cagr_d > 0.0                               # same direction in develop
    verdict_pass = c1 and c2 and c3

    out('')
    out('=' * 74)
    out('FROZEN VERDICT')
    out('=' * 74)
    out(f'(1) VERDICT-window CAGR edge >= +0.5 pts : '
        f'treat {tv["cagr"]:.2f} - base {bv["cagr"]:.2f} = {d_cagr_v:+.2f}  -> {"PASS" if c1 else "FAIL"}')
    out(f'(2) VERDICT-window maxDD no worse +1 pt  : '
        f'treat {tv["maxdd"]:.1f} vs base {bv["maxdd"]:.1f} (floor {bv["maxdd"]-1:.1f})  -> {"PASS" if c2 else "FAIL"}')
    out(f'(3) DEVELOP-window same direction (>0)   : '
        f'treat {td["cagr"]:.2f} - base {bd["cagr"]:.2f} = {d_cagr_d:+.2f}  -> {"PASS" if c3 else "FAIL"}')
    out('-' * 74)
    if verdict_pass:
        out('VERDICT: PASS -- B&H-minus-poison beats plain B&H after costs on all three')
        out('  frozen criteria. The avoid-signals upgrade the passive baseline.')
    else:
        out('VERDICT: TOMBSTONE -- B&H-minus-poison does NOT clear the frozen bar.')
        out('  Avoid-signals stay entry-gates for ACTIVE strategies only; not worth a')
        out('  passive overlay on the unbeaten B&H baseline.')
    out('=' * 74)

    OUT.write_text('\n'.join(_lines) + '\n', encoding='utf-8')
    print(f'\n[saved -> {OUT}]')


if __name__ == '__main__':
    main()
