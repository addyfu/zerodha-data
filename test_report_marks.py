"""Offline unit tests for kite/live_monitor/report_positions.py's chart-fallback
mark tier (added 2026-08-04, Zerodha's /oms/quote now 400s unconditionally for
enctoken sessions).

Standalone: `python test_report_marks.py` -- plain asserts, no pytest, no
network (mirrors test_options_collector.py's style). ZerodhaDataFetcher is
monkeypatched at the report_positions module-attribute level (`rp.ZerodhaDataFetcher`)
with a fake class whose __init__ does no network I/O at all -- unlike the real
class, it never touches _load_instruments()/requests.get, so no instrument-list
download happens either. ZERODHA_ENCTOKEN is forced to a fake value BEFORE the
module import so report_positions' no-token short-circuit never fires here,
regardless of what's in the real .env or environment.
"""
import os
import sys
from datetime import datetime
from pathlib import Path

os.environ['ZERODHA_ENCTOKEN'] = 'FAKE_TOKEN_FOR_TEST'  # must precede the import below

import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parent))
import kite.live_monitor.report_positions as rp


# ---------------------------------------------------------------------------
# fake fetcher plumbing
# ---------------------------------------------------------------------------
def _bar_df(closes, start='2026-08-04 11:00'):
    """Small minute-bar DataFrame shaped like get_historical_data()'s real
    return: DatetimeIndex, a 'close' column. Last row is the 'last close'."""
    idx = pd.date_range(start, periods=len(closes), freq='1min')
    return pd.DataFrame({'close': closes}, index=idx)


def _make_fake_fetcher(quote_result, historical_fn, call_counter=None):
    """Build a fake ZerodhaDataFetcher class.
      quote_result:  dict returned by get_quote() (any symbols, any shape).
      historical_fn: callable(symbol) -> DataFrame/None; may raise to
                     simulate a per-symbol chart-fetch failure.
      call_counter:  optional dict; 'historical' key incremented on every
                     get_historical_data() call, so a test can assert the
                     chart path was/wasn't touched at all.
    __init__ intentionally does nothing with the token -- no network, no
    instrument-list download, unlike the real ZerodhaDataFetcher."""
    class FakeFetcher:
        def __init__(self, token):
            self.token = token

        def get_quote(self, symbols):
            return dict(quote_result)

        def get_historical_data(self, symbol, interval="day", days=60):
            if call_counter is not None:
                call_counter['historical'] = call_counter.get('historical', 0) + 1
            return historical_fn(symbol)

    return FakeFetcher


# ---------------------------------------------------------------------------
# (a) chart fallback basic: get_quote() -> {}, chart works for every symbol
# ---------------------------------------------------------------------------
def test_chart_fallback_basic():
    last_close = {'NIFTY': 24950.5, 'BANKNIFTY': 51234.0}

    def hist(symbol):
        return _bar_df([last_close[symbol] - 10, last_close[symbol]])

    orig = rp.ZerodhaDataFetcher
    rp.ZerodhaDataFetcher = _make_fake_fetcher({}, hist)
    try:
        quotes, status = rp.fetch_live_quotes(['NIFTY', 'BANKNIFTY'], offline=False)
    finally:
        rp.ZerodhaDataFetcher = orig

    assert status == 'chart', status
    assert quotes['NIFTY']['last_price'] == last_close['NIFTY'], quotes['NIFTY']
    assert quotes['BANKNIFTY']['last_price'] == last_close['BANKNIFTY'], quotes['BANKNIFTY']
    assert quotes['NIFTY']['source'] == 'chart', quotes['NIFTY']
    return f"status={status} NIFTY={quotes['NIFTY']['last_price']} BANKNIFTY={quotes['BANKNIFTY']['last_price']}"


