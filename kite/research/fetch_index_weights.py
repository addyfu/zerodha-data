"""Data acquisition: NSE (niftyindices.com) "Indices - Market Capitalisation
& Weightage" monthly report, Dec-2013 -> current month. Downloads the raw
ZIP for each month (per-index constituent weightage PDFs bundled together)
into data/index_weights/indices_data_YYYY-MM.zip. Contents are NOT parsed
here -- that's a follow-up task once the raw archive is complete.

Endpoint (verified LIVE 2026-07-28; scratchpad/recon2/niftyindices_test2.py
downloaded one sample -- indices_dataJan2020.zip, 5.3MB, confirmed to
contain 40 per-index PDFs -- but did not save/print the JSON response body,
so the exact response shape below was confirmed live before writing this
script):
    POST https://niftyindices.com/reports/historical-data/Index/
    Body (JSON): {"SelectedReportType": "4", "SelectedDate": "", "MonthYear": "Jan 2020"}
    Headers: Content-Type: application/json; charset=utf-8,
             Accept: application/json, text/javascript, */*; q=0.01,
             X-Requested-With: XMLHttpRequest,
             Referer: https://niftyindices.com/reports
    MonthYear format is "<3-letter month> <4-digit year>" e.g. "Jan 2020"
    (Python: date.strftime('%b %Y')). SelectedReportType "4" is confirmed
    (from the live reports page HTML select options, saved under
    scratchpad/recon2/niftyindices_reports.html) to be exactly
    "Indices - Market Capitalisation & Weightage".

Response shape -- confirmed with live requests for a normal month, a
month with no report, and out-of-range months:
    Success: {"success": true, "reportName": "...",
              "data": [{"DownloadLink": "/Indices_-_.../indices_dataJan2020.zip",
                         "FileName": "indices_dataJan2020.zip"}]}
    No data: {"success": false, "message": "No Data Found"}
DownloadLink is a RELATIVE path (must prepend https://niftyindices.com).
"data" was a single-item list in every month tested (Dec 2013, Nov 2013,
Jan 2020, Jun 2026) -- one bundled ZIP per month for this report type, not
one link per index. Confirmed live: Jan 2005 and Feb 2050 both return the
"No Data Found" shape (status 200, not a 404/error), and Dec 2013 (the
task's start month) DOES have data -- Nov 2013 also has data but the task
specifies Dec-2013 as the start so that's what's used here.

SURPRISE FOUND DURING LIVE VERIFICATION: no cookie handshake was needed at
all -- a POST from a completely cold requests.Session (no prior GET to
niftyindices.com, no cookies) succeeded immediately and returned the
correct shape. This matches the task's recon note ("No cookies needed per
recon"); confirmed live rather than just assumed, so this script skips the
handshake entirely (one fewer request per run).

Politeness / robustness:
  - requests.Session with a browser User-Agent throughout.
  - ~1 request/second between months (the POST and, on success, the ZIP
    GET together count as one "month" for pacing purposes).
  - Up to 2 retries (3 attempts total) with a 5s backoff on exceptions,
    non-200 status, or bad JSON, for both the POST and the ZIP download.
  - Resumable: a month's ZIP already on disk with size > 100KB is skipped
    without a network call. (No "always refetch current month" rule here,
    unlike the other two fetchers -- a month's report either doesn't
    exist yet ("No Data Found", which never writes a file, so it's
    naturally retried next run) or is a static published snapshot that
    won't change once it does exist.)
  - "No Data Found" months are counted and skipped, not treated as
    failures.
  - Progress printed per month; final summary counts
    downloaded / skipped-existing / no-data / failed.

Usage:
    python kite/research/fetch_index_weights.py
    python kite/research/fetch_index_weights.py --start 2024-01-01 --end 2024-02-29
"""
import argparse
import json
import sys
import time
from datetime import date
from pathlib import Path

import requests

ROOT = Path(__file__).resolve().parents[2]
OUT_DIR = ROOT / 'data' / 'index_weights'

POST_URL = "https://niftyindices.com/reports/historical-data/Index/"
NIFTYINDICES_BASE = "https://niftyindices.com"
UA = 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36'
POST_HEADERS = {
    "User-Agent": UA,
    "Content-Type": "application/json; charset=utf-8",
    "Accept": "application/json, text/javascript, */*; q=0.01",
    "X-Requested-With": "XMLHttpRequest",
    "Referer": "https://niftyindices.com/reports",
}
DOWNLOAD_HEADERS = {
    "User-Agent": UA,
    "Referer": "https://niftyindices.com/reports",
}
SELECTED_REPORT_TYPE = "4"  # "Indices - Market Capitalisation & Weightage"

DEFAULT_START = date(2013, 12, 1)
MIN_ZIP_BYTES = 100 * 1024  # real ZIPs seen were ~5.3MB; 100KB floor catches truncated saves
REQUEST_SLEEP_SEC = 1.0
MAX_ATTEMPTS = 3
RETRY_BACKOFF_SEC = 5.0


def iter_months(start, end):
    """Yield the first-of-month date for each month in [start, end]
    inclusive, based on year/month only."""
    y, m = start.year, start.month
    while (y, m) <= (end.year, end.month):
        yield date(y, m, 1)
        m += 1
        if m > 12:
            m = 1
            y += 1


def month_year_str(d):
    return d.strftime('%b %Y')  # e.g. "Jan 2020"


