"""
NIFTY Options Minute-Bar Forward Collector
===========================================
Collects 1-minute OHLCV+OI bars for the two nearest-expiry NIFTY option
chains and stores them in data/options_data.db. Designed to run daily
(Mon-Fri, after market close) via systemd timer on Oracle.

This is plumbing, not a study -- see docs/superpowers/specs/
2026-08-03-options-minute-collector-design.md for the frozen mechanical
rules. Do not change expiry/strike/tripwire logic without a decision-log
entry there; a later change needs to be knowable so a backtest can split
the archive at the rule change.

Never imports zerodha_auto_login or performs any login/TOTP flow -- same
one-session rule as report_positions.py. A dead token is a hard failure,
not a prompt to re-authenticate.
"""

import argparse
import io
import logging
import os
import sqlite3
import sys
import time
from datetime import datetime, timedelta
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
DB_PATH = DATA_DIR / "options_data.db"
LOG_PATH = DATA_DIR / "options_collector.log"
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
INSTRUMENTS_URL = "https://api.kite.trade/instruments"
NIFTY_SPOT_TOKEN = 256265
NIFTY_NAME = "NIFTY"
NFO_OPT_SEGMENT = "NFO-OPT"

STRIKE_WINDOW = 1000.0
SPOT_MIN, SPOT_MAX = 10000.0, 60000.0
EMPTY_CHAIN_THRESHOLD = 0.30
FETCH_PACING_SECONDS = 0.3
NEW_CONTRACT_LOOKBACK_DAYS = 45
CHUNK_SPAN_DAYS = 60


class TokenExpiredError(Exception):
    """Raised when the chart API returns HTTP 403 -- enctoken.txt is dead."""


class SpotFetchError(Exception):
    """Raised when the NIFTY index daily close cannot be determined."""


# ---------------------------------------------------------------------------
# Token loading
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
# Instrument dump (public, unauthenticated)
# ---------------------------------------------------------------------------
def fetch_instrument_dump() -> pd.DataFrame:
    """Downloads api.kite.trade/instruments (public CSV, no auth) and returns
    the NFO-OPT / name==NIFTY rows only."""
    response = requests.get(INSTRUMENTS_URL, timeout=30)
    response.raise_for_status()
    return parse_instrument_csv(response.text)


def parse_instrument_csv(text: str) -> pd.DataFrame:
    """CSV columns (per Kite instrument dump): instrument_token,exchange_token,
    tradingsymbol,name,last_price,expiry,strike,tick_size,lot_size,
    instrument_type,segment,exchange. Read by header name rather than
    position so a column-order change upstream doesn't silently mis-map."""
    df = pd.read_csv(io.StringIO(text))
    opts = df[(df["segment"] == NFO_OPT_SEGMENT) & (df["name"] == NIFTY_NAME)].copy()
    opts["expiry"] = pd.to_datetime(opts["expiry"]).dt.date
    opts["strike"] = opts["strike"].astype(float)
    opts["instrument_token"] = opts["instrument_token"].astype(int)
    return opts[["instrument_token", "tradingsymbol", "expiry", "strike", "instrument_type"]].reset_index(drop=True)


def select_two_nearest_expiries(opts: pd.DataFrame, today) -> list:
    """The two nearest NIFTY option expiries with expiry >= today. An expiry
    dying TODAY still counts (bars exist until 15:30); an expiry that died
    yesterday rolls off. No hardcoded weekday -- NSE has moved expiry days
    before, discovery from the instrument dump is the rule."""
    upcoming = sorted({e for e in opts["expiry"].unique() if e >= today})
    return upcoming[:2]


def select_contracts(opts: pd.DataFrame, expiries: list, spot: float,
                      window: float = STRIKE_WINDOW) -> pd.DataFrame:
    """All listed strikes within +/-window of spot, both CE and PE, both
    selected expiries. Strike list comes straight from the instrument dump --
    no hardcoded 50/100-point step assumption."""
    lo, hi = spot - window, spot + window
    sel = opts[opts["expiry"].isin(expiries) & (opts["strike"] >= lo) & (opts["strike"] <= hi)]
    return sel.sort_values(["expiry", "strike", "instrument_type"]).reset_index(drop=True)


