"""Data acquisition: NSE bulk deals, block deals, and short-selling
disclosures, market-wide (all symbols), 2005-01-01 -> today, one CSV per
year per type into data/bulk_deals/{bulk|block|short}_YYYY.csv.

Endpoint (verified LIVE 2026-07-28 -- see scratchpad/recon2/ for the
frontend JS that calls it, and this docstring for the actual response
samples the recon agent's notes didn't capture):
    GET https://www.nseindia.com/api/historicalOR/bulk-block-short-deals
        ?optionType={bulk_deals|block_deals|short_selling}
        &from=DD-MM-YYYY&to=DD-MM-YYYY
Required headers: browser User-Agent + Referer matching the live report
page (https://www.nseindia.com/report-detail/display-bulk-and-block-deals).
/api/historical/bulk-deals (no "OR") is Akamai-blocked -- 503 on every
attempt during recon, see scratchpad/recon2/nse_out.txt. The "OR" path is
what the report page's own JS calls (bulk-block-deals-short-selling.js,
saved under scratchpad/recon2/) and is not blocked.

SURPRISES FOUND DURING LIVE VERIFICATION (2026-07-28, not just recon
notes -- confirmed with real requests before writing this script):
  - Date range is capped: a 517-day request (01-01-2023..01-06-2024)
    returned HTTP 500 with a 5-byte "Error" body (no JSON at all).
    Chunking to <=90 days per call stays well clear of this and lines up
    with the task's "~5 calls/year/type" estimate (366/90 -> 5 chunks).
  - bulk_deals and block_deals share an IDENTICAL schema, fields prefixed
    BD_*: BD_DT_DATE, BD_DT_ORDER, BD_SYMBOL, BD_SCRIP_NAME,
    BD_CLIENT_NAME, BD_BUY_SELL, BD_QTY_TRD, BD_TP_WATP, BD_REMARKS.
    There is NO separate buyer/seller column pair -- one row per
    (symbol, client, side), same convention as the public archives
    bulk.csv. "BD_BUY_SELL" tells you which side BD_CLIENT_NAME was on.
  - short_selling has a smaller, different schema (SS_*): SS_DATE,
    SS_DATE_ORDER, SS_SYMBOL, SS_NAME, SS_QTY -- no client name, no
    side, no price (short-sell disclosures are aggregate qty only).
  - The cookie handshake (GET https://www.nseindia.com/ before hitting
    /api/..., as in fetch_bhavcopy_full.py) returned HTTP 403 with ZERO
    cookies set on every attempt during live verification -- yet the
    actual /api/historicalOR/... call still succeeded (HTTP 200)
    immediately afterward on the SAME cold session, no cookies, as long
    as browser User-Agent + a matching Referer were present on the
    request itself. The handshake is still attempted here (cheap, and
    NSE's bot detection may tighten later) but its failure is NOT
    treated as fatal -- fetch_bhavcopy_full.py's get_session() calls
    r.raise_for_status() on the handshake, which would abort this script
    immediately given the above, so that call is deliberately omitted.

Politeness / robustness (matches kite/research/fetch_bhavcopy_full.py):
  - requests.Session with a browser User-Agent and a Referer matching the
    live report page.
  - ~1 request/second (time.sleep(1) after every attempt).
  - Each chunk gets up to 2 retries (3 attempts total) with a 5s backoff
    on exceptions, non-200 status, or bad/unexpected JSON.
  - Resumable: a year's CSV already on disk (any size > 0, since a file
    is only ever written after ALL of that year's chunks succeed) is
    skipped without a network call -- EXCEPT the current year, which is
    always refetched (new deals are disclosed daily all year).
  - If any chunk within a year fails after retries, that year's file is
    NOT written (so it stays resumable) and the year is counted failed.
  - Progress printed per year/type; final summary counts
    fetched / skipped-existing / empty / failed.

Usage:
    python kite/research/fetch_bulk_block_deals.py
    python kite/research/fetch_bulk_block_deals.py --start 2024-01-01 --end 2024-02-29
"""
import argparse
import csv
import io
import sys
import time
from datetime import date, timedelta
from pathlib import Path

import pandas as pd
import requests

ROOT = Path(__file__).resolve().parents[2]
OUT_DIR = ROOT / 'data' / 'bulk_deals'

