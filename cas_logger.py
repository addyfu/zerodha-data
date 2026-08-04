"""
NIFTY Closing Auction Session (CAS) Daily Triple Logger
========================================================
Logs one row per trading day to data/cas_log.db: the last continuous-trading
price (15:29 close), the closing-auction print (last bar of the day), and
next morning's open (backfilled a day later). See docs/superpowers/specs/
2026-08-04-entries-exits-research-shortlist.md, candidate C, for the
hypothesis this feeds (auction-vs-traded gap partially reverts at next open)
and the ~60-session data requirement before any test has power.

SEBI's closing auction session went live 2026-08-03; day one printed an
official close ~200pts above the last traded level. This is purely
accumulative logging plumbing -- not a strategy, not a study -- per the
spec's "tiny logging + wait" scope.

Sibling of options_collector.py; conventions (token loading, chart API
fetch shape, tripwire discipline, logging, CLI, exit codes) are mirrored
deliberately so the two units read the same way in the systemd journal.
Never imports zerodha_auto_login or performs any login/TOTP flow -- same
one-session rule as options_collector.py / report_positions.py. A dead
token is a hard failure, not a prompt to re-authenticate.
"""

import argparse
import io
import logging
import os
import sqlite3
import sys
from datetime import date, datetime, timedelta
from datetime import time as dtime
from pathlib import Path

import pandas as pd
import requests

# Fix Windows console encoding (harmless no-op on the Oracle Linux deploy target).
if sys.platform == 'win32':
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8', errors='replace')
    sys.stderr = io.TextIOWrapper(sys.stderr.buffer, encoding='utf-8', errors='replace')

BASE_DIR = Path(__file__).parent
DATA_DIR = BASE_DIR / "data"
DB_PATH = DATA_DIR / "cas_log.db"          # NEW file -- never touches options_data.db or anything else
LOG_PATH = DATA_DIR / "cas_logger.log"
ENCTOKEN_PATH = BASE_DIR / "enctoken.txt"

DATA_DIR.mkdir(exist_ok=True)

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s',
    handlers=[
        logging.FileHandler(LOG_PATH),
        logging.StreamHandler(sys.stdout),
    ],
)
logger = logging.getLogger(__name__)

CHART_URL = "https://kite.zerodha.com/oms/instruments/historical"
NIFTY_INDEX_TOKEN = 256265
CHUNK_SPAN_DAYS = 60  # kept for parity with options_collector.fetch_candles; never triggers for a single day's span


class TokenExpiredError(Exception):
    """Raised when the chart API returns HTTP 403 -- enctoken.txt is dead."""


# ---------------------------------------------------------------------------
# Token loading -- verbatim from options_collector.py
# ---------------------------------------------------------------------------
def load_enctoken() -> str | None:
    """ZERODHA_ENCTOKEN env var takes priority, then repo-root enctoken.txt.
    Never attempts a login of its own -- see module docstring."""
    token = os.environ.get("ZERODHA_ENCTOKEN")
    if token:
        return token.strip()
    if ENCTOKEN_PATH.exists():
        text = ENCTOKEN_PATH.read_text().strip()
        return text or None
    return None


def build_session(enctoken: str) -> requests.Session:
    session = requests.Session()
    session.headers.update({
        "Authorization": f"enctoken {enctoken}",
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
        "Accept": "application/json",
        "X-Kite-Version": "3.0.0",
    })
    return session


