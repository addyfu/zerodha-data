"""Acceptance tests for dashboard.py's tiered price ladder (2026-08-05 fix).

Bug: the dashboard priced open positions ONLY from zerodha_data.db's minute
closes, which on the Oracle deploy target is a nightly-synced copy -- up to
a day stale during market hours -- yet the "Current" column showed it with
no indication it wasn't live. This suite covers the fix: latest_prices()
now ladders tier-1 (the `latest_prices` table the live monitor writes into
BOTH book DBs every scan cycle) over tier-2 (the old zerodha_data.db
fallback), and every price rendered carries a visible staleness tag when
it's not a fresh (<=10min old) tier-1 read.

Standalone: `python kite/live_monitor/test_dashboard_prices.py` -- plain
asserts, no pytest, no network. Every scenario runs against throwaway
sqlite files in a temp dir; the real books/zerodha_data.db are never
touched. Style matches test_charges.py.
"""
import sqlite3
import sys
import tempfile
from datetime import datetime, timedelta
from pathlib import Path

_CODE_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(_CODE_ROOT))

from kite.live_monitor import dashboard

# Remember the module's real (env-derived) DB paths/BOOKS so every test can
# point them at its own throwaway temp DBs without ever touching the real
# ones, and so nothing leaks between tests (each test calls _use_dbs() with
# its own tmp dir before doing anything else).
_ORIG_MAIN_DB = dashboard.MAIN_DB
_ORIG_INCUBATOR_DB = dashboard.INCUBATOR_DB
_ORIG_ZERODHA_DB = dashboard.ZERODHA_DB
_ORIG_BOOKS = dashboard.BOOKS


def _use_dbs(main_db, incubator_db, zerodha_db):
    """Point dashboard.py's module-level DB paths (and the derived BOOKS
    list _tier1_prices()/read_book() actually iterate) at test fixtures."""
    dashboard.MAIN_DB = Path(main_db)
    dashboard.INCUBATOR_DB = Path(incubator_db)
    dashboard.ZERODHA_DB = Path(zerodha_db)
    dashboard.BOOKS = [("main", dashboard.MAIN_DB), ("incubator", dashboard.INCUBATOR_DB)]


def _restore_dbs():
    dashboard.MAIN_DB = _ORIG_MAIN_DB
    dashboard.INCUBATOR_DB = _ORIG_INCUBATOR_DB
    dashboard.ZERODHA_DB = _ORIG_ZERODHA_DB
    dashboard.BOOKS = _ORIG_BOOKS


# ---------------------------------------------------------------------------
# fixture builders -- minimal schemas matching paper_trader.py's
# _init_database() (positions/account/latest_prices) and the zerodha
# collector's ohlcv table, just enough for dashboard.py's queries to work.
# ---------------------------------------------------------------------------
def _make_book_db(path, positions=(), account=None, latest_prices=None,
                   create_latest_prices_table=True):
    conn = sqlite3.connect(str(path))
    conn.execute("""
        CREATE TABLE positions (
            id INTEGER PRIMARY KEY,
            symbol TEXT NOT NULL,
            direction TEXT NOT NULL,
            entry_price REAL NOT NULL,
            entry_time TEXT NOT NULL,
            quantity INTEGER NOT NULL,
            stop_loss REAL,
            take_profit REAL,
            strategy TEXT,
            exit_price REAL,
            exit_time TEXT,
            exit_reason TEXT,
            pnl REAL DEFAULT 0,
            pnl_pct REAL DEFAULT 0,
            status TEXT DEFAULT 'open',
            trailing_stop REAL,
            highest_price REAL,
            lowest_price REAL,
            trade_mode TEXT DEFAULT 'INTRADAY'
        )
    """)
    conn.execute("""
        CREATE TABLE account (
            id INTEGER PRIMARY KEY,
            capital REAL NOT NULL,
            initial_capital REAL NOT NULL,
            trade_counter INTEGER DEFAULT 0,
            last_updated TEXT
        )
    """)
    if create_latest_prices_table:
        conn.execute("""
            CREATE TABLE latest_prices (
                symbol TEXT PRIMARY KEY,
                price REAL NOT NULL,
                updated_at TEXT NOT NULL
            )
        """)
    for p in positions:
        conn.execute(
            "INSERT INTO positions (symbol, direction, entry_price, entry_time, quantity, "
            "stop_loss, take_profit, strategy, status, trade_mode) VALUES (?,?,?,?,?,?,?,?,?,?)",
            (p['symbol'], p['direction'], p['entry_price'], p['entry_time'], p['quantity'],
             p.get('stop_loss'), p.get('take_profit'), p.get('strategy', 'test'),
             p.get('status', 'open'), p.get('trade_mode', 'INTRADAY')),
        )
    if account:
        conn.execute(
            "INSERT INTO account (capital, initial_capital, last_updated) VALUES (?,?,?)",
            (account.get('capital', 100000), account.get('initial_capital', 100000),
             account.get('last_updated')),
        )
    if latest_prices and create_latest_prices_table:
        conn.executemany(
            "INSERT INTO latest_prices (symbol, price, updated_at) VALUES (?,?,?)",
            latest_prices,
        )
    conn.commit()
    conn.close()