API_URL = "https://www.nseindia.com/api/historicalOR/bulk-block-short-deals"
UA = 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36'
HEADERS = {
    "User-Agent": UA,
    "Accept": "*/*",
    "Accept-Language": "en-US,en;q=0.9",
    "Referer": "https://www.nseindia.com/report-detail/display-bulk-and-block-deals",
}

# optionType (API param) -> (file prefix, fallback columns for an empty year)
OPTION_TYPES = {
    'bulk_deals': (
        'bulk',
        ['BD_DT_DATE', 'BD_DT_ORDER', 'BD_SYMBOL', 'BD_SCRIP_NAME',
         'BD_CLIENT_NAME', 'BD_BUY_SELL', 'BD_QTY_TRD', 'BD_TP_WATP', 'BD_REMARKS'],
    ),
    'block_deals': (
        'block',
        ['BD_DT_DATE', 'BD_DT_ORDER', 'BD_SYMBOL', 'BD_SCRIP_NAME',
         'BD_CLIENT_NAME', 'BD_BUY_SELL', 'BD_QTY_TRD', 'BD_TP_WATP', 'BD_REMARKS'],
    ),
    'short_selling': (
        'short',
        ['SS_DATE', 'SS_DATE_ORDER', 'SS_SYMBOL', 'SS_NAME', 'SS_QTY'],
    ),
}

DEFAULT_START = date(2005, 1, 1)
CHUNK_DAYS = 30             # 2026-07-28: dropped from 90 after the silent 70-row
                            # JSON cap was found — small chunks keep any hidden
                            # CSV-side cap out of reach (~12 calls/year/type)
REQUEST_SLEEP_SEC = 1.0
MAX_ATTEMPTS = 3            # 1 try + 2 retries
RETRY_BACKOFF_SEC = 5.0


def get_session():
    """Best-effort cookie warm-up. NOT treated as fatal if it 403s -- see
    module docstring: the historicalOR endpoint works fine on a cold
    session with no cookies as long as UA+Referer are set per-request."""
    s = requests.Session()
    s.headers.update(HEADERS)
    try:
        r = s.get("https://www.nseindia.com", timeout=15)
        print(f'  [session] handshake status={r.status_code} cookies={list(s.cookies.keys())}', flush=True)
    except requests.RequestException as e:
        print(f'  [session] handshake error (non-fatal): {type(e).__name__}: {e}', flush=True)
    return s


def iter_chunks(start, end, max_days):
    """Yield (chunk_start, chunk_end) date pairs covering [start, end]
    inclusive, each spanning at most max_days days."""
    cur = start
    step = timedelta(days=max_days - 1)
    while cur <= end:
        chunk_end = min(cur + step, end)
        yield cur, chunk_end
        cur = chunk_end + timedelta(days=1)


def fetch_chunk(session, option_type, start, end):
    """One optionType/date-range call with retries+backoff. Returns a list
    of record dicts on success, or None if all attempts failed.

    2026-07-28 reviewer fix: the JSON path SILENTLY CAPS every response at
    ~70 rows (HTTP 200, no error, no pagination hint) — the first full-history
    run truncated 21 years of bulk deals to ~1 row/day and reported success.
    csv=true (same trick as the vixhistory endpoint) returns the FULL result
    set (verified: 2,564 rows for Jun-2024 vs 70 via JSON). We now request
    csv=true and parse the CSV. Chunks were also dropped 90d -> ~30d to keep
    any hidden CSV-side cap out of reach; a chunk whose row count lands
    suspiciously at exactly 70 aborts loudly rather than saving."""
    params = {
        "optionType": option_type,
        "from": start.strftime('%d-%m-%Y'),
        "to": end.strftime('%d-%m-%Y'),
        "csv": "true",
    }
    last_err = None
    for attempt in range(1, MAX_ATTEMPTS + 1):
        try:
            r = session.get(API_URL, params=params, timeout=60)
        except requests.RequestException as e:
            last_err = f'{type(e).__name__}: {e}'
            if attempt < MAX_ATTEMPTS:
                time.sleep(RETRY_BACKOFF_SEC)
            continue
        if r.status_code != 200:
            last_err = f'HTTP {r.status_code}'
            if attempt < MAX_ATTEMPTS:
                time.sleep(RETRY_BACKOFF_SEC)
            continue
        text = r.content.decode('utf-8-sig', errors='replace')
        lines = [ln for ln in text.splitlines() if ln.strip()]
        if not lines or ',' not in lines[0]:
            last_err = f'unexpected CSV body: {text[:80]!r}'
            if attempt < MAX_ATTEMPTS:
                time.sleep(RETRY_BACKOFF_SEC)
            continue
        reader = csv.DictReader(io.StringIO(text))
        # normalize NSE's trailing-space headers ("Date ", "Symbol ", ...)
        records = [{(k or '').strip(): (v or '').strip() for k, v in row.items()}
                   for row in reader]
        if len(records) == 70:
            # exactly the JSON cap — refuse to trust it; treat as an error so
            # a regressed endpoint can never silently truncate again
            last_err = 'row count == 70 (the silent JSON cap) — refusing to save'
            if attempt < MAX_ATTEMPTS:
                time.sleep(RETRY_BACKOFF_SEC)
            continue
        return records
    print(f'    FAILED chunk {start.isoformat()}..{end.isoformat()} ({option_type}) '
          f'after {MAX_ATTEMPTS} attempts: {last_err}', flush=True)
    return None