# ---------------------------------------------------------------------------
# (b) per-symbol isolation: A raises, B still gets marked, status stays 'chart'
# ---------------------------------------------------------------------------
def test_chart_fallback_partial_failure_isolated():
    def hist(symbol):
        if symbol == 'A':
            raise RuntimeError("simulated chart-fetch failure for A")
        return _bar_df([19.0, 20.5])

    orig = rp.ZerodhaDataFetcher
    rp.ZerodhaDataFetcher = _make_fake_fetcher({}, hist)
    try:
        quotes, status = rp.fetch_live_quotes(['A', 'B'], offline=False)
    finally:
        rp.ZerodhaDataFetcher = orig

    assert status == 'chart', status
    assert 'A' not in quotes, f"A must be skipped, got {quotes.get('A')}"
    assert quotes['B']['last_price'] == 20.5, quotes['B']
    return f"status={status} A_present={'A' in quotes} B={quotes['B']['last_price']}"


# ---------------------------------------------------------------------------
# (c) every symbol empty (None or zero-row DataFrame) -> 'quote-failed'
# ---------------------------------------------------------------------------
def test_chart_fallback_all_empty_falls_to_quote_failed():
    def hist(symbol):
        return None if symbol == 'A' else pd.DataFrame(columns=['close'])

    orig = rp.ZerodhaDataFetcher
    rp.ZerodhaDataFetcher = _make_fake_fetcher({}, hist)
    try:
        quotes, status = rp.fetch_live_quotes(['A', 'B'], offline=False)
    finally:
        rp.ZerodhaDataFetcher = orig

    assert status == 'quote-failed', status
    assert quotes == {}, quotes
    return f"status={status} quotes={quotes}"


# ---------------------------------------------------------------------------
# (d) live quote succeeds -> chart path (get_historical_data) never called
# ---------------------------------------------------------------------------
def test_live_quote_success_skips_chart_path():
    call_counter = {}

    def hist(symbol):
        return _bar_df([1.0])  # would satisfy the chart path if it were ever called

    quote_result = {'NIFTY': {'last_price': 25000.0, 'timestamp': datetime.now()}}
    orig = rp.ZerodhaDataFetcher
    rp.ZerodhaDataFetcher = _make_fake_fetcher(quote_result, hist, call_counter)
    try:
        quotes, status = rp.fetch_live_quotes(['NIFTY'], offline=False)
    finally:
        rp.ZerodhaDataFetcher = orig

    assert status == 'live', status
    assert quotes['NIFTY']['last_price'] == 25000.0, quotes['NIFTY']
    assert call_counter.get('historical', 0) == 0, \
        f"chart fallback must not run when get_quote() succeeds, called {call_counter.get('historical', 0)}x"
    return f"status={status} chart_calls={call_counter.get('historical', 0)}"


# ---------------------------------------------------------------------------
# (e) mark_open_positions: chart-sourced quote -> mark_source 'CHART' + note
# ---------------------------------------------------------------------------
def test_mark_open_positions_chart_source():
    bar_ts = datetime(2026, 8, 4, 11, 30)
    quotes = {'NIFTY': {'last_price': 25050.0, 'timestamp': bar_ts, 'source': 'chart'}}
    rows = [{'symbol': 'NIFTY', 'direction': 'BUY', 'entry_price': 25000.0, 'quantity': 10}]

    rp.mark_open_positions(rows, quotes, None)

    row = rows[0]
    assert row['mark_source'] == 'CHART', row['mark_source']
    assert row['mark_price'] == 25050.0, row['mark_price']
    assert '2026-08-04 11:30' in row['mark_note'], row['mark_note']
    assert row['unrealized'] == (25050.0 - 25000.0) * 10, row['unrealized']
    return f"mark_source={row['mark_source']} mark_note={row['mark_note']!r}"


def main():
    tests = [
        test_chart_fallback_basic,
        test_chart_fallback_partial_failure_isolated,
        test_chart_fallback_all_empty_falls_to_quote_failed,
        test_live_quote_success_skips_chart_path,
        test_mark_open_positions_chart_source,
    ]
    passed = failed = 0
    print("=" * 78)
    for fn in tests:
        try:
            detail = fn()
            print(f"PASS  {fn.__name__:48} {detail}")
            passed += 1
        except Exception as e:
            print(f"FAIL  {fn.__name__:48} {type(e).__name__}: {e}")
            failed += 1
    print("=" * 78)
    print(f"{passed}/{passed + failed} scenarios passed.")
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
