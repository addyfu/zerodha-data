"""Data acquisition for docs/superpowers/specs/2026-07-27-delivery-factor-design.md.

Downloads NSE "security-wise bhavdata full" daily CSVs (price + delivery
quantity/percentage, all series) from the public archive, one file per
trading day, into data/bhavcopy_full/. This is the raw input for
kite/research/delivery_factor_study.py (DELIV_QTY / DELIV_PER columns).

URL (verified working 2026-07-27, no auth needed once cookies are warm):
    https://archives.nseindia.com/products/content/sec_bhavdata_full_DDMMYYYY.csv
Earliest available ~Oct 2019 (DELIV_QTY/DELIV_PER not published before that
in this merged file — see spec's "Data (frozen)" section). A 404 on a
weekday means a market holiday, not a real failure; those are counted and
skipped silently (no retry — retrying a 404 wastes calls for nothing).

SURPRISE FOUND DURING SELF-CHECK (2026-07-28, verified against a real
Dec2023-Mar2024 pull, not assumed): archives.nseindia.com does NOT always
404 on a market holiday. For at least 6 of 86 real weekdays in that pull
(2023-12-25 Christmas, 2024-01-22 Ram Mandir holiday, 2024-01-26 Republic
Day, 2024-03-08 Mahashivratri, 2024-03-25 Holi, 2024-03-29 Good Friday) the
server returned HTTP 200 with the PREVIOUS trading day's file content —
same bytes, wrong requested date — instead of a 404. Saving that under the
requested date's filename would silently duplicate a trading day's data
under two different dates and corrupt every downstream computation keyed
on date (rolling windows, corp-action back-adjustment, the weekly
calendar). Fix: every downloaded file's first data row's DATE1 field is
checked against the requested date (_extract_first_date1); a mismatch is
treated exactly like a holiday (not saved, counted in holiday_stale_data,
folded into the holiday total) rather than as a successful download.

Politeness / robustness (per spec, do not change without re-reading it):
  - requests.Session with a browser User-Agent (archives.nseindia.com 403s
    on the default python-requests UA).
  - Initial GET to https://www.nseindia.com warms the session cookies
    BEFORE the first archive request; archives.nseindia.com is a separate
    host from www.nseindia.com/api but shares the same anti-bot front door
    and 403s without a cookie handshake first, same as the pattern already
    verified working in fetch_announcements.py for the /api host.
  - ~1 request/second (time.sleep(1) after every attempt, success or not).
  - Each file gets up to 2 retries (3 attempts total) with a 5s backoff on
    exceptions or HTTP 5xx. Two CONSECUTIVE failed files (after their own
    retries are exhausted) trigger a fresh cookie handshake before
    continuing, in case the session went stale mid-run.
  - Resumable: a file already on disk with size > 10KB is treated as
    already-downloaded and skipped without a network call. (10KB floor
    catches truncated/error-page saves from a prior interrupted run — a
    real day's CSV covering the whole NSE EQ+other-series universe is
    hundreds of KB.)
  - Progress printed every 50 files attempted; final summary counts
    downloaded / skipped-existing / holiday-404 / failed.

Usage:
    python kite/research/fetch_bhavcopy_full.py
    python kite/research/fetch_bhavcopy_full.py --start 2024-01-01 --end 2024-01-10
"""
import argparse
import sys
import time
from datetime import date, datetime, timedelta
from pathlib import Path

import requests

ROOT = Path(__file__).resolve().parents[2]
OUT_DIR = ROOT / 'data' / 'bhavcopy_full'

ARCHIVE_BASE = "https://archives.nseindia.com/products/content"
UA = 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36'
HEADERS = {
    "User-Agent": UA,
    "Accept": "text/csv,application/octet-stream,*/*",
    "Accept-Language": "en-US,en;q=0.9",
    "Referer": "https://www.nseindia.com/all-reports",
}

DEFAULT_START = date(2019, 10, 1)
MIN_FILE_BYTES = 10 * 1024  # 10KB floor for "already downloaded, valid"
REQUEST_SLEEP_SEC = 1.0
MAX_ATTEMPTS = 3            # 1 try + 2 retries
RETRY_BACKOFF_SEC = 5.0
PROGRESS_EVERY = 50


def get_session():
    """Warm cookies against the main NSE site before hitting the archives
    host. Required or archives.nseindia.com 403s on a cold session."""
    s = requests.Session()
    s.headers.update(HEADERS)
    r = s.get("https://www.nseindia.com", timeout=15)
    r.raise_for_status()
    return s


def iter_weekdays(start, end):
    d = start
    one = timedelta(days=1)
    while d <= end:
        if d.weekday() < 5:  # Mon-Fri
            yield d
        d += one


def url_for(d):
    return f"{ARCHIVE_BASE}/sec_bhavdata_full_{d.strftime('%d%m%Y')}.csv"


def out_path_for(d):
    return OUT_DIR / f"sec_bhavdata_full_{d.strftime('%d%m%Y')}.csv"


def already_downloaded(path):
    return path.exists() and path.stat().st_size > MIN_FILE_BYTES


