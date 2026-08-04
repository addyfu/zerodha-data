"""Offline unit tests for cas_logger.py.

Standalone: `python test_cas_logger.py` -- plain asserts, no pytest, no
network (mirrors test_options_collector.py's style, which mirrors
kite/live_monitor/test_charges.py). Every scenario runs against a throwaway
sqlite file in a temp dir; network calls are monkeypatched at the
module-function level (fetch_candles, load_enctoken) and 'today' is
monkeypatched via today_ist() so main() runs its real control flow with
fabricated data and a controlled simulated date -- no waiting for an actual
midnight to test the cross-day backfill.
"""
import sqlite3
import sys
import tempfile
from datetime import date
from pathlib import Path

import cas_logger as cl


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------
def _day_minute_candles(date_str, include_1529=True, include_auction=True):
    """A minimal but representative day: 09:15 open bar, an 11:00 midday
    bar, an optional 15:29 last-continuous-trading bar, and an optional
    15:32 closing-auction print with a different close (simulating the ~200pt
    CAS gap from the spec). Real days have ~375 continuous minute bars; the
    extraction logic only looks at specific timestamps plus the max-ts bar,
    so a sparse fixture exercises the same code paths without needing all
    375."""
    rows = [
        [f"{date_str}T09:15:00+0530", 24000.0, 24010.0, 23990.0, 24005.0, 10000],
        [f"{date_str}T11:00:00+0530", 24100.0, 24120.0, 24080.0, 24110.0, 5000],
    ]
    if include_1529:
        rows.append([f"{date_str}T15:29:00+0530", 24190.0, 24200.0, 24180.0, 24195.0, 8000])
    if include_auction:
        rows.append([f"{date_str}T15:32:00+0530", 24195.0, 24400.0, 24195.0, 24390.0, 20000])
    return rows


def _day_candle_row(date_str, close):
    return [f"{date_str}T00:00:00+0530", 24000.0, 24400.0, 23990.0, close, 500000]


def _make_fake_fetch_candles(minute_by_date: dict, daily_by_date: dict):
    """minute_by_date: {date_str: [candles]} for interval='minute'.
    daily_by_date: {date_str: candle-or-None} for interval='day'.
    Dispatches on from_dt.date() (both of cas_logger's fetch helpers always
    call fetch_candles with from_dt = start of the target day)."""
    def fake(session, token, from_dt, to_dt, interval, oi=False):
        assert token == cl.NIFTY_INDEX_TOKEN, token
        date_str = from_dt.date().isoformat()
        if interval == "minute":
            return list(minute_by_date.get(date_str, [])), 200
        if interval == "day":
            row = daily_by_date.get(date_str)
            return ([row] if row else []), 200
        raise AssertionError(f"unexpected interval {interval!r}")
    return fake


def _run_main(db_path, simulated_today: date, minute_by_date: dict, daily_by_date: dict,
              token="FAKE_TOKEN_FOR_TEST", dry_run=False):
    orig_load, orig_fetch, orig_today = cl.load_enctoken, cl.fetch_candles, cl.today_ist
    cl.load_enctoken = (lambda: token) if token is not None else (lambda: None)
    cl.fetch_candles = _make_fake_fetch_candles(minute_by_date, daily_by_date)
    cl.today_ist = lambda: simulated_today
    try:
        argv = ["--db", str(db_path)] + (["--dry-run"] if dry_run else [])
        rc = cl.main(argv)
    finally:
        cl.load_enctoken, cl.fetch_candles, cl.today_ist = orig_load, orig_fetch, orig_today
    return rc


def _fetch_row(db_path, date_str):
    if not Path(db_path).exists():
        return None
    conn = sqlite3.connect(db_path)
    row = conn.execute(
        "SELECT date, traded_1529, auction_close, auction_ts, official_close, open_next "
        "FROM cas_log WHERE date = ?", (date_str,)
    ).fetchone()
    conn.close()
    return row


def _row_count(db_path):
    if not Path(db_path).exists():
        return 0
    conn = sqlite3.connect(db_path)
    n = conn.execute("SELECT COUNT(*) FROM cas_log").fetchone()[0]
    conn.close()
    return n