# ---------------------------------------------------------------------------
# Chart API (authenticated) -- same endpoint/format as options_collector.fetch_candles
# ---------------------------------------------------------------------------
def fetch_candles(session: requests.Session, token: int, from_dt: datetime, to_dt: datetime,
                   interval: str, oi: bool = False) -> tuple[list, int | None]:
    """Fetches raw candles for [from_dt, to_dt], chunking any span over
    CHUNK_SPAN_DAYS (never needed here -- every call this module makes spans
    a single day -- kept only so this function is a byte-for-byte match of
    options_collector.fetch_candles). Returns (candles, last_http_status);
    candles is [] and status is None if from_dt > to_dt (nothing to fetch)."""
    if from_dt > to_dt:
        return [], None

    all_candles: list = []
    last_status = None
    span_start = from_dt
    while span_start <= to_dt:
        span_end = min(span_start + timedelta(days=CHUNK_SPAN_DAYS), to_dt)
        url = f"{CHART_URL}/{token}/{interval}"
        params = {
            "from": span_start.strftime("%Y-%m-%d %H:%M:%S"),
            "to": span_end.strftime("%Y-%m-%d %H:%M:%S"),
        }
        if oi:
            params["oi"] = 1

        response = session.get(url, params=params, timeout=30)
        last_status = response.status_code
        if response.status_code == 403:
            raise TokenExpiredError(f"HTTP 403 fetching token {token}")
        if response.status_code == 200:
            data = response.json()
            if data.get("status") == "success":
                all_candles.extend(data.get("data", {}).get("candles", []))

        span_start = span_end + timedelta(seconds=1)

    return all_candles, last_status


def fetch_index_minute_bars_today(session: requests.Session, today: date) -> list:
    """All of today's NIFTY index minute bars, 00:00 to now. One call covers
    holiday detection, the 15:29 traded level, the 09:15 open, and the
    closing-auction print (whichever bar has the latest ts) -- no need for
    options_collector's separate index_printed_bars_today probe since we need
    the actual bar contents here, not just a presence boolean."""
    start = datetime.combine(today, dtime(0, 0, 0))
    now = datetime.now()
    candles, _ = fetch_candles(session, NIFTY_INDEX_TOKEN, start, now, interval="minute", oi=False)
    return candles


def fetch_index_day_candle_today(session: requests.Session, today: date) -> list | None:
    """Interval='day' candle for TODAY specifically (unlike
    options_collector.fetch_spot_close, which wants the most recent daily
    close of the last few days to center a strike window and is happy with
    yesterday's on a quiet morning). Here we need this exact date's close as
    a cross-check against the minute-bar triple, so any candle not dated
    today is discarded rather than falling back to it."""
    start = datetime.combine(today, dtime(0, 0, 0))
    now = datetime.now()
    candles, _ = fetch_candles(session, NIFTY_INDEX_TOKEN, start, now, interval="day", oi=False)
    for c in candles:
        if parse_candle_ts(c[0]).date() == today:
            return c
    return None


# ---------------------------------------------------------------------------
# Bar extraction
# ---------------------------------------------------------------------------
def parse_candle_ts(raw_ts) -> datetime:
    """Kite candle timestamps arrive as ISO8601 with a fixed +0530 offset (NSE
    has no DST). Normalize through pandas then strip the offset, mirroring
    options_collector.parse_stored_ts's naive-IST wall-clock convention used
    throughout this codebase (system clock assumed Asia/Kolkata)."""
    ts_str = str(pd.to_datetime(raw_ts))
    return datetime.strptime(ts_str[:19], "%Y-%m-%d %H:%M:%S")


def find_bar_at_time(candles: list, target_time: dtime):
    """Returns the single candle whose IST wall-clock time matches
    target_time exactly, or None. Candles are Kite's raw [ts, o, h, l, c, v]
    rows (oi absent -- this module always fetches with oi=False)."""
    for c in candles:
        if parse_candle_ts(c[0]).time() == target_time:
            return c
    return None


def last_bar_of_day(candles: list):
    """The candle with the latest ts. Once CAS bars appear after 15:30 this
    is the auction/settlement print; on a day the feed simply stops at 15:29
    (or a pre-CAS-format day) this collapses to the same bar as
    traded_1529 -- per spec that equality is expected data, not a failure,
    so no comparison/validation is done here on purpose."""
    return max(candles, key=lambda c: parse_candle_ts(c[0]))