def out_path(d):
    return OUT_DIR / f"indices_data_{d.strftime('%Y-%m')}.zip"


def already_downloaded(path):
    return path.exists() and path.stat().st_size > MIN_ZIP_BYTES


def post_report(session, my_str):
    """POST for one month. Returns one of:
      ('ok', [ {DownloadLink, FileName}, ... ])
      ('no_data', None)
      ('failed', None)
    Retries on exceptions/non-200/bad-JSON."""
    body = json.dumps({"SelectedReportType": SELECTED_REPORT_TYPE, "SelectedDate": "", "MonthYear": my_str})
    last_err = None
    for attempt in range(1, MAX_ATTEMPTS + 1):
        try:
            r = session.post(POST_URL, headers=POST_HEADERS, data=body, timeout=30)
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
        try:
            payload = r.json()
        except ValueError as e:
            last_err = f'bad JSON: {e}'
            if attempt < MAX_ATTEMPTS:
                time.sleep(RETRY_BACKOFF_SEC)
            continue
        if not payload.get('success'):
            msg = payload.get('message', '')
            if 'no data' in msg.lower():
                return 'no_data', None
            last_err = f'success=false, message={msg!r}'
            if attempt < MAX_ATTEMPTS:
                time.sleep(RETRY_BACKOFF_SEC)
            continue
        items = payload.get('data') or []
        if not items:
            return 'no_data', None
        return 'ok', items
    print(f'    FAILED POST for {my_str} after {MAX_ATTEMPTS} attempts: {last_err}', flush=True)
    return 'failed', None


def download_zip(session, link, dest):
    """Download one ZIP with retries+backoff. Returns True on success."""
    url = link if link.startswith('http') else NIFTYINDICES_BASE + link
    last_err = None
    for attempt in range(1, MAX_ATTEMPTS + 1):
        try:
            r = session.get(url, headers=DOWNLOAD_HEADERS, timeout=60)
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
        content = r.content
        if len(content) < MIN_ZIP_BYTES:
            last_err = f'suspiciously small body ({len(content)} bytes)'
            if attempt < MAX_ATTEMPTS:
                time.sleep(RETRY_BACKOFF_SEC)
            continue
        dest.write_bytes(content)
        return True
    print(f'    FAILED download {url} after {MAX_ATTEMPTS} attempts: {last_err}', flush=True)
    return False


def download_range(start, end):
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    session = requests.Session()
    session.headers.update({"User-Agent": UA})

    months = list(iter_months(start, end))
    downloaded = skipped_existing = no_data = failed = 0
    failed_months = []

    for i, d in enumerate(months, 1):
        tag = d.strftime('%Y-%m')
        path = out_path(d)
        if already_downloaded(path):
            skipped_existing += 1
            continue

        my_str = month_year_str(d)
        status, items = post_report(session, my_str)
        time.sleep(REQUEST_SLEEP_SEC)

        if status == 'no_data':
            no_data += 1
            print(f'[{tag}] No Data Found', flush=True)
            continue
        if status == 'failed':
            failed += 1
            failed_months.append(tag)
            continue

        # status == 'ok': one (or, defensively, more) DownloadLink(s) for this month
        ok_all = True
        for idx, item in enumerate(items):
            link = item.get('DownloadLink')
            if not link:
                ok_all = False
                print(f'[{tag}] item missing DownloadLink: {item}', flush=True)
                continue
            dest = path if len(items) == 1 else OUT_DIR / f"indices_data_{tag}_{idx}.zip"
            ok = download_zip(session, link, dest)
            time.sleep(REQUEST_SLEEP_SEC)
            if not ok:
                ok_all = False

        if ok_all:
            downloaded += 1
            size_kb = path.stat().st_size // 1024 if path.exists() else 0
            print(f'[{tag}] downloaded ({size_kb} KB) -> {path.name}', flush=True)
        else:
            failed += 1
            failed_months.append(tag)

        if i % 20 == 0 or i == len(months):
            print(f'[{i}/{len(months)}] downloaded={downloaded} skipped={skipped_existing} '
                  f'no_data={no_data} failed={failed}', flush=True)

    print('')
    print('=' * 78)
    print('FETCH SUMMARY')
    print('=' * 78)
    print(f'  Range requested    : {start.strftime("%Y-%m")} -> {end.strftime("%Y-%m")} (monthly)')
    print(f'  Months requested   : {len(months)}')
    print(f'  Downloaded (new)   : {downloaded}')
    print(f'  Skipped (existing) : {skipped_existing}')
    print(f'  No Data Found      : {no_data}')
    print(f'  Failed             : {failed}')
    if failed_months:
        print(f'  Failed months (re-run this script to retry -- resumable): {failed_months}')
    print('=' * 78)
    return {'downloaded': downloaded, 'skipped_existing': skipped_existing,
            'no_data': no_data, 'failed': failed, 'failed_months': failed_months}


def parse_args():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('--start', type=str, default=None, help='YYYY-MM-DD, default 2013-12-01 (month part used)')
    p.add_argument('--end', type=str, default=None, help='YYYY-MM-DD, default today (month part used)')
    return p.parse_args()


def main():
    args = parse_args()
    start = date.fromisoformat(args.start) if args.start else DEFAULT_START
    end = date.fromisoformat(args.end) if args.end else date.today()
    if (start.year, start.month) > (end.year, end.month):
        sys.exit(f'--start {start} is after --end {end}')
    download_range(start, end)


if __name__ == '__main__':
    main()