def _make_zerodha_db(path, bars=()):
    """bars: iterable of (symbol, datetime_str, close)."""
    conn = sqlite3.connect(str(path))
    conn.execute("""
        CREATE TABLE ohlcv (
            symbol TEXT NOT NULL,
            datetime TEXT NOT NULL,
            interval TEXT NOT NULL,
            open REAL, high REAL, low REAL, close REAL, volume INTEGER
        )
    """)
    conn.executemany(
        "INSERT INTO ohlcv (symbol, datetime, interval, close) VALUES (?,?,'minute',?)",
        [(sym, ts, close) for sym, ts, close in bars],
    )
    conn.commit()
    conn.close()


# ---------------------------------------------------------------------------
# (a) tier-1 wins over tier-2 when both exist and tier-1 is fresh
# ---------------------------------------------------------------------------
def test_tier1_wins_when_fresh(tmp):
    now = datetime(2026, 8, 5, 10, 0, 0)
    fresh_ts = (now - timedelta(minutes=2)).isoformat()
    main_db, inc_db, zdb = Path(tmp) / 'main.db', Path(tmp) / 'inc.db', Path(tmp) / 'zerodha.db'
    _make_book_db(main_db, latest_prices=[('TCS', 100.5, fresh_ts)])
    _make_book_db(inc_db)
    _make_zerodha_db(zdb, bars=[('TCS', '2026-08-04 15:29:00+05:30', 90.0)])
    _use_dbs(main_db, inc_db, zdb)

    prices = dashboard.latest_prices(['TCS'], now=now)
    assert prices['TCS']['price'] == 100.5, f"tier1 price should win, got {prices['TCS']}"
    assert prices['TCS']['source'] == 'tier1', prices['TCS']
    assert prices['TCS']['stale'] is False, prices['TCS']
    return f"tier1 100.5 (fresh) beat tier2's 90.0"


