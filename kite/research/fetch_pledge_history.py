"""Data acquisition: NSE promoter/promoter-group share pledge disclosures
(SAST Regulation 31(1) & 31(2), i.e. "sast3132"), market-wide (no symbol
filter), 2015-01-01 -> today, one CSV per month into
data/pledge/pledge_YYYY-MM.csv.

Endpoint (verified LIVE 2026-07-28, response shape confirmed with real
requests -- scratchpad/recon2/ has the page HTML and frontend JS
(corporate-filings.js) that reference this API but did not capture a live
response body, so this docstring records what was actually observed):
    GET https://www.nseindia.com/api/corporate-pledgedata-sast3132
        ?index=equities&from_date=DD-MM-YYYY&to_date=DD-MM-YYYY
Required header: Referer matching the live report page
(https://www.nseindia.com/companies-listing/corporate-filings-regulation-31
-- NSE's nav calls this tab "Regulation 31(1) & 31(2)", which is where the
"sast3132" endpoint name comes from; see corporate-filings.js).

Response shape: {"promoterNameList": [...], "data": [...]}. Only "data" is
kept -- one row per pledge/release/invocation event -- with ALL its fields
(attachment, broadcastdate, companyName, encumbHolding, encumbPerc,
eventDate, eventDetailsEntity, eventDetailsFromDate, eventDetailsHolding,
eventDetailsPerc, eventDetailsToDate, eventDetailsType,
eventDetailsTypeEncumb, postEventHolding, postEventHoldingPerc,
preeventHolding, preeventHoldingPerc, preeventHoldingShare, promoterName,
reportingDate, seqId, symbol, sysTime, timeDifference -- confirmed
identical across a 2015 sample and a 2024 sample). promoterNameList is a
UI autocomplete helper, not disclosure data, and is discarded.

SURPRISE FOUND DURING LIVE VERIFICATION: unlike bulk/block deals, a full
366-day request (01-01-2024..31-12-2024) returned HTTP 200 with 964
records -- no ~365-day hard cap observed here. Monthly chunks are used
anyway because the task wants one file per month, not because the API
requires it.

Politeness / robustness: structurally the same recipe as the existing
kite/research/fetch_announcements.py (also an NSE /api/ monthly-chunked
puller) -- browser UA, best-effort cookie handshake (non-fatal on
failure: see fetch_bulk_block_deals.py's docstring -- the handshake
reliably 403s with zero cookies during live verification, yet the actual
/api/ call still succeeds regardless, as long as UA+Referer are set on
the request itself), ~1.5s between requests, 3 attempts per month with a
session re-warm on failure, resumable (skips existing non-empty month
files -- EXCEPT the current month, always refetched since it accrues new
disclosures all month), progress logged, final summary.

Usage:
    python kite/research/fetch_pledge_history.py
    python kite/research/fetch_pledge_history.py --start 2024-01-01 --end 2024-02-29
"""
import argparse
import calendar
import json
import sys
import time
from datetime import date
from pathlib import Path

import pandas as pd
import requests

ROOT = Path(__file__).resolve().parents[2]
OUT_DIR = ROOT / 'data' / 'pledge'

API_URL = "https://www.nseindia.com/api/corporate-pledgedata-sast3132"
UA = 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36'
HEADERS = {
    "User-Agent": UA,
    "Accept": "*/*",
    "Accept-Language": "en-US,en;q=0.9",
    "Referer": "https://www.nseindia.com/companies-listing/corporate-filings-regulation-31",
}

FALLBACK_COLUMNS = [
    'attachment', 'broadcastdate', 'companyName', 'encumbHolding', 'encumbPerc',
    'eventDate', 'eventDetailsEntity', 'eventDetailsFromDate', 'eventDetailsHolding',
    'eventDetailsPerc', 'eventDetailsToDate', 'eventDetailsType', 'eventDetailsTypeEncumb',
    'postEventHolding', 'postEventHoldingPerc', 'preeventHolding', 'preeventHoldingPerc',
    'preeventHoldingShare', 'promoterName', 'reportingDate', 'seqId', 'symbol', 'sysTime',
    'timeDifference',
]

DEFAULT_START = date(2015, 1, 1)
SLEEP_SEC = 1.5
MAX_RETRIES = 3


def get_session():
    """Best-effort cookie warm-up -- see module docstring, non-fatal."""
    s = requests.Session()
    s.headers.update(HEADERS)
    try:
        r = s.get("https://www.nseindia.com", timeout=15)
        print(f'  [session] handshake status={r.status_code} cookies={list(s.cookies.keys())}', flush=True)
    except requests.RequestException as e:
        print(f'  [session] handshake error (non-fatal): {type(e).__name__}: {e}', flush=True)
    return s


