"""Phase 1 data acquisition (docs/superpowers/specs/2026-07-21-news-event-alpha-design.md).

Download ALL equity corporate announcements from NSE, 2020-01-01 -> today,
chunked by month, into data/announcements/ann_YYYY-MM.csv.

Recipe verified 2026-07-21 (see scratchpad/nse_final_recipe.py): warm cookies
with a GET against a real NSE page (https://www.nseindia.com/option-chain),
then GET https://www.nseindia.com/api/corporate-announcements with
index=equities, from_date/to_date as dd-mm-yyyy -> full JSON array for the
range, no pagination.

Usage:
    python kite/research/fetch_announcements.py

Resumable: re-running skips any month whose CSV already exists. Rate-limited
(1.5s between requests) and retries with a fresh session on 401/403/bad-JSON,
up to 3 attempts per month, then logs the failure and moves on.
"""
import calendar
import json
import sys
import time
from datetime import date
from pathlib import Path

import pandas as pd
import requests

ROOT = Path(__file__).resolve().parents[2]
OUT_DIR = ROOT / 'data' / 'announcements'
UNIVERSE_DIR = ROOT / 'data' / 'daily_universe'
LOG_FILE = ROOT / 'kite' / 'research' / 'fetch_announcements.log'

BASE = "https://www.nseindia.com/api"
HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; rv:109.0) Gecko/20100101 Firefox/118.0",
    "Accept": "*/*",
    "Accept-Language": "en-US,en;q=0.5",
    "Accept-Encoding": "gzip, deflate",
    "Referer": "https://www.nseindia.com/get-quotes/equity?symbol=HDFCBANK",
}

START_YEAR, START_MONTH = 2020, 1
COLUMNS = ['sort_date', 'an_dt', 'exchdisstime', 'symbol', 'sm_name', 'sm_isin',
           'desc', 'attchmntText', 'attchmntFile', 'seq_id']
SLEEP_SEC = 1.5
MAX_RETRIES = 3


def log(msg):
    """Print with flush and append to a log file, so progress survives a
    long-running/backgrounded run."""
    print(msg, flush=True)
    try:
        with open(LOG_FILE, 'a', encoding='utf-8') as fh:
            fh.write(msg + '\n')
    except OSError:
        pass


def get_session():
    """Warm up cookies against a real NSE page. Required before any /api/
    call or NSE returns 401/403."""
    s = requests.Session()
    s.headers.update(HEADERS)
    r = s.get("https://www.nseindia.com/option-chain", timeout=15)
    r.raise_for_status()
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


def iter_months(start_year=START_YEAR, start_month=START_MONTH, end=None):
    """Yield (year, month) tuples from the start through the given end date
    (default: today), inclusive of the current month."""
    end = end or date.today()
    y, m = start_year, start_month
    while (y, m) <= (end.year, end.month):
        yield y, m
        m += 1
        if m > 12:
            m = 1
            y += 1


def fetch_month(session, year, month):
    """Fetch one month of equity corporate announcements from NSE. Returns a
    DataFrame with COLUMNS, deduped on seq_id. Raises on any recognizable
    failure (bad auth, bad JSON, unexpected shape) so the caller can retry
    with a re-warmed session."""
    from_dt, to_dt = month_bounds(year, month)
    r = session.get(
        f"{BASE}/corporate-announcements",
        params={"index": "equities", "from_date": from_dt, "to_date": to_dt},
        timeout=60,
    )
    if r.status_code in (401, 403):
        raise PermissionError(f"HTTP {r.status_code}")
    r.raise_for_status()
    records = r.json()  # may raise json.JSONDecodeError
    if not isinstance(records, list):
        raise ValueError(f"unexpected payload type: {type(records).__name__}")

    df = pd.DataFrame(records)
    for col in COLUMNS:
        if col not in df.columns:
            df[col] = ''
    df = df[COLUMNS].copy()
    # keep seq_id as a plain string (avoid scientific notation / float coercion)
    df['seq_id'] = df['seq_id'].astype(str)
    df = df.drop_duplicates(subset='seq_id', keep='last')
    return df