def fetch_year(session, option_type, year, range_start, range_end):
    """Fetch every chunk for one (option_type, year), clipped to
    [range_start, range_end]. Returns (records, ok) -- ok=False means at
    least one chunk failed after retries; caller should not save."""
    y_start = max(range_start, date(year, 1, 1))
    y_end = min(range_end, date(year, 12, 31))
    all_records = []
    ok = True
    for c_start, c_end in iter_chunks(y_start, y_end, CHUNK_DAYS):
        records = fetch_chunk(session, option_type, c_start, c_end)
        time.sleep(REQUEST_SLEEP_SEC)
        if records is None:
            ok = False
            continue
        all_records.extend(records)
    return all_records, ok


def out_path(prefix, year):
    return OUT_DIR / f'{prefix}_{year}.csv'


def already_done(path, current_year_tag, this_year_tag):
    if current_year_tag == this_year_tag:
        return False  # current year always refetched
    return path.exists() and path.stat().st_size > 0


def download_range(start, end):
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    session = get_session()

    years = list(range(start.year, end.year + 1))
    current_year = date.today().year

    fetched = skipped_existing = empty = failed = 0
    failed_combos = []
    total_records = 0

    for year in years:
        for option_type, (prefix, fallback_cols) in OPTION_TYPES.items():
            path = out_path(prefix, year)
            if already_done(path, current_year, year):
                skipped_existing += 1
                print(f'[{year} {option_type}] skip (existing)', flush=True)
                continue

            records, ok = fetch_year(session, option_type, year, start, end)
            if not ok:
                failed += 1
                failed_combos.append(f'{year}:{option_type}')
                print(f'[{year} {option_type}] FAILED (partial data discarded, resumable)', flush=True)
                continue

            df = pd.DataFrame(records) if records else pd.DataFrame(columns=fallback_cols)
            df.to_csv(path, index=False, encoding='utf-8')
            fetched += 1
            total_records += len(df)
            if not records:
                empty += 1
            print(f'[{year} {option_type}] {len(df)} records -> {path.name}', flush=True)

    print('')
    print('=' * 78)
    print('FETCH SUMMARY')
    print('=' * 78)
    print(f'  Range requested    : {start.isoformat()} -> {end.isoformat()}')
    print(f'  Year x type combos : {len(years) * len(OPTION_TYPES)}')
    print(f'  Fetched (new)      : {fetched}  (~{total_records} total records)')
    print(f'  Skipped (existing) : {skipped_existing}')
    print(f'  Empty (0 records)  : {empty}')
    print(f'  Failed             : {failed}')
    if failed_combos:
        print(f'  Failed combos (re-run this script to retry -- resumable): {failed_combos}')
    print('=' * 78)
    return {'fetched': fetched, 'skipped_existing': skipped_existing,
            'empty': empty, 'failed': failed, 'failed_combos': failed_combos}


def parse_args():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('--start', type=str, default=None, help='YYYY-MM-DD, default 2005-01-01')
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