# ---------------------------------------------------------------------------
# Chart API (authenticated)
# ---------------------------------------------------------------------------
def fetch_candles(session: requests.Session, token: int, from_dt: datetime, to_dt: datetime,
                   interval: str, oi: bool = False) -> tuple[list, int | None]:
    """Fetches raw candles for [from_dt, to_dt], chunking any span over
    CHUNK_SPAN_DAYS (never needed for a NIFTY weekly option's ~week-long life;
    kept for the 45-day new-contract backfill and as a safety net per spec).
    Returns (candles, last_http_status); candles is [] and status is None if
    from_dt > to_dt (nothing to fetch)."""
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


def fetch_spot_close(session: requests.Session) -> float:
    """Latest NIFTY 50 index daily close (token 256265), last ~5 days of
    daily candles, take the last one. No fallback source -- a wrong center
    would bias the archive silently, so the run fails loudly instead."""
    to_dt = datetime.now()
    from_dt = to_dt - timedelta(days=5)
    candles, status = fetch_candles(session, NIFTY_SPOT_TOKEN, from_dt, to_dt, interval="day", oi=False)
    if not candles:
        raise SpotFetchError(f"no daily candles returned for NIFTY index (last HTTP status={status})")
    return float(candles[-1][4])


def index_printed_bars_today(session: requests.Session, today) -> bool:
    """One extra API call for the holiday tripwire: did the NIFTY index print
    any minute bars today? Silent index -> holiday/weekend. Printing index
    with a mostly-empty option chain -> a real feed break."""
    start = datetime.combine(today, dtime(0, 0, 0))
    now = datetime.now()
    candles, _ = fetch_candles(session, NIFTY_SPOT_TOKEN, start, now, interval="minute", oi=False)
    return len(candles) > 0


# ---------------------------------------------------------------------------
# Storage
# ---------------------------------------------------------------------------
def init_db(db_path) -> sqlite3.Connection:
    db_path = Path(db_path)
    db_path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(str(db_path))
    conn.execute("""
        CREATE TABLE IF NOT EXISTS option_bars (
            tradingsymbol TEXT,
            expiry TEXT,
            strike REAL,
            opt_type TEXT,
            ts TEXT,
            open REAL,
            high REAL,
            low REAL,
            close REAL,
            volume INTEGER,
            oi INTEGER,
            PRIMARY KEY(tradingsymbol, ts)
        )
    """)
    conn.execute("""
        CREATE TABLE IF NOT EXISTS collection_runs (
            run_date TEXT,
            started_at TEXT,
            finished_at TEXT,
            expiries TEXT,
            contracts INTEGER,
            contracts_empty INTEGER,
            rows_added INTEGER,
            status TEXT,
            note TEXT
        )
    """)
    conn.commit()
    return conn


def get_last_ts(conn: sqlite3.Connection, tradingsymbol: str) -> str | None:
    row = conn.execute(
        "SELECT MAX(ts) FROM option_bars WHERE tradingsymbol = ?", (tradingsymbol,)
    ).fetchone()
    return row[0] if row and row[0] else None


def parse_stored_ts(ts_str: str) -> datetime:
    """Stored ts mirrors daily_collector's str(pandas.Timestamp) output, e.g.
    '2026-08-03 09:16:00+05:30' (space separator, fixed +05:30 offset -- NSE
    has no DST). Strip the offset and parse the naive IST wall-clock part,
    matching the rest of live_monitor's naive-IST convention (system clock
    assumed Asia/Kolkata; see report_positions.py / sync_release_db.py)."""
    return datetime.strptime(ts_str[:19], "%Y-%m-%d %H:%M:%S")