# ---------------------------------------------------------------------------
# (a) normal day writes correct triple
# ---------------------------------------------------------------------------
def test_normal_day_writes_triple(tmp):
    db_path = Path(tmp) / "a.db"
    d1 = date(2026, 8, 3)
    minute = {"2026-08-03": _day_minute_candles("2026-08-03")}
    daily = {"2026-08-03": _day_candle_row("2026-08-03", 24390.0)}

    rc = _run_main(db_path, d1, minute, daily)
    assert rc == 0, rc

    row = _fetch_row(db_path, "2026-08-03")
    assert row is not None, "row must exist for 2026-08-03"
    d, traded_1529, auction_close, auction_ts, official_close, open_next = row
    assert traded_1529 == 24195.0, traded_1529
    assert auction_close == 24390.0, auction_close
    assert "15:32:00" in auction_ts, auction_ts
    assert official_close == 24390.0, official_close
    assert open_next is None, f"open_next must be NULL on the day itself, got {open_next}"
    return (f"date={d} traded_1529={traded_1529} auction_close={auction_close} "
            f"gap={auction_close - traded_1529:+.1f} official_close={official_close} open_next={open_next}")


# ---------------------------------------------------------------------------
# (b) re-run same day idempotent
# ---------------------------------------------------------------------------
def test_rerun_same_day_idempotent(tmp):
    db_path = Path(tmp) / "b.db"
    d1 = date(2026, 8, 3)
    minute = {"2026-08-03": _day_minute_candles("2026-08-03")}
    daily = {"2026-08-03": _day_candle_row("2026-08-03", 24390.0)}

    rc1 = _run_main(db_path, d1, minute, daily)
    row1 = _fetch_row(db_path, "2026-08-03")
    rc2 = _run_main(db_path, d1, minute, daily)
    row2 = _fetch_row(db_path, "2026-08-03")

    assert rc1 == 0 and rc2 == 0, (rc1, rc2)
    assert _row_count(db_path) == 1, f"re-run must not duplicate rows, got {_row_count(db_path)}"
    assert row1 == row2, f"re-run must produce identical row: {row1} vs {row2}"
    return f"1 row after 2 runs, unchanged: {row2}"


# ---------------------------------------------------------------------------
# (c) next-day run backfills open_next of prior row
# ---------------------------------------------------------------------------
def test_next_day_backfills_prior_open_next(tmp):
    db_path = Path(tmp) / "c.db"
    d1 = date(2026, 8, 3)
    d2 = date(2026, 8, 4)
    minute = {
        "2026-08-03": _day_minute_candles("2026-08-03"),
        "2026-08-04": _day_minute_candles("2026-08-04"),
    }
    daily = {
        "2026-08-03": _day_candle_row("2026-08-03", 24390.0),
        "2026-08-04": _day_candle_row("2026-08-04", 24350.0),
    }

    rc1 = _run_main(db_path, d1, minute, daily)
    row1_before = _fetch_row(db_path, "2026-08-03")
    assert rc1 == 0 and row1_before[5] is None, "day-1 row must have NULL open_next before day 2 runs"

    rc2 = _run_main(db_path, d2, minute, daily)
    assert rc2 == 0, rc2

    row1_after = _fetch_row(db_path, "2026-08-03")
    row2 = _fetch_row(db_path, "2026-08-04")
    assert row1_after is not None and row2 is not None
    # day 2's 09:15 open (see _day_minute_candles) is 24000.0
    assert row1_after[5] == 24000.0, f"day-1 open_next must be backfilled from day-2's 09:15 open, got {row1_after[5]}"
    assert row2[5] is None, "day-2's own row must have NULL open_next (only backfilled by day 3)"
    assert _row_count(db_path) == 2, _row_count(db_path)
    return f"day1.open_next backfilled to {row1_after[5]} after day-2 run; day2.open_next={row2[5]}"


# ---------------------------------------------------------------------------
# (d) holiday exits 0 with no row
# ---------------------------------------------------------------------------
def test_holiday_exits_0_no_row(tmp):
    db_path = Path(tmp) / "d.db"
    d1 = date(2026, 8, 15)  # e.g. Independence Day
    minute = {}  # no bars printed at all for this date
    daily = {}

    rc = _run_main(db_path, d1, minute, daily)
    assert rc == 0, rc
    assert _row_count(db_path) == 0, f"holiday must not write a row, got {_row_count(db_path)} rows"
    return f"exit={rc} rows={_row_count(db_path)}"


# ---------------------------------------------------------------------------
# (e) missing 15:29 bar with other bars present exits 1
# ---------------------------------------------------------------------------
def test_missing_1529_bar_exits_1(tmp):
    db_path = Path(tmp) / "e.db"
    d1 = date(2026, 8, 3)
    minute = {"2026-08-03": _day_minute_candles("2026-08-03", include_1529=False)}
    daily = {"2026-08-03": _day_candle_row("2026-08-03", 24390.0)}

    rc = _run_main(db_path, d1, minute, daily)
    assert rc == 1, f"missing 15:29 bar with other bars present must exit 1, got {rc}"
    assert _row_count(db_path) == 0, "no row should be written when the 15:29 tripwire fires"
    return f"exit={rc} rows={_row_count(db_path)}"


