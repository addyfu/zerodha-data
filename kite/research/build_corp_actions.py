"""Data acquisition for docs/superpowers/specs/2026-07-27-delivery-factor-design.md.

Builds a split/bonus price-adjustment table from the NSE corporate-actions
API, for use by kite/research/delivery_factor_study.py to make OPEN/CLOSE
price series continuous across corporate actions (brief rule R14 — bhavcopy
prices are NOT split/bonus adjusted).

API (verified working 2026-07-27, same cookie handshake + browser UA as
fetch_announcements.py's already-verified /api/corporate-announcements):
    https://www.nseindia.com/api/corporates-corporateActions
        ?index=equities&from_date=DD-MM-YYYY&to_date=DD-MM-YYYY
Returns a JSON list of records with (at least) symbol, series, faceVal,
exDate, subject. Fetched in 6-month chunks from 2019-07-01 (three months
before the bhavcopy data starts, so any action with an ex-date inside the
very first weeks of the study's price history is still caught) through
today.

WHAT WE PARSE (frozen, per spec):
  - Face-value splits: subject matches "Face Value Split (Sub-Division) -
    From Rs X Per Share To Rs Y Per Share" (case-insensitive, tolerant of
    "Rs." / "Rs " / minor spacing variants NSE actually uses).
    price factor = Y / X  (post-split face value / pre-split face value).
    A 10 -> 2 split makes each pre-split share become 5 post-split shares,
    so the pre-split PRICE must be multiplied by 2/10 = 0.2 to compare
    against post-split prices. factor = new_face/old_face = Y/X.
  - Bonus issues: subject matches "Bonus <a>:<b>" (a new shares issued for
    every b held). A holder of b shares ends up with (a+b) shares at the
    same total value, so the pre-bonus PRICE must be scaled down by
    b/(a+b) to be comparable post-bonus. factor = b / (a + b).

WHAT WE DELIBERATELY IGNORE (per spec — do not add these back without a
spec amendment):
  - Dividends (cash dividends do not change share count/face value; no
    price-continuity adjustment needed for this factor, and the spec
    explicitly treats dividend drag as a uniform, direction-neutral cost
    left unadjusted).
  - AGM/Board Meeting/EGM notices (no price effect).
  - Rights issues — EXCLUDED DELIBERATELY. Rights entitle existing holders
    to buy additional shares at a subscription price, which requires
    knowing the subscription price and ratio to compute a proper adjusted
    close (the standard "rights-adjusted close" formula), not just a share
    -count ratio like bonuses. NSE's corporate-actions `subject` field for
    rights issues is inconsistent about including the subscription price,
    so a conservative parser would silently mis-price a nontrivial share
    of rights actions. Since rights issues are rare for the liquid,
    turnover-gated universe this study uses (small/mid caps do rights
    issues far more than the large caps that clear TURNOVER_LACS >= 200),
    we exclude them rather than risk a silently wrong factor. If the study
    ever HALTs on a NaN-factor rights row inside its loaded panel (see
    delivery_factor_study.py's HALT-on-NaN-factor-match rule), that is the
    signal to come back and build a real rights-adjustment path — not to
    quietly guess a factor here.
  - Buybacks (do not change the continuing float's per-share economics in
    a way this simple multiplicative-factor table can represent; and like
    rights, requires knowing the buyback price/quantity, not just the
    `subject` text).

CONSERVATIVE PARSING RULE (per spec): if `subject` clearly mentions "Split"
or "Bonus" but the numbers cannot be extracted from it with the regexes
above (unexpected phrasing), we still emit a row with factor=NaN rather
than silently dropping it or guessing — factor=NaN rows are exactly the
tripwire delivery_factor_study.py's HALT check is built to catch if such a
row's symbol/ex_date ever falls inside the loaded price panel. A running
count of these unparseable-but-relevant rows is printed at the end.

OUTPUT CONVENTION (frozen, documented here and repeated in the study):
    data/corp_actions_adjustments.csv with columns symbol, ex_date, factor,
    subject. To make a price series continuous across an action, multiply
    every price dated STRICTLY BEFORE ex_date by `factor` (prices on/after
    ex_date are left as-is; the exchange itself already prices the stock
    post-action from the ex-date open). Multiple actions for the same
    symbol compound: a price far enough in the past to precede two ex-dates
    gets multiplied by both factors (the study applies them cumulatively,
    working backwards from the most recent action).

ONLY series == 'EQ' rows are kept (matches the study's universe filter;
non-EQ series (BE, SM, etc.) are out of scope for this factor).

Usage:
    python kite/research/build_corp_actions.py
    python kite/research/build_corp_actions.py --start 2024-01-01 --end 2024-12-31
"""
import argparse
import re
import sys
import time
from datetime import date, timedelta
from pathlib import Path

import pandas as pd
import requests

ROOT = Path(__file__).resolve().parents[2]
OUT_PATH = ROOT / 'data' / 'corp_actions_adjustments.csv'

