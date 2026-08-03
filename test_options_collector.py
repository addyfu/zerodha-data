"""Offline unit tests for options_collector.py.

Standalone: `python test_options_collector.py` -- plain asserts, no pytest,
no network (mirrors kite/live_monitor/test_charges.py's style). Every
scenario runs against a throwaway sqlite file in a temp dir; network calls
are monkeypatched at the module-function level (fetch_instrument_dump,
fetch_candles, load_enctoken) so main() runs its real control flow with
fabricated data.
"""
import sqlite3
import sys
import tempfile
from datetime import date, datetime, timedelta
from pathlib import Path

import pandas as pd

import options_collector as oc


# ---------------------------------------------------------------------------
# (a) two-nearest-expiry selection, incl. expiry-day boundary
# ---------------------------------------------------------------------------
def test_two_nearest_expiries_boundary():
    today = date(2026, 8, 6)
    expired = today - timedelta(days=7)     # dead, must roll off
    dying_today = today                      # expires TODAY, must still count
    next_week = today + timedelta(days=7)
    third = today + timedelta(days=14)       # nearest TWO only -- must be excluded

    rows = []
    for expiry in (expired, dying_today, next_week, third):
        for strike, itype in ((24000.0, "CE"), (24000.0, "PE")):
            rows.append({
                "instrument_token": hash((expiry, strike, itype)) % 10_000_000,
                "tradingsymbol": f"NIFTY{expiry.isoformat()}{itype}{int(strike)}",
                "expiry": expiry, "strike": strike, "instrument_type": itype,
            })
    opts = pd.DataFrame(rows)

    selected = oc.select_two_nearest_expiries(opts, today)
    assert selected == [dying_today, next_week], selected
    assert expired not in selected, "expired expiry must roll off"
    assert third not in selected, "only the two nearest expiries may be selected"
    return f"selected {selected} from {[expired, dying_today, next_week, third]}"


# ---------------------------------------------------------------------------
# (b) strike-window filter
# ---------------------------------------------------------------------------
def test_strike_window_filter():
    spot = 25000.0
    expiry = date(2026, 8, 6)
    strikes = [spot - 1500, spot - 1000, spot, spot + 1000, spot + 1500]
    rows = []
    for strike in strikes:
        for itype in ("CE", "PE"):
            rows.append({
                "instrument_token": hash((strike, itype)) % 10_000_000,
                "tradingsymbol": f"NIFTY{int(strike)}{itype}",
                "expiry": expiry, "strike": strike, "instrument_type": itype,
            })
    opts = pd.DataFrame(rows)

    sel = oc.select_contracts(opts, [expiry], spot)
    got_strikes = sorted(sel["strike"].unique())
    expected = sorted([spot - 1000, spot, spot + 1000])
    assert got_strikes == expected, got_strikes
    assert len(sel) == len(expected) * 2, "both CE and PE must survive the filter"
    assert set(sel["instrument_type"]) == {"CE", "PE"}
    return f"kept strikes {got_strikes} (dropped +/-1500 wings), {len(sel)} contracts (CE+PE)"