# ---------------------------------------------------------------------------
# Storage
# ---------------------------------------------------------------------------
def init_db(db_path) -> sqlite3.Connection:
    db_path = Path(db_path)
    db_path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(str(db_path))
    conn.execute("""
        CREATE TABLE IF NOT EXISTS cas_log (
            date TEXT PRIMARY KEY,
            traded_1529 REAL,
            auction_close REAL,
            auction_ts TEXT,
            official_close REAL,
            open_next REAL
        )
    """)
    conn.commit()
    return conn


def upsert_today_row(conn: sqlite3.Connection, date_str: str, traded_1529: float,
                      auction_close: float, auction_ts: str, official_close) -> None:
    """INSERT OR REPLACE keyed on date. Always writes open_next = NULL for
    today's own row -- open_next for a given date is only ever known the
    NEXT trading day (see backfill_previous_day), so it can never already be
    set at the moment we insert today's row. A repeat run the same evening
    therefore just rewrites NULL over NULL here; it cannot clobber a real
    backfilled value."""
    conn.execute(
        "INSERT OR REPLACE INTO cas_log "
        "(date, traded_1529, auction_close, auction_ts, official_close, open_next) "
        "VALUES (?, ?, ?, ?, ?, NULL)",
        (date_str, traded_1529, auction_close, auction_ts, official_close),
    )
    conn.commit()


def sessions_traded_between(session: requests.Session, after: date, before: date) -> bool:
    """True if the NIFTY index printed any DAILY candle strictly between two
    dates (exclusive both ends). Guards the backfill against a missed-run
    gap: if the logger skipped a session, the 'previous' row's true next-day
    open belongs to the missed session, not to today -- writing today's open
    there would be silently WRONG data, which this codebase treats as worse
    than missing data. Adjacent dates and weekend-only gaps need no fetch /
    return False cheaply."""
    if (before - after).days <= 1:
        return False
    start = datetime.combine(after + timedelta(days=1), dtime(0, 0, 0))
    end = datetime.combine(before - timedelta(days=1), dtime(23, 59, 59))
    candles, _ = fetch_candles(session, NIFTY_INDEX_TOKEN, start, end, interval="day", oi=False)
    return len(candles) > 0


def backfill_previous_day(conn: sqlite3.Connection, today_str: str, open_next_value: float,
                           session: requests.Session) -> str | None:
    """Finds the most recent existing row with date < today and sets its
    open_next to today's 09:15 open -- but ONLY if no trading session
    occurred between that row's date and today (see sessions_traded_between;
    a missed session means the prior row's open_next is unknowable now and
    stays NULL, loudly). Returns the backfilled date string, or None if no
    prior row exists or the gap check blocked the write. Idempotent:
    re-running the same evening re-writes the same value onto the same row
    -- no duplication, no double-backfill."""
    row = conn.execute(
        "SELECT date FROM cas_log WHERE date < ? ORDER BY date DESC LIMIT 1",
        (today_str,),
    ).fetchone()
    if not row:
        return None
    prev_date = row[0]
    if sessions_traded_between(session, date.fromisoformat(prev_date), date.fromisoformat(today_str)):
        logger.warning(
            f"session(s) traded between {prev_date} and {today_str} but were never logged "
            f"-- leaving {prev_date}.open_next NULL (unknown beats wrong)")
        return None
    conn.execute("UPDATE cas_log SET open_next = ? WHERE date = ?", (open_next_value, prev_date))
    conn.commit()
    return prev_date


# ---------------------------------------------------------------------------
# CLI / main
# ---------------------------------------------------------------------------
def today_ist() -> date:
    """Wall-clock date, naive-IST convention (system clock assumed
    Asia/Kolkata -- see parse_candle_ts). Broken out from an inline
    datetime.now().date() so tests can monkeypatch 'today' and exercise the
    cross-day backfill without waiting for an actual midnight."""
    return datetime.now().date()