# ---------------------------------------------------------------------------
# (b) symbol missing from tier 1 falls back to tier 2 and gets the stale tag
# ---------------------------------------------------------------------------
def test_missing_from_tier1_falls_back_to_tier2_stale(tmp):
    now = datetime(2026, 8, 5, 10, 0, 0)
    main_db, inc_db, zdb = Path(tmp) / 'main.db', Path(tmp) / 'inc.db', Path(tmp) / 'zerodha.db'
    # TCS has tier-1 data; INFY does not -- only tier-2 has it.
    _make_book_db(main_db, latest_prices=[('TCS', 100.5, (now - timedelta(minutes=2)).isoformat())])
    _make_book_db(inc_db)
    old_ts = '2026-08-04 15:29:00+05:30'
    _make_zerodha_db(zdb, bars=[('INFY', old_ts, 1500.25)])
    _use_dbs(main_db, inc_db, zdb)

    prices = dashboard.latest_prices(['TCS', 'INFY'], now=now)
    assert 'INFY' in prices, 'INFY should have fallen through to tier 2, not been dropped'
    assert prices['INFY']['source'] == 'tier2', prices['INFY']
    assert prices['INFY']['price'] == 1500.25, prices['INFY']
    assert prices['INFY']['ts'] == old_ts, prices['INFY']
    assert prices['INFY']['stale'] is True, 'a day-old zerodha_data.db bar must be tagged stale'
    # sanity: TCS untouched by the fallback path
    assert prices['TCS']['source'] == 'tier1'
    return f"INFY fell to tier2 @ {old_ts}, tagged stale=True"


# ---------------------------------------------------------------------------
# (c) missing latest_prices TABLE entirely -> clean fallback, no exception
# ---------------------------------------------------------------------------
def test_missing_latest_prices_table_fails_soft(tmp):
    now = datetime(2026, 8, 5, 10, 0, 0)
    main_db, inc_db, zdb = Path(tmp) / 'main.db', Path(tmp) / 'inc.db', Path(tmp) / 'zerodha.db'
    # Simulate an older DB snapshot that predates the latest_prices table.
    _make_book_db(main_db, create_latest_prices_table=False)
    _make_book_db(inc_db, create_latest_prices_table=False)
    _make_zerodha_db(zdb, bars=[('RELIANCE', '2026-08-04 15:29:00+05:30', 2500.0)])
    _use_dbs(main_db, inc_db, zdb)

    prices = dashboard.latest_prices(['RELIANCE'], now=now)  # must not raise
    assert prices['RELIANCE']['source'] == 'tier2', prices['RELIANCE']
    assert prices['RELIANCE']['price'] == 2500.0, prices['RELIANCE']
    assert prices['RELIANCE']['stale'] is True

    # Also exercise read_book() end-to-end with the table missing, since
    # that's the actual call path the dashboard uses.
    book = dashboard.read_book(main_db, '2026-08-05', now)
    assert book['available'] is True, 'a missing latest_prices TABLE must not make the DB "unavailable"'
    return "missing latest_prices TABLE -> clean tier2 fallback, no exception, book still available"


# ---------------------------------------------------------------------------
# (d) both-books case picks the newer timestamp
# ---------------------------------------------------------------------------
def test_newer_of_both_books_wins(tmp):
    now = datetime(2026, 8, 5, 10, 0, 0)
    main_db, inc_db, zdb = Path(tmp) / 'main.db', Path(tmp) / 'inc.db', Path(tmp) / 'zerodha.db'
    older_ts = (now - timedelta(minutes=5)).isoformat()
    newer_ts = (now - timedelta(minutes=1)).isoformat()
    _make_book_db(main_db, latest_prices=[('HDFCBANK', 1600.0, older_ts)])
    _make_book_db(inc_db, latest_prices=[('HDFCBANK', 1610.0, newer_ts)])
    _make_zerodha_db(zdb)
    _use_dbs(main_db, inc_db, zdb)

    prices = dashboard.latest_prices(['HDFCBANK'], now=now)
    assert prices['HDFCBANK']['price'] == 1610.0, (
        f"expected the incubator book's newer price (1610.0) to win, got {prices['HDFCBANK']}")
    assert prices['HDFCBANK']['ts'] == newer_ts

    # Flip which book has the newer row -- main should win this time. Fresh
    # filenames (not a rewrite of main_db/inc_db) since sqlite3 can't
    # CREATE TABLE into a file that already has one.
    main_db2, inc_db2 = Path(tmp) / 'main2.db', Path(tmp) / 'inc2.db'
    _make_book_db(main_db2, latest_prices=[('HDFCBANK', 1650.0, newer_ts)])
    _make_book_db(inc_db2, latest_prices=[('HDFCBANK', 1600.0, older_ts)])
    _use_dbs(main_db2, inc_db2, zdb)
    prices2 = dashboard.latest_prices(['HDFCBANK'], now=now)
    assert prices2['HDFCBANK']['price'] == 1650.0, prices2['HDFCBANK']
    return "newer timestamp wins regardless of which book (main/incubator) has it"