def upsert_bars(conn: sqlite3.Connection, tradingsymbol: str, expiry: str, strike: float,
                 opt_type: str, candles: list) -> int:
    """INSERT OR REPLACE all candles for one contract. Returns the net row
    count change for this tradingsymbol (not affected-row count, which INSERT
    OR REPLACE reports as 1 per statement regardless of whether the row was
    new) -- this is what makes idempotency ("run twice -> 0 net new rows")
    directly measurable."""
    if not candles:
        return 0

    before = conn.execute(
        "SELECT COUNT(*) FROM option_bars WHERE tradingsymbol = ?", (tradingsymbol,)
    ).fetchone()[0]

    rows = []
    for candle in candles:
        ts_str = str(pd.to_datetime(candle[0]))
        o, h, l, c, v = candle[1], candle[2], candle[3], candle[4], candle[5]
        oi = candle[6] if len(candle) > 6 else 0
        rows.append((tradingsymbol, expiry, strike, opt_type, ts_str, o, h, l, c, int(v), int(oi)))

    conn.executemany(
        "INSERT OR REPLACE INTO option_bars "
        "(tradingsymbol, expiry, strike, opt_type, ts, open, high, low, close, volume, oi) "
        "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
        rows,
    )
    conn.commit()

    after = conn.execute(
        "SELECT COUNT(*) FROM option_bars WHERE tradingsymbol = ?", (tradingsymbol,)
    ).fetchone()[0]
    return after - before


def record_run(db_path, run_date: str, started_at: datetime, finished_at: datetime,
                expiries: str, contracts: int, contracts_empty: int, rows_added: int,
                status: str, note: str) -> None:
    conn = init_db(db_path)
    conn.execute(
        "INSERT INTO collection_runs "
        "(run_date, started_at, finished_at, expiries, contracts, contracts_empty, rows_added, status, note) "
        "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
        (run_date, started_at.isoformat(), finished_at.isoformat(), expiries,
         contracts, contracts_empty, rows_added, status, note),
    )
    conn.commit()
    conn.close()


# ---------------------------------------------------------------------------
# CLI / main
# ---------------------------------------------------------------------------
def build_arg_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="NIFTY options minute-bar forward collector")
    parser.add_argument("--dry-run", action="store_true",
                         help="Discover + select contracts, print selection, no fetch/no DB writes")
    parser.add_argument("--max-contracts", type=int, default=None,
                         help="Cap the number of contracts fetched (smoke tests)")
    parser.add_argument("--db", type=Path, default=DB_PATH, help="Override DB path")
    return parser