# ---------------------------------------------------------------------------
# (c) upsert idempotency
# ---------------------------------------------------------------------------
def test_upsert_idempotent(tmp):
    db_path = Path(tmp) / "idempotent.db"
    conn = oc.init_db(db_path)

    candles = [
        ["2026-08-03T09:15:00+0530", 100.0, 105.0, 98.0, 102.0, 500, 1200],
        ["2026-08-03T09:16:00+0530", 102.0, 104.0, 101.0, 103.0, 300, 1210],
        ["2026-08-03T09:17:00+0530", 103.0, 106.0, 102.0, 104.5, 250, 1220],
    ]
    added_first = oc.upsert_bars(conn, "NIFTY0806CE24000", "2026-08-06", 24000.0, "CE", candles)
    count_after_first = conn.execute(
        "SELECT COUNT(*) FROM option_bars WHERE tradingsymbol = ?", ("NIFTY0806CE24000",)
    ).fetchone()[0]

    added_second = oc.upsert_bars(conn, "NIFTY0806CE24000", "2026-08-06", 24000.0, "CE", candles)
    count_after_second = conn.execute(
        "SELECT COUNT(*) FROM option_bars WHERE tradingsymbol = ?", ("NIFTY0806CE24000",)
    ).fetchone()[0]
    conn.close()

    assert added_first == 3, added_first
    assert count_after_first == 3, count_after_first
    assert added_second == 0, f"re-inserting identical rows must add 0, got {added_second}"
    assert count_after_second == 3, "row count must not change on a repeat run"
    return f"first run +{added_first} rows (count={count_after_first}), second run +{added_second} (count={count_after_second})"


# ---------------------------------------------------------------------------
# (d) empty-chain tripwire (exit 1) and holiday (exit 0), via main()
# ---------------------------------------------------------------------------
def _synthetic_opts(today: date) -> pd.DataFrame:
    """4 contracts (2 strikes x CE/PE), one expiry, all within +/-1000 of the
    fake spot 25000, so select_contracts keeps all of them and none have any
    stored rows yet (fetch always attempted, never skipped as 'up to date')."""
    expiry = today + timedelta(days=3)
    rows = []
    for strike in (24500.0, 25500.0):
        for itype in ("CE", "PE"):
            rows.append({
                "instrument_token": hash((strike, itype)) % 10_000_000,
                "tradingsymbol": f"NIFTY{expiry.isoformat()}{itype}{int(strike)}",
                "expiry": expiry, "strike": strike, "instrument_type": itype,
            })
    return pd.DataFrame(rows)


def _make_fake_fetch_candles(spot_close: float, index_active: bool):
    """Simulates: spot daily-close fetch succeeds; every per-contract minute
    fetch returns zero rows (100% empty chain); the index minute-bar check
    returns bars iff index_active."""
    def fake(session, token, from_dt, to_dt, interval, oi=False):
        if token == oc.NIFTY_SPOT_TOKEN and interval == "day":
            return [["2026-08-03T00:00:00+0530", spot_close, spot_close, spot_close, spot_close, 0]], 200
        if token == oc.NIFTY_SPOT_TOKEN and interval == "minute":
            if index_active:
                return [["2026-08-03T09:15:00+0530", spot_close, spot_close, spot_close, spot_close, 1000, 0]], 200
            return [], 200
        return [], 200  # every option contract: empty
    return fake


def _run_main_with_fakes(tmp, index_active: bool):
    db_path = Path(tmp) / "trip.db"
    today = datetime.now().date()

    orig_load, orig_dump, orig_fetch = oc.load_enctoken, oc.fetch_instrument_dump, oc.fetch_candles
    oc.load_enctoken = lambda: "FAKE_TOKEN_FOR_TEST"
    oc.fetch_instrument_dump = lambda: _synthetic_opts(today)
    oc.fetch_candles = _make_fake_fetch_candles(spot_close=25000.0, index_active=index_active)
    try:
        rc = oc.main(["--db", str(db_path)])
    finally:
        oc.load_enctoken, oc.fetch_instrument_dump, oc.fetch_candles = orig_load, orig_dump, orig_fetch

    conn = sqlite3.connect(db_path)
    status, note = conn.execute(
        "SELECT status, note FROM collection_runs ORDER BY rowid DESC LIMIT 1"
    ).fetchone()
    conn.close()
    return rc, status, note


def test_empty_chain_tripwire_exits_1(tmp):
    rc, status, note = _run_main_with_fakes(tmp, index_active=True)
    assert rc == 1, f"empty-chain with a live index must exit 1, got {rc}"
    assert status == "failed", status
    assert "empty-chain" in note, note
    return f"exit={rc} status={status} note={note!r}"