# ---------------------------------------------------------------------------
# (e) staleness threshold boundary at exactly 10 minutes
# ---------------------------------------------------------------------------
def test_staleness_boundary_at_exactly_10_minutes(tmp):
    now = datetime(2026, 8, 5, 10, 0, 0)
    main_db, inc_db, zdb = Path(tmp) / 'main.db', Path(tmp) / 'inc.db', Path(tmp) / 'zerodha.db'
    exactly_10 = (now - timedelta(minutes=10)).isoformat()
    just_over_10 = (now - timedelta(minutes=10, seconds=1)).isoformat()
    just_under_10 = (now - timedelta(minutes=9, seconds=59)).isoformat()
    _make_book_db(main_db, latest_prices=[
        ('ATEN', 10.0, exactly_10),
        ('BOVER', 20.0, just_over_10),
        ('CUNDER', 30.0, just_under_10),
    ])
    _make_book_db(inc_db)
    _make_zerodha_db(zdb)
    _use_dbs(main_db, inc_db, zdb)

    prices = dashboard.latest_prices(['ATEN', 'BOVER', 'CUNDER'], now=now)
    assert prices['ATEN']['stale'] is False, 'exactly 10:00 old must still count as "within 10 minutes"'
    assert prices['BOVER']['stale'] is True, '10:01 old must be stale'
    assert prices['CUNDER']['stale'] is False, '9:59 old must be fresh'

    # Also confirm _is_fresh directly at the boundary (belt and suspenders --
    # this is the actual function driving the ladder's staleness bit).
    assert dashboard._is_fresh(now - timedelta(minutes=10), now) is True
    assert dashboard._is_fresh(now - timedelta(minutes=10, seconds=1), now) is False
    return "boundary holds: exactly 10min=fresh, 10min+1s=stale"


# ---------------------------------------------------------------------------
# extra: full-page render (the actual DashboardHandler.do_GET path) shows a
# fresh price with no tag, a stale-tagged fallback price, and both new
# per-book header stamps -- this is the "render one page offline" evidence
# the task asked to verify, kept in the same suite for one-command coverage.
# ---------------------------------------------------------------------------
def test_render_page_offline_shows_ladder_and_header_stamps(tmp):
    main_db, inc_db, zdb = Path(tmp) / 'main.db', Path(tmp) / 'inc.db', Path(tmp) / 'zerodha.db'
    fresh_ts = datetime.now().isoformat()          # fresh as of whenever this test actually runs
    stale_ts = '2020-01-01 09:15:00+05:30'         # unambiguously >10min old under any wall clock
    _make_book_db(
        main_db,
        positions=[
            dict(symbol='TCS', direction='BUY', entry_price=90.0,
                 entry_time='2026-08-05 09:16:00', quantity=10, status='open'),
            dict(symbol='WIPRO', direction='BUY', entry_price=400.0,
                 entry_time='2026-08-05 09:17:00', quantity=5, status='open'),
        ],
        account=dict(capital=100000, initial_capital=100000, last_updated='2026-08-05 09:17:00'),
        latest_prices=[('TCS', 101.25, fresh_ts)],   # tier-1, fresh -> plain price
    )
    _make_book_db(inc_db)
    _make_zerodha_db(zdb, bars=[('WIPRO', stale_ts, 405.5)])  # tier-2 fallback -> stale tag
    _use_dbs(main_db, inc_db, zdb)

    html_out = dashboard.render_page()

    assert '101.25' in html_out, 'fresh tier-1 price (TCS) missing from rendered page'
    assert 'stale-tag' in html_out, 'no staleness tag class rendered anywhere on the page'
    assert '405.5' in html_out, 'stale fallback price (WIPRO) missing from rendered page'
    assert 'stale-DB' in html_out, 'tier-2 fallback price should be tagged "stale-DB"'
    assert 'prices as of' in html_out, 'new "prices as of" header stamp missing'
    assert 'last trade' in html_out, 'new "last trade" header stamp missing'
    assert 'updated 2026-08-05 09:17' not in html_out, (
        'old misleading single "updated <last_updated>" stamp should be gone')
    return 'render_page(): fresh price bare, stale price tagged, both header stamps present'