def fetch_month_with_retries(session, year, month):
    """Wraps fetch_month with re-warm-on-failure retry logic.
    Returns (df_or_None, session) -- session may be replaced after a re-warm."""
    tag = f'{year:04d}-{month:02d}'
    last_err = None
    for attempt in range(1, MAX_RETRIES + 1):
        try:
            df = fetch_month(session, year, month)
            return df, session
        except (PermissionError, requests.RequestException, json.JSONDecodeError, ValueError) as e:
            last_err = e
            log(f'  [{tag}] attempt {attempt}/{MAX_RETRIES} failed: {type(e).__name__}: {e} -- re-warming session')
            time.sleep(2)
            try:
                session = get_session()
            except Exception as e2:
                log(f'  [{tag}] re-warm failed: {type(e2).__name__}: {e2}')
            time.sleep(SLEEP_SEC)
    log(f'[{tag}] FAILED after {MAX_RETRIES} attempts: {type(last_err).__name__}: {last_err}')
    return None, session


def download_all():
    """Run the full month-by-month download loop. Resumable: skips months
    whose output CSV already exists. Returns a list of month tags ('YYYY-MM')
    that failed after retries."""
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    session = get_session()
    months = list(iter_months())
    failed = []
    completed = 0
    total_records = 0
    for y, m in months:
        tag = f'{y:04d}-{m:02d}'
        out = OUT_DIR / f'ann_{tag}.csv'
        if out.exists():
            completed += 1
            try:
                total_records += sum(1 for _ in open(out, encoding='utf-8')) - 1
            except OSError:
                pass
            continue
        df, session = fetch_month_with_retries(session, y, m)
        if df is None:
            failed.append(tag)
            continue
        df.to_csv(out, index=False, encoding='utf-8')
        completed += 1
        total_records += len(df)
        log(f'[{tag}] {len(df)} records -> {out.name}')
        time.sleep(SLEEP_SEC)
    log(f'DOWNLOAD DONE: {completed}/{len(months)} months present, '
        f'{len(failed)} failed, ~{total_records} total records on disk. Failed: {failed}')
    return failed


def build_summary():
    """Read every ann_YYYY-MM.csv, compute Phase-1 quality-gate stats, write
    data/announcements/summary.json, print it, and return the dict."""
    files = sorted(OUT_DIR.glob('ann_*.csv'))
    if not files:
        log('No announcement files found; skipping summary.')
        return None

    frames = []
    for f in files:
        try:
            df = pd.read_csv(f, dtype={'seq_id': str}, encoding='utf-8', keep_default_na=False)
        except Exception as e:
            log(f'  WARN: failed to read {f.name}: {type(e).__name__}: {e}')
            continue
        frames.append(df)
    all_df = pd.concat(frames, ignore_index=True) if frames else pd.DataFrame(columns=COLUMNS)

    total = len(all_df)
    years = all_df['sort_date'].astype(str).str.slice(0, 4)
    records_per_year = {y: int(c) for y, c in years.value_counts().sort_index().items()}

    symbols = set(all_df['symbol'].dropna().astype(str)) - {''}
    distinct_symbols = len(symbols)

    top_categories = {k: int(v) for k, v in all_df['desc'].value_counts().head(30).items()}

    def strip_day_suffix(stem):
        return stem[:-4] if stem.endswith('_day') else stem

    universe_symbols = {strip_day_suffix(p.stem) for p in UNIVERSE_DIR.glob('*_day.csv')}
    joined_mask = all_df['symbol'].astype(str).isin(universe_symbols)
    join_count = int(joined_mask.sum())
    join_rate = (join_count / total) if total else 0.0

    summary = {
        'generated_at': pd.Timestamp.now().isoformat(),
        'months_present': len(files),
        'total_records': total,
        'records_per_year': records_per_year,
        'distinct_symbols': distinct_symbols,
        'top_30_categories': top_categories,
        'universe_join': {
            'universe_symbol_count': len(universe_symbols),
            'join_count': join_count,
            'join_rate': round(join_rate, 4),
        },
        'phase1_quality_gate': {
            'rule': '>=100000 usable AND >=60% joinable',
            'usable_ok': total >= 100_000,
            'joinable_ok': join_rate >= 0.60,
            'pass': (total >= 100_000) and (join_rate >= 0.60),
        },
    }
    with open(OUT_DIR / 'summary.json', 'w', encoding='utf-8') as fh:
        json.dump(summary, fh, indent=2, ensure_ascii=False)
    log(json.dumps(summary, indent=2, ensure_ascii=False))
    return summary


def main():
    failed = download_all()
    build_summary()
    if failed:
        log(f'Months failed after retries (re-run this script to retry them): {failed}')


if __name__ == '__main__':
    main()