# ---------------------------------------------------------------------------
# (f) missing token exits 1
# ---------------------------------------------------------------------------
def test_missing_token_exits_1(tmp):
    db_path = Path(tmp) / "f.db"
    d1 = date(2026, 8, 3)
    rc = _run_main(db_path, d1, {}, {}, token=None)
    assert rc == 1, f"missing token must exit 1, got {rc}"
    assert not Path(db_path).exists() or _row_count(db_path) == 0, "no fetch/write should happen without a token"
    return f"exit={rc}"


# ---------------------------------------------------------------------------
# Bonus: dry-run makes no db writes at all (reviewer checklist item, CLI spec)
# ---------------------------------------------------------------------------
def test_dry_run_no_write(tmp):
    db_path = Path(tmp) / "g.db"
    d1 = date(2026, 8, 3)
    minute = {"2026-08-03": _day_minute_candles("2026-08-03")}
    daily = {"2026-08-03": _day_candle_row("2026-08-03", 24390.0)}

    rc = _run_main(db_path, d1, minute, daily, dry_run=True)
    assert rc == 0, rc
    assert not Path(db_path).exists(), "dry-run must not create/touch the db file"
    return f"exit={rc} db_exists={Path(db_path).exists()}"


# ---------------------------------------------------------------------------
# (h) Reviewer regression (2026-08-04): missed-session gap guard.
# If the logger skipped a session between the previous row and today, today's
# 09:15 open is NOT the previous row's true next-day open -- backfill must be
# BLOCKED (NULL beats wrong). A weekend-only gap has no missed session and
# must still backfill normally.
# ---------------------------------------------------------------------------
def test_gap_guard_blocks_backfill_after_missed_session(tmp):
    db_path = Path(tmp) / "h1.db"
    mon, thu = date(2026, 8, 3), date(2026, 8, 6)
    minute = {
        "2026-08-03": _day_minute_candles("2026-08-03"),
        "2026-08-06": _day_minute_candles("2026-08-06"),
    }
    # Market DID trade on Aug 4 (daily candle exists) but the logger never ran.
    daily = {
        "2026-08-03": _day_candle_row("2026-08-03", 24390.0),
        "2026-08-04": _day_candle_row("2026-08-04", 24300.0),
        "2026-08-06": _day_candle_row("2026-08-06", 24310.0),
    }
    assert _run_main(db_path, mon, minute, daily) == 0
    assert _run_main(db_path, thu, minute, daily) == 0
    mon_row = _fetch_row(db_path, "2026-08-03")
    assert mon_row[5] is None, (
        f"missed-session gap must leave open_next NULL, got {mon_row[5]}")

    # Weekend-only gap: Fri 08-07 -> Mon 08-10, no daily candle Sat/Sun.
    db2 = Path(tmp) / "h2.db"
    fri, mon2 = date(2026, 8, 7), date(2026, 8, 10)
    minute2 = {
        "2026-08-07": _day_minute_candles("2026-08-07"),
        "2026-08-10": _day_minute_candles("2026-08-10"),
    }
    daily2 = {
        "2026-08-07": _day_candle_row("2026-08-07", 24390.0),
        "2026-08-10": _day_candle_row("2026-08-10", 24310.0),
    }
    assert _run_main(db2, fri, minute2, daily2) == 0
    assert _run_main(db2, mon2, minute2, daily2) == 0
    fri_row = _fetch_row(db2, "2026-08-07")
    assert fri_row[5] == 24000.0, (
        f"weekend-only gap must still backfill (Mon 09:15 open), got {fri_row[5]}")
    return f"missed-session: open_next={mon_row[5]} (blocked); weekend: open_next={fri_row[5]} (backfilled)"


def main():
    tests = [
        test_normal_day_writes_triple,
        test_rerun_same_day_idempotent,
        test_next_day_backfills_prior_open_next,
        test_holiday_exits_0_no_row,
        test_missing_1529_bar_exits_1,
        test_missing_token_exits_1,
        test_dry_run_no_write,
        test_gap_guard_blocks_backfill_after_missed_session,
    ]
    passed = failed = 0
    print("=" * 78)
    for fn in tests:
        try:
            with tempfile.TemporaryDirectory() as tmp:
                detail = fn(tmp)
            print(f"PASS  {fn.__name__:42} {detail}")
            passed += 1
        except Exception as e:
            print(f"FAIL  {fn.__name__:42} {type(e).__name__}: {e}")
            failed += 1
    print("=" * 78)
    print(f"{passed}/{passed + failed} scenarios passed.")
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