def build_arg_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="NIFTY closing-auction-session (CAS) daily triple logger "
                     "(traded_1529 / auction_close / open_next)")
    parser.add_argument("--dry-run", action="store_true",
                         help="Fetch + compute today's triple, print, no db writes")
    parser.add_argument("--db", type=Path, default=DB_PATH, help="Override DB path")
    return parser


def main(argv=None) -> int:
    args = build_arg_parser().parse_args(argv)

    today = today_ist()
    today_str = today.isoformat()
    status, note = "unknown", ""
    traded_1529 = auction_close = official_close = None
    auction_ts = None
    backfilled_date = None

    try:
        enctoken = load_enctoken()
        if not enctoken:
            status = "failed"
            note = "enctoken missing (no enctoken.txt, no ZERODHA_ENCTOKEN env)"
            logger.critical(note)
            return 1

        session = build_session(enctoken)

        try:
            candles = fetch_index_minute_bars_today(session, today)
        except TokenExpiredError as e:
            status = "failed"
            note = f"enctoken dead (403 fetching minute bars): {e}"
            logger.critical(note)
            return 1

        if not candles:
            status, note = "holiday", "no minute bars today -- holiday/weekend, clean exit"
            logger.info(note)
            return 0

        bar_1529 = find_bar_at_time(candles, dtime(15, 29))
        if bar_1529 is None:
            status = "failed"
            note = (f"15:29 bar missing but {len(candles)} other minute bars exist today "
                     "-- data hole")
            logger.critical(note)
            return 1
        traded_1529 = float(bar_1529[4])

        last_bar = last_bar_of_day(candles)
        auction_close = float(last_bar[4])
        auction_ts = str(pd.to_datetime(last_bar[0]))

        try:
            day_candle = fetch_index_day_candle_today(session, today)
        except TokenExpiredError as e:
            status = "failed"
            note = f"enctoken dead (403 fetching day candle): {e}"
            logger.critical(note)
            return 1

        if day_candle is None:
            official_close = None
            logger.warning("no day-interval candle matched today -- "
                            "official_close cross-check unavailable this run")
        else:
            official_close = float(day_candle[4])

        bar_0915 = find_bar_at_time(candles, dtime(9, 15))
        open_next_for_prev = float(bar_0915[1]) if bar_0915 is not None else None
        if bar_0915 is None:
            logger.warning("09:15 bar missing -- cannot backfill previous day's open_next this run")

        gap = auction_close - traded_1529

        if args.dry_run:
            status, note = "dry_run", "dry run: no db write"
            print(f"date={today_str} traded_1529={traded_1529} auction_close={auction_close} "
                  f"auction_ts={auction_ts} official_close={official_close} gap={gap:+.2f}")
            return 0

        conn = init_db(args.db)
        upsert_today_row(conn, today_str, traded_1529, auction_close, auction_ts, official_close)
        if open_next_for_prev is not None:
            backfilled_date = backfill_previous_day(conn, today_str, open_next_for_prev, session)
        conn.close()

        status = "ok"
        note = f"row written for {today_str}"
        if backfilled_date:
            note += f", backfilled open_next for {backfilled_date}"
        return 0

    except Exception as e:
        status = "failed"
        note = f"unhandled exception: {e}"
        logger.critical(note, exc_info=True)
        return 1

    finally:
        if auction_close is not None and traded_1529 is not None:
            gap_str = f"{(auction_close - traded_1529):+.2f}"
        else:
            gap_str = "n/a"
        summary = (f"date={today_str} status={status} traded_1529={traded_1529} "
                   f"auction_close={auction_close} gap={gap_str} "
                   f"backfilled={'y' if backfilled_date else 'n'} note={note}")
        logger.info(summary)


if __name__ == "__main__":
    sys.exit(main())