def test_newest_wins_fossil_tier1_loses_to_newer_tier2(tmp):
    """Reviewer regression (2026-08-05, HINDALCO incident): a tier-1 row not
    refreshed for days (symbol untracked between positions) must LOSE to a
    newer tier-2 close. And a fresh tier-1 row must still beat tier 2."""
    now = datetime(2026, 8, 5, 10, 53, 0)
    # fossil tier-1: six days old; tier-2: one day old -- newer than the fossil
    m1, i1, z1 = Path(tmp) / 'm1.db', Path(tmp) / 'i1.db', Path(tmp) / 'z1.db'
    _make_book_db(m1, latest_prices=[('HINDALCO', 962.8, '2026-07-30T10:13:45')])
    _make_book_db(i1)
    _make_zerodha_db(z1, [('HINDALCO', '2026-08-04 12:23:00+05:30', 1003.0)])
    _use_dbs(m1, i1, z1)
    try:
        out = dashboard.latest_prices(['HINDALCO'], now=now)
    finally:
        _restore_dbs()
    p = out['HINDALCO']
    assert p['source'] == 'tier2', f"newer tier-2 must win over fossil tier-1, got {p}"
    assert p['price'] == 1003.0, p
    assert p['stale'] is True, "a day-old tier-2 price is still stale -- tag stays"

    # control: fresh tier-1 (2 min old) beats the same tier-2
    m2, i2 = Path(tmp) / 'm2.db', Path(tmp) / 'i2.db'
    _make_book_db(m2, latest_prices=[('HINDALCO', 999.5, '2026-08-05T10:51:00')])
    _make_book_db(i2)
    _use_dbs(m2, i2, z1)
    try:
        out2 = dashboard.latest_prices(['HINDALCO'], now=now)
    finally:
        _restore_dbs()
    p2 = out2['HINDALCO']
    assert p2['source'] == 'tier1' and p2['price'] == 999.5 and p2['stale'] is False, p2
    return f"fossil tier1 lost to newer tier2 ({p['price']}); fresh tier1 still wins ({p2['price']})"


def main():
    tests = [
        test_tier1_wins_when_fresh,
        test_missing_from_tier1_falls_back_to_tier2_stale,
        test_missing_latest_prices_table_fails_soft,
        test_newer_of_both_books_wins,
        test_staleness_boundary_at_exactly_10_minutes,
        test_render_page_offline_shows_ladder_and_header_stamps,
        test_newest_wins_fossil_tier1_loses_to_newer_tier2,
    ]
    passed = failed = 0
    print('=' * 78)
    try:
        for fn in tests:
            with tempfile.TemporaryDirectory() as tmp:
                try:
                    detail = fn(tmp)
                    print(f'PASS  {fn.__name__:48} {detail}')
                    passed += 1
                except Exception as e:
                    print(f'FAIL  {fn.__name__:48} {type(e).__name__}: {e}')
                    failed += 1
    finally:
        _restore_dbs()
    print('=' * 78)
    print(f'{passed}/{passed + failed} scenarios passed.')
    return 1 if failed else 0


if __name__ == '__main__':
    sys.exit(main())