def main(argv=None) -> int:
    args = build_arg_parser().parse_args(argv)

    started_at = datetime.now()
    run_date = started_at.strftime("%Y-%m-%d")
    status, note, expiries_str = "unknown", "", ""
    contracts_selected = contracts_empty = rows_added = 0

    try:
        enctoken = load_enctoken()
        if not enctoken:
            status = "failed"
            note = "enctoken missing (no enctoken.txt, no ZERODHA_ENCTOKEN env)"
            logger.critical(note)
            return 1

        session = build_session(enctoken)

        logger.info("Downloading instrument dump...")
        opts = fetch_instrument_dump()
        today = started_at.date()
        expiries = select_two_nearest_expiries(opts, today)
        if not expiries:
            status = "failed"
            note = "no NIFTY NFO-OPT expiries >= today found in instrument dump"
            logger.critical(note)
            return 1
        expiries_str = ",".join(e.isoformat() for e in expiries)
        logger.info(f"Selected expiries: {expiries_str}")

        try:
            spot = fetch_spot_close(session)
        except TokenExpiredError as e:
            status = "failed"
            note = f"enctoken dead (403 on first fetch): {e}"
            logger.critical(note)
            return 1
        except SpotFetchError as e:
            status = "failed"
            note = f"spot fetch failed: {e}"
            logger.critical(note)
            return 1

        if not (SPOT_MIN <= spot <= SPOT_MAX):
            status = "failed"
            note = f"spot {spot} outside sane bounds [{SPOT_MIN}, {SPOT_MAX}]"
            logger.critical(note)
            return 1
        logger.info(f"NIFTY spot close: {spot}")

        contracts_df = select_contracts(opts, expiries, spot)
        if args.max_contracts:
            contracts_df = contracts_df.head(args.max_contracts)
        contracts_selected = len(contracts_df)
        logger.info(f"Selected {contracts_selected} contracts within +/-{STRIKE_WINDOW:.0f} of spot")

        if args.dry_run:
            status, note = "dry_run", "dry run: no fetch, no db writes"
            for _, row in contracts_df.iterrows():
                print(f"{row['tradingsymbol']:25s} expiry={row['expiry']} strike={row['strike']:.1f} type={row['instrument_type']}")
            return 0

        conn = init_db(args.db)
        now = datetime.now()

        for _, row in contracts_df.iterrows():
            tradingsymbol = row["tradingsymbol"]
            last_ts = get_last_ts(conn, tradingsymbol)
            if last_ts is None:
                from_dt = now - timedelta(days=NEW_CONTRACT_LOOKBACK_DAYS)
            else:
                from_dt = parse_stored_ts(last_ts) + timedelta(minutes=1)

            if from_dt > now:
                continue  # already up to date this run; not a fetch failure
            if from_dt.date() == now.date() and from_dt.time() >= dtime(15, 30):
                # Post-close same-day re-run: the previous run already captured
                # everything through the 15:30 close and no new bars can print
                # until the next session. Fetching would return 0 candles and
                # falsely count toward the empty-chain tripwire.
                continue

            try:
                candles, _ = fetch_candles(session, int(row["instrument_token"]), from_dt, now,
                                            interval="minute", oi=True)
            except TokenExpiredError as e:
                logger.error(f"{tradingsymbol}: token expired mid-run ({e}) -- counting as empty")
                contracts_empty += 1
                time.sleep(FETCH_PACING_SECONDS)
                continue
            except Exception as e:
                logger.error(f"{tradingsymbol}: fetch error ({e}) -- counting as empty")
                contracts_empty += 1
                time.sleep(FETCH_PACING_SECONDS)
                continue

            if not candles:
                contracts_empty += 1
            else:
                added = upsert_bars(conn, tradingsymbol, row["expiry"].isoformat(),
                                     float(row["strike"]), row["instrument_type"], candles)
                rows_added += added

            time.sleep(FETCH_PACING_SECONDS)

        conn.close()

        empty_ratio = (contracts_empty / contracts_selected) if contracts_selected else 0.0
        if empty_ratio > EMPTY_CHAIN_THRESHOLD:
            logger.warning(f"{contracts_empty}/{contracts_selected} contracts empty "
                            f"({empty_ratio:.0%}) -- checking index for holiday")
            try:
                index_active = index_printed_bars_today(session, today)
            except TokenExpiredError as e:
                status = "failed"
                note = f"token died during holiday check: {e}"
                logger.critical(note)
                return 1
            except Exception as e:
                status = "failed"
                note = f"holiday check failed, cannot confirm silently: {e}"
                logger.critical(note)
                return 1

            if index_active:
                status = "failed"
                note = (f"empty-chain tripwire: {contracts_empty}/{contracts_selected} contracts "
                        f"empty but NIFTY index printed bars today")
                logger.critical(note)
                return 1

            status, note = "holiday", "holiday - clean exit"
            logger.info(note)
            return 0

        status = "ok"
        note = f"{rows_added} rows added across {contracts_selected} contracts"
        logger.info(note)
        return 0

    except Exception as e:
        status = "failed"
        note = f"unhandled exception: {e}"
        logger.critical(note, exc_info=True)
        return 1

    finally:
        finished_at = datetime.now()
        summary = (f"run_date={run_date} status={status} expiries={expiries_str} "
                   f"contracts={contracts_selected} contracts_empty={contracts_empty} "
                   f"rows_added={rows_added} note={note}")
        logger.info(summary)
        if not args.dry_run:
            try:
                record_run(args.db, run_date, started_at, finished_at, expiries_str,
                           contracts_selected, contracts_empty, rows_added, status, note)
            except Exception as e:
                logger.error(f"failed to write collection_runs row: {e}")


if __name__ == "__main__":
    sys.exit(main())