def extract_first_date1(content_bytes):
    """Parse the CSV header + first data row from raw response bytes and
    return the DATE1 field as a date, or None if the content can't be
    parsed this way (caller treats None as 'can't validate, save anyway').
    Kept dependency-light (no pandas) since this script otherwise only
    needs requests."""
    try:
        text = content_bytes.decode('utf-8', errors='replace')
    except Exception:
        return None
    lines = text.splitlines()
    if len(lines) < 2:
        return None
    header = [h.strip() for h in lines[0].split(',')]
    if 'DATE1' not in header:
        return None
    idx = header.index('DATE1')
    row = [c.strip() for c in lines[1].split(',')]
    if idx >= len(row):
        return None
    try:
        return datetime.strptime(row[idx], '%d-%b-%Y').date()
    except ValueError:
        return None


def fetch_one(session, d):
    """Attempt to download one day's file, up to MAX_ATTEMPTS tries with a
    RETRY_BACKOFF_SEC backoff on exceptions/5xx. Returns one of:
      ('ok', path)              -- downloaded and saved
      ('holiday', None)         -- HTTP 404, no retry (market holiday)
      ('holiday_stale', None)   -- HTTP 200 but content's own DATE1 doesn't
                                    match the requested date (NSE served a
                                    previous trading day's file for a
                                    holiday -- see module docstring). Not
                                    saved, no retry (retrying would just
                                    get the same stale content again).
      ('failed', None)          -- exhausted retries on exceptions/5xx/etc.
    """
    url = url_for(d)
    last_err = None
    for attempt in range(1, MAX_ATTEMPTS + 1):
        try:
            r = session.get(url, timeout=30)
        except requests.RequestException as e:
            last_err = f'{type(e).__name__}: {e}'
            if attempt < MAX_ATTEMPTS:
                time.sleep(RETRY_BACKOFF_SEC)
            continue
        if r.status_code == 404:
            return 'holiday', None
        if r.status_code >= 500:
            last_err = f'HTTP {r.status_code}'
            if attempt < MAX_ATTEMPTS:
                time.sleep(RETRY_BACKOFF_SEC)
            continue
        if r.status_code != 200:
            # 401/403/etc -- not a holiday, not transient-server; still
            # worth a retry since it may be a stale-cookie blip, but don't
            # loop forever on it.
            last_err = f'HTTP {r.status_code}'
            if attempt < MAX_ATTEMPTS:
                time.sleep(RETRY_BACKOFF_SEC)
            continue
        content = r.content
        if not content or len(content) < MIN_FILE_BYTES:
            last_err = f'suspiciously small body ({len(content)} bytes)'
            if attempt < MAX_ATTEMPTS:
                time.sleep(RETRY_BACKOFF_SEC)
            continue
        content_date = extract_first_date1(content)
        if content_date is not None and content_date != d:
            print(f'  [{d.isoformat()}] HTTP 200 but content dated {content_date.isoformat()} '
                  f'(stale holiday data, not saved)', flush=True)
            return 'holiday_stale', None
        out = out_path_for(d)
        out.write_bytes(content)
        return 'ok', out
    print(f'  [{d.isoformat()}] FAILED after {MAX_ATTEMPTS} attempts: {last_err}', flush=True)
    return 'failed', None


def download_range(start, end):
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    session = get_session()

    days = list(iter_weekdays(start, end))
    downloaded = skipped_existing = holidays = failed = 0
    consecutive_failures = 0
    failed_dates = []

    for i, d in enumerate(days, 1):
        path = out_path_for(d)
        if already_downloaded(path):
            skipped_existing += 1
            continue

        status, _ = fetch_one(session, d)
        time.sleep(REQUEST_SLEEP_SEC)

        if status == 'ok':
            downloaded += 1
            consecutive_failures = 0
        elif status in ('holiday', 'holiday_stale'):
            holidays += 1
            consecutive_failures = 0
        else:  # failed
            failed += 1
            failed_dates.append(d.isoformat())
            consecutive_failures += 1
            if consecutive_failures >= 2:
                print(f'  [{d.isoformat()}] 2 consecutive failures -- re-warming session', flush=True)
                try:
                    session = get_session()
                except Exception as e:
                    print(f'  re-warm failed: {type(e).__name__}: {e}', flush=True)
                consecutive_failures = 0

        if i % PROGRESS_EVERY == 0 or i == len(days):
            print(f'[{i}/{len(days)}] downloaded={downloaded} skipped_existing={skipped_existing} '
                  f'holiday_404={holidays} failed={failed}', flush=True)

    print('')
    print('=' * 78)
    print('FETCH SUMMARY')
    print('=' * 78)
    print(f'  Range requested   : {start.isoformat()} -> {end.isoformat()} (weekdays only)')
    print(f'  Weekday count     : {len(days)}')
    print(f'  Downloaded (new)  : {downloaded}')
    print(f'  Skipped (existing): {skipped_existing}')
    print(f'  Holiday (404 or stale-data): {holidays}')
    print(f'  Failed            : {failed}')
    if failed_dates:
        print(f'  Failed dates (re-run this script to retry -- resumable): {failed_dates}')
    print('=' * 78)
    return {'downloaded': downloaded, 'skipped_existing': skipped_existing,
            'holidays': holidays, 'failed': failed, 'failed_dates': failed_dates}


def parse_args():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('--start', type=str, default=None,
                    help='YYYY-MM-DD, default 2019-10-01 (earliest DELIV_QTY/DELIV_PER coverage)')
    p.add_argument('--end', type=str, default=None,
                    help='YYYY-MM-DD, default today')
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