def test_holiday_exits_0(tmp):
    rc, status, note = _run_main_with_fakes(tmp, index_active=False)
    assert rc == 0, f"empty chain with a silent index (holiday) must exit 0, got {rc}"
    assert status == "holiday", status
    assert note == "holiday - clean exit", note
    return f"exit={rc} status={status} note={note!r}"


def test_missing_enctoken_exits_1(tmp):
    """Bonus tripwire check (reviewer checklist item): no enctoken.txt and no
    ZERODHA_ENCTOKEN env -> CRITICAL, exit 1, no attempt at any fetch."""
    db_path = Path(tmp) / "notoken.db"
    orig_load = oc.load_enctoken
    oc.load_enctoken = lambda: None
    try:
        rc = oc.main(["--db", str(db_path)])
    finally:
        oc.load_enctoken = orig_load

    conn = sqlite3.connect(db_path)
    status, note = conn.execute(
        "SELECT status, note FROM collection_runs ORDER BY rowid DESC LIMIT 1"
    ).fetchone()
    conn.close()
    assert rc == 1, rc
    assert status == "failed", status
    assert "enctoken missing" in note, note
    return f"exit={rc} status={status} note={note!r}"


def test_same_day_rerun_not_tripwire(tmp):
    """Reviewer regression (2026-08-03): evening re-run after a successful
    collection. Every contract's stored data already reaches 15:29 today, so
    from_dt lands at >= 15:30 same-day. The re-run must skip those contracts
    as up-to-date (no new bars can exist after the close), NOT count them
    empty and NOT trip the empty-chain wire even though the index printed
    bars this morning."""
    db_path = Path(tmp) / "rerun.db"
    today = datetime.now().date()
    opts = _synthetic_opts(today)
    conn = oc.init_db(db_path)
    for _, row in opts.iterrows():
        candles = [[f"{today.isoformat()}T15:29:00+0530", 100.0, 101.0, 99.0, 100.5, 50, 500]]
        oc.upsert_bars(conn, row["tradingsymbol"], row["expiry"].isoformat(),
                       float(row["strike"]), row["instrument_type"], candles)
    conn.close()

    orig_load, orig_dump, orig_fetch = oc.load_enctoken, oc.fetch_instrument_dump, oc.fetch_candles
    oc.load_enctoken = lambda: "FAKE_TOKEN_FOR_TEST"
    oc.fetch_instrument_dump = lambda: opts
    oc.fetch_candles = _make_fake_fetch_candles(spot_close=25000.0, index_active=True)
    try:
        rc = oc.main(["--db", str(db_path)])
    finally:
        oc.load_enctoken, oc.fetch_instrument_dump, oc.fetch_candles = orig_load, orig_dump, orig_fetch

    conn = sqlite3.connect(db_path)
    status, empty, note = conn.execute(
        "SELECT status, contracts_empty, note FROM collection_runs ORDER BY rowid DESC LIMIT 1"
    ).fetchone()
    conn.close()
    assert rc == 0, f"same-day re-run must exit 0, got {rc} (note={note!r})"
    assert status == "ok", (status, note)
    assert empty == 0, f"up-to-date contracts must not count as empty, got {empty}"
    return f"exit={rc} status={status} contracts_empty={empty}"


def main():
    tests = [
        test_two_nearest_expiries_boundary,
        test_strike_window_filter,
        test_upsert_idempotent,
        test_empty_chain_tripwire_exits_1,
        test_holiday_exits_0,
        test_missing_enctoken_exits_1,
        test_same_day_rerun_not_tripwire,
    ]
    passed = failed = 0
    print("=" * 78)
    for fn in tests:
        needs_tmp = fn.__code__.co_argcount == 1
        try:
            if needs_tmp:
                with tempfile.TemporaryDirectory() as tmp:
                    detail = fn(tmp)
            else:
                detail = fn()
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