def month_bounds(year, month):
    """Return (from_dt, to_dt) as 'dd-mm-yyyy' strings covering the given
    month, clipped to today if the month is the current (in-progress) one."""
    last_day = calendar.monthrange(year, month)[1]
    start = date(year, month, 1)
    end = date(year, month, last_day)
    today = date.today()
    if end > today:
        end = today
    return start.strftime('%d-%m-%Y'), end.strftime('%d-%m-%Y')


def iter_months(start_year, start_month, end):
    y, m = start_year, start_month
    while (y, m) <= (end.year, end.month):
        yield y, m
        m += 1
        if m > 12:
            m = 1
            y += 1


def fetch_month(session, year, month):
    """Fetch one month of pledge disclosures. Returns a DataFrame with ALL
    fields NSE returns (dynamic columns), deduped on seqId. Raises on any
    recognizable failure so the caller can retry with a re-warmed session."""
    from_dt, to_dt = month_bounds(year, month)
    r = session.get(
        API_URL,
        params={"index": "equities", "from_date": from_dt, "to_date": to_dt},
        timeout=60,
    )
    if r.status_code in (401, 403):
        raise PermissionError(f"HTTP {r.status_code}")
    r.raise_for_status()
    payload = r.json()
    if not isinstance(payload, dict) or 'data' not in payload:
        raise ValueError(f"unexpected payload shape: "
                          f"{list(payload.keys()) if isinstance(payload, dict) else type(payload).__name__}")
    records = payload['data']
    if not isinstance(records, list):
        raise ValueError(f"unexpected 'data' type: {type(records).__name__}")

    if records:
        df = pd.DataFrame(records)
        if 'seqId' in df.columns:
            df['seqId'] = df['seqId'].astype(str)
            df = df.drop_duplicates(subset='seqId', keep='last')
    else:
        df = pd.DataFrame(columns=FALLBACK_COLUMNS)
    return df


def fetch_month_with_retries(session, year, month):
    tag = f'{year:04d}-{month:02d}'
    last_err = None
    for attempt in range(1, MAX_RETRIES + 1):
        try:
            df = fetch_month(session, year, month)
            return df, session
        except (PermissionError, requests.RequestException, json.JSONDecodeError, ValueError) as e:
            last_err = e
            print(f'  [{tag}] attempt {attempt}/{MAX_RETRIES} failed: {type(e).__name__}: {e} '
                  f'-- re-warming session', flush=True)
            time.sleep(2)
            try:
                session = get_session()
            except Exception as e2:
                print(f'  [{tag}] re-warm failed: {type(e2).__name__}: {e2}', flush=True)
            time.sleep(SLEEP_SEC)
    print(f'[{tag}] FAILED after {MAX_RETRIES} attempts: {type(last_err).__name__}: {last_err}', flush=True)
    return None, session


def download_range(start, end):
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    session = get_session()

    months = list(iter_months(start.year, start.month, end))
    today = date.today()
    current_tag = (today.year, today.month)

    fetched = skipped_existing = empty = failed = 0
    total_records = 0
    failed_months = []

    for y, m in months:
        tag = f'{y:04d}-{m:02d}'
        out = OUT_DIR / f'pledge_{tag}.csv'
        if (y, m) != current_tag and out.exists() and out.stat().st_size > 0:
            skipped_existing += 1
            continue

        df, session = fetch_month_with_retries(session, y, m)
        if df is None:
            failed += 1
            failed_months.append(tag)
            continue

        df.to_csv(out, index=False, encoding='utf-8')
        fetched += 1
        total_records += len(df)
        if len(df) == 0:
            empty += 1
        print(f'[{tag}] {len(df)} records -> {out.name}', flush=True)
        time.sleep(SLEEP_SEC)

    print('')
    print('=' * 78)
    print('FETCH SUMMARY')
    print('=' * 78)
    print(f'  Range requested    : {start.isoformat()} -> {end.isoformat()} (monthly)')
    print(f'  Months requested   : {len(months)}')
    print(f'  Fetched (new)      : {fetched}  (~{total_records} total records)')
    print(f'  Skipped (existing) : {skipped_existing}')
    print(f'  Empty (0 records)  : {empty}')
    print(f'  Failed             : {failed}')
    if failed_months:
        print(f'  Failed months (re-run this script to retry -- resumable): {failed_months}')
    print('=' * 78)
    return {'fetched': fetched, 'skipped_existing': skipped_existing,
            'empty': empty, 'failed': failed, 'failed_months': failed_months}


def parse_args():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('--start', type=str, default=None, help='YYYY-MM-DD, default 2015-01-01')
    p.add_argument('--end', type=str, default=None, help='YYYY-MM-DD, default today')
    return p.parse_args()


def main():
    args = parse_args()
    start = date.fromisoformat(args.start) if args.start else DEFAULT_START
    end = date.fromisoformat(args.end) if args.end else date.today()
    if start > end:
        sys.exit(f'--start {start} is after --end {end}')
    download_range(start, end)


if __name__ == '__main__':
    main()