BASE = "https://www.nseindia.com/api"
UA = 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36'
HEADERS = {
    "User-Agent": UA,
    "Accept": "*/*",
    "Accept-Language": "en-US,en;q=0.9",
    "Accept-Encoding": "gzip, deflate",
    "Referer": "https://www.nseindia.com/companies-listing/corporate-filings-actions",
}

DEFAULT_START = date(2019, 7, 1)
CHUNK_MONTHS = 6
SLEEP_SEC = 1.0
MAX_RETRIES = 3

# "Face Value Split (Sub-Division) - From Rs 10 Per Share To Rs 2 Per Share"
# (also tolerate "Rs." / "Rs.10" / extra spaces, AND NSE's grammatically-singular
# "Re 1/- Per Share" when the post-split face value is Rs 1 -- verified 2026-07-28
# against real 2024 data: ~30/95 real split rows use "To Re 1/- Per Share", not
# "To Rs 1/- Per Share", and were silently falling into the NaN/unparseable
# bucket before this was caught by a self-check run).
SPLIT_RE = re.compile(
    r'from\s+r[se]\.?\s*(\d+(?:\.\d+)?)\s*(?:/-)?\s*per\s+share\s+to\s+r[se]\.?\s*(\d+(?:\.\d+)?)\s*(?:/-)?\s*per\s+share',
    re.IGNORECASE,
)
# "Bonus 1:1", "Bonus Issue 4:5", "Bonus 1 : 1" etc.
BONUS_RE = re.compile(r'bonus[^0-9]*?(\d+)\s*:\s*(\d+)', re.IGNORECASE)


def get_session():
    s = requests.Session()
    s.headers.update(HEADERS)
    r = s.get("https://www.nseindia.com/companies-listing/corporate-filings-actions", timeout=15)
    r.raise_for_status()
    return s


def month_chunks(start, end, months=CHUNK_MONTHS):
    """Yield (from_date, to_date) date pairs covering [start, end] in
    `months`-month chunks, inclusive, clipped to end."""
    cur = start
    while cur <= end:
        # advance `months` months from cur
        y = cur.year + (cur.month - 1 + months) // 12
        m = (cur.month - 1 + months) % 12 + 1
        nxt = date(y, m, 1) - timedelta(days=1)
        chunk_end = min(nxt, end)
        yield cur, chunk_end
        cur = chunk_end + timedelta(days=1)


def fetch_chunk(session, frm, to):
    r = session.get(
        f"{BASE}/corporates-corporateActions",
        params={"index": "equities",
                "from_date": frm.strftime('%d-%m-%Y'),
                "to_date": to.strftime('%d-%m-%Y')},
        timeout=60,
    )
    if r.status_code in (401, 403):
        raise PermissionError(f"HTTP {r.status_code}")
    r.raise_for_status()
    records = r.json()
    if not isinstance(records, list):
        raise ValueError(f"unexpected payload type: {type(records).__name__}")
    return records


def fetch_chunk_with_retries(session, frm, to):
    tag = f'{frm.isoformat()}..{to.isoformat()}'
    last_err = None
    for attempt in range(1, MAX_RETRIES + 1):
        try:
            return fetch_chunk(session, frm, to), session
        except (PermissionError, requests.RequestException, ValueError) as e:
            last_err = e
            print(f'  [{tag}] attempt {attempt}/{MAX_RETRIES} failed: {type(e).__name__}: {e} -- re-warming session',
                  flush=True)
            time.sleep(2)
            try:
                session = get_session()
            except Exception as e2:
                print(f'  [{tag}] re-warm failed: {type(e2).__name__}: {e2}', flush=True)
            time.sleep(SLEEP_SEC)
    print(f'[{tag}] FAILED after {MAX_RETRIES} attempts: {type(last_err).__name__}: {last_err}', flush=True)
    return None, session


def parse_subject(subject):
    """Return (factor, kind) for one corp-action `subject` string.
    kind in {'split', 'bonus', 'other'}. factor is float, or NaN if the
    subject is a split/bonus we could not extract numbers from. 'other'
    rows (dividends/AGM/rights/buyback/etc.) are filtered out by the
    caller before this is even invoked for anything but split/bonus
    candidates -- see fetch_and_build().
    """
    m = SPLIT_RE.search(subject)
    if m:
        old_fv, new_fv = float(m.group(1)), float(m.group(2))
        if old_fv > 0:
            return new_fv / old_fv, 'split'
        return float('nan'), 'split'
    m = BONUS_RE.search(subject)
    if m:
        a, b = float(m.group(1)), float(m.group(2))
        if (a + b) > 0:
            return b / (a + b), 'bonus'
        return float('nan'), 'bonus'
    return None, None  # not a split/bonus subject at all


def is_relevant_candidate(subject):
    """True if the subject text plausibly describes a split or bonus, even
    if parse_subject() can't extract numbers from it (conservative-parsing
    tripwire per module docstring).

    Bonus DEBENTURES are excluded (2026-07-28, reviewer): e.g. BRITANNIA's
    "Scheme Of Arangement- Bonus - 1 Debenture For 1 Equity Share Held" hands
    out debentures, not shares -- equity share count is unchanged, so no
    price-continuity factor applies. Economically it's a special-dividend-like
    distribution, which the frozen spec deliberately leaves unadjusted (same
    treatment as cash dividends). Without this exclusion the conservative
    tripwire correctly flagged these rows as NaN and the study HALTed."""
    s = subject.lower()
    if 'debenture' in s:
        return False
    return ('split' in s and 'face value' in s) or 'sub-division' in s or 'bonus' in s


def build_table(records):
    """records: list of raw NSE corporate-action dicts. Returns
    (DataFrame[symbol, ex_date, factor, subject], n_unparseable)."""
    rows = []
    n_unparseable = 0
    for rec in records:
        series = str(rec.get('series', '')).strip()
        if series != 'EQ':
            continue
        subject = str(rec.get('subject', '') or '').strip()
        if not subject:
            continue
        if not is_relevant_candidate(subject):
            continue  # dividends / AGM / rights / buyback / etc. -- ignored per spec
        symbol = str(rec.get('symbol', '') or '').strip()
        ex_date_raw = str(rec.get('exDate', '') or '').strip()
        if not symbol or not ex_date_raw:
            continue
        try:
            ex_date = pd.to_datetime(ex_date_raw, dayfirst=True).date()
        except (ValueError, TypeError):
            continue
        factor, kind = parse_subject(subject)
        if factor is None:
            # is_relevant_candidate said split/bonus-ish but neither regex
            # matched at all -- still a tripwire row.
            n_unparseable += 1
            factor = float('nan')
        elif pd.isna(factor):
            n_unparseable += 1
        rows.append({'symbol': symbol, 'ex_date': ex_date.isoformat(),
                      'factor': factor, 'subject': subject})
    df = pd.DataFrame(rows, columns=['symbol', 'ex_date', 'factor', 'subject'])
    if not df.empty:
        df = df.drop_duplicates(subset=['symbol', 'ex_date', 'subject']).sort_values(
            ['symbol', 'ex_date']).reset_index(drop=True)
    return df, n_unparseable


def fetch_and_build(start, end):
    session = get_session()
    all_records = []
    chunks = list(month_chunks(start, end))
    for i, (frm, to) in enumerate(chunks, 1):
        records, session = fetch_chunk_with_retries(session, frm, to)
        if records is None:
            print(f'  [{i}/{len(chunks)}] {frm}..{to}: FAILED, skipping this chunk', flush=True)
            continue
        all_records.extend(records)
        print(f'  [{i}/{len(chunks)}] {frm}..{to}: {len(records)} raw records (running total {len(all_records)})',
              flush=True)
        time.sleep(SLEEP_SEC)

    df, n_unparseable = build_table(all_records)
    return df, n_unparseable, len(all_records)


def parse_args():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('--start', type=str, default=None,
                    help='YYYY-MM-DD, default 2019-07-01')
    p.add_argument('--end', type=str, default=None,
                    help='YYYY-MM-DD, default today')
    return p.parse_args()


def main():
    args = parse_args()
    start = date.fromisoformat(args.start) if args.start else DEFAULT_START
    end = date.fromisoformat(args.end) if args.end else date.today()
    if start > end:
        sys.exit(f'--start {start} is after --end {end}')

    print(f'Fetching NSE corporate actions {start.isoformat()} -> {end.isoformat()} '
          f'in {CHUNK_MONTHS}-month chunks ...')
    df, n_unparseable, n_raw = fetch_and_build(start, end)

    OUT_PATH.parent.mkdir(parents=True, exist_ok=True)
    df.to_csv(OUT_PATH, index=False)

    n_split = int((df['subject'].str.contains('split', case=False, na=False) |
                   df['subject'].str.contains('sub-division', case=False, na=False)).sum()) if not df.empty else 0
    n_bonus = int(df['subject'].str.contains('bonus', case=False, na=False).sum()) if not df.empty else 0
    n_nan = int(df['factor'].isna().sum()) if not df.empty else 0

    print('')
    print('=' * 78)
    print('CORP ACTIONS SUMMARY')
    print('=' * 78)
    print(f'  Raw records fetched (all subjects, all series): {n_raw}')
    print(f'  Rows kept (series==EQ, split/bonus subjects)  : {len(df)}')
    print(f'    of which split-like                         : {n_split}')
    print(f'    of which bonus-like                          : {n_bonus}')
    print(f'  Unparseable (factor=NaN) rows                 : {n_unparseable} (WARNING count)')
    print(f'  Output                                         : {OUT_PATH}')
    print('=' * 78)
    if n_nan > 0:
        print(f'WARNING: {n_nan} rows have factor=NaN -- these are split/bonus-worded subjects whose')
        print('numbers could not be parsed. delivery_factor_study.py HALTS if any of these rows')
        print('matches a symbol-date inside its loaded price panel (frozen HALT rule).')


if __name__ == '__main__':
    main()
