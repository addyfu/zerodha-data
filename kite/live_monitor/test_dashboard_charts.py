"""Acceptance tests for dashboard.py's position-charts feature (2026-08-05 spec,
docs/superpowers/specs/2026-08-05-dashboard-position-charts-design.md).

Covers spec tests (a)-(g):
  (a) endpoint JSON correct on synthetic DBs (candles + levels + markers)
  (b) indicator parity: dashboard's indicator values match SignalDetector's own
      computation on a shared fixture series (the fidelity rule, tested)
  (c) cache: second call within TTL performs zero fetches (counter)
  (d) no token + no DB coverage -> "chart unavailable", HTTP 200, no raise
  (e) unknown strategy -> unavailable, no raise
  (f) rotation mapping returns daily candles, intraday returns minute
  (g) rendered chart page contains container div, vendored JS reference, and
      the params echo

Standalone: `python kite/live_monitor/test_dashboard_charts.py` -- plain
asserts, no pytest, ZERO network (the one real network call site,
_chart_api_fetch, is always monkeypatched with a counting stub or never
reached because _resolve_enctoken is monkeypatched to return no token).
Every scenario runs against throwaway sqlite/CSV files in a temp dir; the
real books/zerodha_data.db/data/daily are never touched. Style matches
test_dashboard_prices.py.
"""
import random
import sqlite3
import sys
import tempfile
from datetime import datetime
from pathlib import Path

import pandas as pd

_CODE_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(_CODE_ROOT))

from kite.live_monitor import dashboard

# Remember the module's real (env-derived) paths so every test can point
# them at its own throwaway fixtures without ever touching the real ones,
# and so nothing leaks between tests.
_ORIG_MAIN_DB = dashboard.MAIN_DB
_ORIG_INCUBATOR_DB = dashboard.INCUBATOR_DB
_ORIG_ZERODHA_DB = dashboard.ZERODHA_DB
_ORIG_BOOKS = dashboard.BOOKS
_ORIG_DAILY_DATA_DIR = dashboard.DAILY_DATA_DIR
_ORIG_RESOLVE_ENCTOKEN = dashboard._resolve_enctoken
_ORIG_CHART_API_FETCH = dashboard._chart_api_fetch


def _use_dbs(main_db, incubator_db, zerodha_db, daily_dir):
    dashboard.MAIN_DB = Path(main_db)
    dashboard.INCUBATOR_DB = Path(incubator_db)
    dashboard.ZERODHA_DB = Path(zerodha_db)
    dashboard.BOOKS = [("main", dashboard.MAIN_DB), ("incubator", dashboard.INCUBATOR_DB)]
    dashboard.DAILY_DATA_DIR = Path(daily_dir)


def _restore():
    dashboard.MAIN_DB = _ORIG_MAIN_DB
    dashboard.INCUBATOR_DB = _ORIG_INCUBATOR_DB
    dashboard.ZERODHA_DB = _ORIG_ZERODHA_DB
    dashboard.BOOKS = _ORIG_BOOKS
    dashboard.DAILY_DATA_DIR = _ORIG_DAILY_DATA_DIR
    dashboard._resolve_enctoken = _ORIG_RESOLVE_ENCTOKEN
    dashboard._chart_api_fetch = _ORIG_CHART_API_FETCH
    dashboard._chart_cache.clear()


# ---------------------------------------------------------------------------
# fixture builders
# ---------------------------------------------------------------------------
def _make_positions_db(path, positions=()):
    """Same positions-table shape as test_dashboard_prices.py's _make_book_db
    (nullable stop_loss/take_profit -- fine for a test-only fixture)."""
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
    for p in positions:
        conn.execute(
            "INSERT INTO positions (symbol, direction, entry_price, entry_time, quantity, "
            "stop_loss, take_profit, strategy, status, exit_price, exit_time, exit_reason) "
            "VALUES (?,?,?,?,?,?,?,?,?,?,?,?)",
            (p['symbol'], p['direction'], p['entry_price'], p['entry_time'], p.get('quantity', 10),
             p.get('stop_loss'), p.get('take_profit'), p.get('strategy', 'test'),
             p.get('status', 'open'), p.get('exit_price'), p.get('exit_time'), p.get('exit_reason')),
        )
    conn.commit()
    conn.close()


def _synthetic_minute_rows(symbol, date_str, n=120, start_price=100.0, seed=1):
    """Deterministic (seeded) synthetic minute OHLCV rows for one session,
    starting at 09:15. Enough bars (n>=100) for period-14/20/21 indicators to
    have real (non-NaN) values well before the end of the session."""
    rnd = random.Random(seed)
    rows = []
    price = start_price
    t0 = pd.Timestamp(f"{date_str} 09:15:00")
    for i in range(n):
        t = t0 + pd.Timedelta(minutes=i)
        change = rnd.uniform(-0.5, 0.5)
        o = price
        c = price + change
        h = max(o, c) + abs(rnd.uniform(0, 0.3))
        l = min(o, c) - abs(rnd.uniform(0, 0.3))
        vol = rnd.randint(100, 1000)
        rows.append((symbol, t.strftime('%Y-%m-%d %H:%M:%S'), 'minute', o, h, l, c, vol))
        price = c
    return rows


def _make_zerodha_ohlcv_db(path, rows=()):
    """rows: iterable of (symbol, datetime_str, interval, open, high, low, close, volume)."""
    conn = sqlite3.connect(str(path))
    conn.execute("""
        CREATE TABLE ohlcv (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            symbol TEXT NOT NULL,
            datetime TEXT NOT NULL,
            interval TEXT NOT NULL,
            open REAL, high REAL, low REAL, close REAL, volume INTEGER, oi INTEGER DEFAULT 0
        )
    """)
    conn.executemany(
        "INSERT INTO ohlcv (symbol, datetime, interval, open, high, low, close, volume) "
        "VALUES (?,?,?,?,?,?,?,?)",
        rows,
    )
    conn.commit()
    conn.close()


def _make_daily_csv(daily_dir, symbol, n=200, start_price=500.0, end_date='2026-08-04', seed=7):
    """Writes {symbol}_day_2000d.csv in the same shape as the real
    data/daily/*.csv files (datetime,open,high,low,close,volume,oi)."""
    Path(daily_dir).mkdir(parents=True, exist_ok=True)
    rnd = random.Random(seed)
    end = pd.Timestamp(end_date)
    dates = pd.bdate_range(end=end, periods=n)  # business days, deterministic spacing
    price = start_price
    lines = ["datetime,open,high,low,close,volume,oi"]
    for d in dates:
        change = rnd.uniform(-3, 3)
        o = price
        c = price + change
        h = max(o, c) + abs(rnd.uniform(0, 2))
        l = min(o, c) - abs(rnd.uniform(0, 2))
        vol = rnd.randint(10000, 100000)
        lines.append(f"{d.strftime('%Y-%m-%d')} 00:00:00+05:30,{o:.2f},{h:.2f},{l:.2f},{c:.2f},{vol},0")
        price = c
    (Path(daily_dir) / f"{symbol}_day_2000d.csv").write_text("\n".join(lines), encoding='utf-8')


def _synthetic_fixture_df(n=60, start_price=200.0, seed=3):
    """A plain in-memory OHLCV DataFrame (datetime index) for the indicator-
    parity test -- no DB/CSV involved, just what _run_strategy_indicator()
    and SignalDetector's own strategy.generate_signals() both consume."""
    rnd = random.Random(seed)
    t0 = pd.Timestamp('2026-08-03 09:15:00')
    price = start_price
    recs = []
    for i in range(n):
        t = t0 + pd.Timedelta(minutes=i)
        change = rnd.uniform(-1.0, 1.0)
        o = price
        c = price + change
        h = max(o, c) + abs(rnd.uniform(0, 0.5))
        l = min(o, c) - abs(rnd.uniform(0, 0.5))
        vol = rnd.randint(100, 1000)
        recs.append({'datetime': t, 'open': o, 'high': h, 'low': l, 'close': c, 'volume': vol})
        price = c
    df = pd.DataFrame(recs).set_index('datetime')
    return df


# ---------------------------------------------------------------------------
# (a) endpoint JSON correct on synthetic DBs (candles + levels + markers)
# ---------------------------------------------------------------------------
def test_a_endpoint_json_correct_on_synthetic_dbs(tmp):
    main_db, inc_db, zdb = Path(tmp) / 'main.db', Path(tmp) / 'inc.db', Path(tmp) / 'z.db'
    daily_dir = Path(tmp) / 'daily'
    _make_positions_db(main_db, positions=[dict(
        symbol='TESTSYM', direction='BUY', entry_price=100.5, entry_time='2026-08-03 09:20:00',
        stop_loss=98.0, take_profit=105.0, strategy='rsi_trend_confirmation', status='open',
    )])
    _make_positions_db(inc_db)
    rows = (_synthetic_minute_rows('TESTSYM', '2026-08-02', n=100, seed=11)
            + _synthetic_minute_rows('TESTSYM', '2026-08-03', n=100, seed=12))
    _make_zerodha_ohlcv_db(zdb, rows)
    _use_dbs(main_db, inc_db, zdb, daily_dir)

    # 'today' is 2026-08-05 -- 2026-08-03 is a past day, so this exercises the
    # DB tier with no token/network involved at all.
    payload = dashboard.build_chart_payload(
        'TESTSYM', '2026-08-03', 'rsi_trend_confirmation', 'main',
        now=datetime(2026, 8, 5, 10, 0, 0))

    assert payload['available'] is True, payload
    assert len(payload['candles']) > 0, 'expected non-empty candles'
    assert payload['chart_type'] == 'minute'
    assert payload['source'] == 'db'
    assert payload['stale'] is False, 'a genuinely past day is the historical record, not stale'

    ind = payload['indicator']
    assert ind is not None and ind['indicator'] == 'rsi' and ind['period'] == 14, ind
    assert len(ind['series']) == len(payload['candles'])
    assert any(v is not None for v in ind['series']), 'expected some non-NaN RSI values'

    trade = payload['trade']
    assert trade['entry_price'] == 100.5 and trade['stop_loss'] == 98.0 and trade['take_profit'] == 105.0

    assert len(payload['markers']) == 1, f"expected exactly one (entry) marker, got {payload['markers']}"
    m = payload['markers'][0]
    assert 'entry' in m['text'] and m['shape'] == 'arrowUp'  # BUY entry
    return f"{len(payload['candles'])} candles, rsi period=14, 1 entry marker, source=db not stale"


# ---------------------------------------------------------------------------
# (b) indicator parity: dashboard's values match SignalDetector's own
#     computation on a shared fixture series
# ---------------------------------------------------------------------------
def test_b_indicator_parity_with_signal_detector(tmp):
    from kite.live_monitor.signal_detector import SignalDetector

    df = _synthetic_fixture_df(n=60, seed=5)

    checked = []
    for strategy_name, cols in [
        ('bb_mean_reversion', ['bb_upper', 'bb_middle', 'bb_lower']),
        ('adx_filter', ['adx']),
    ]:
        sd = SignalDetector(strategy_name)  # the real live signal-detection object
        expected = sd.strategy.generate_signals(df.copy())

        out_df, spec_meta, err = dashboard._run_strategy_indicator(strategy_name, df)
        assert err is None, f"{strategy_name}: {err}"
        assert spec_meta is not None

        for col in cols:
            exp_vals = expected[col].tolist()
            got_vals = out_df[col].tolist()
            assert len(exp_vals) == len(got_vals)
            for e, g in zip(exp_vals, got_vals):
                e_nan = e != e
                g_nan = g != g
                assert e_nan == g_nan, f"{strategy_name}.{col}: NaN mismatch ({e} vs {g})"
                if not e_nan:
                    assert abs(e - g) < 1e-9, f"{strategy_name}.{col}: {e} != {g}"
        checked.append(strategy_name)

    return f"parity holds for {', '.join(checked)} against SignalDetector's own strategy.generate_signals()"


# ---------------------------------------------------------------------------
# (c) cache: second call within TTL performs zero fetches (counter)
# ---------------------------------------------------------------------------
def test_c_cache_second_call_zero_fetches(tmp):
    dashboard._chart_cache.clear()
    calls = {'n': 0}

    def _counting_fetch(symbol, token):
        calls['n'] += 1
        return _synthetic_fixture_df(n=10, seed=9)

    dashboard._chart_api_fetch = _counting_fetch
    try:
        df1 = dashboard.get_today_minute_bars('CACHESYM', 'faketoken')
        df2 = dashboard.get_today_minute_bars('CACHESYM', 'faketoken')
        assert df1 is not None and df2 is not None
        assert calls['n'] == 1, f"expected exactly 1 real fetch, got {calls['n']}"
        # a different (symbol, interval) key is NOT cached under the same slot
        dashboard.get_today_minute_bars('OTHERSYM', 'faketoken')
        assert calls['n'] == 2
    finally:
        dashboard._chart_api_fetch = _ORIG_CHART_API_FETCH
        dashboard._chart_cache.clear()
    return "2nd call within 60s TTL hit the cache (0 fetches); a different symbol still fetched"


# ---------------------------------------------------------------------------
# (d) no token + no DB coverage -> "chart unavailable", HTTP 200 (never
#     raises), reflected on both build_chart_payload() and render_chart_page()
# ---------------------------------------------------------------------------
def test_d_no_token_no_db_unavailable(tmp):
    main_db, inc_db, zdb = Path(tmp) / 'main.db', Path(tmp) / 'inc.db', Path(tmp) / 'z.db'
    daily_dir = Path(tmp) / 'daily'
    today = datetime(2026, 8, 5, 10, 0, 0)
    _make_positions_db(main_db, positions=[dict(
        symbol='NOTOKEN', direction='BUY', entry_price=50.0, entry_time='2026-08-05 09:20:00',
        stop_loss=48.0, take_profit=55.0, strategy='adx_filter', status='open',
    )])
    _make_positions_db(inc_db)
    _make_zerodha_ohlcv_db(zdb, [])  # DB exists but carries nothing for this symbol
    _use_dbs(main_db, inc_db, zdb, daily_dir)
    dashboard._resolve_enctoken = lambda: ''  # force "no token" -- never a real fetch attempt
    dashboard._chart_cache.clear()

    try:
        payload = dashboard.build_chart_payload('NOTOKEN', '2026-08-05', 'adx_filter', 'main', now=today)
    except Exception as e:
        raise AssertionError(f"build_chart_payload raised: {e!r}")

    assert payload['available'] is False, payload
    assert 'no token' in payload['reason'] and 'no DB coverage' in payload['reason'], payload['reason']

    try:
        html_out = dashboard.render_chart_page('NOTOKEN', '2026-08-05', 'adx_filter', 'main', now=today)
    except Exception as e:
        raise AssertionError(f"render_chart_page raised: {e!r}")
    assert 'chart unavailable:' in html_out, html_out[:300]
    return f"available=False, reason={payload['reason']!r}, page shows 'chart unavailable:' line, no raise"


# ---------------------------------------------------------------------------
# (e) unknown strategy -> unavailable, no raise
# ---------------------------------------------------------------------------
def test_e_unknown_strategy_unavailable(tmp):
    main_db, inc_db, zdb = Path(tmp) / 'main.db', Path(tmp) / 'inc.db', Path(tmp) / 'z.db'
    daily_dir = Path(tmp) / 'daily'
    _make_positions_db(main_db)
    _make_positions_db(inc_db)
    _make_zerodha_ohlcv_db(zdb, [])
    _use_dbs(main_db, inc_db, zdb, daily_dir)

    try:
        payload = dashboard.build_chart_payload('ANYSYM', '2026-08-04', 'not_a_real_strategy', 'main')
    except Exception as e:
        raise AssertionError(f"build_chart_payload raised: {e!r}")
    assert payload['available'] is False
    assert 'unknown strategy' in payload['reason'], payload['reason']

    try:
        html_out = dashboard.render_chart_page('ANYSYM', '2026-08-04', 'not_a_real_strategy', 'main')
    except Exception as e:
        raise AssertionError(f"render_chart_page raised: {e!r}")
    assert 'chart unavailable:' in html_out and 'unknown strategy' in html_out
    return f"reason={payload['reason']!r}, no raise from either build_chart_payload or render_chart_page"


# ---------------------------------------------------------------------------
# (f) rotation mapping returns daily candles, intraday returns minute
# ---------------------------------------------------------------------------
def test_f_rotation_daily_vs_intraday_minute(tmp):
    main_db, inc_db, zdb = Path(tmp) / 'main.db', Path(tmp) / 'inc.db', Path(tmp) / 'z.db'
    daily_dir = Path(tmp) / 'daily'

    _make_positions_db(main_db, positions=[
        dict(symbol='ROTSYM', direction='BUY', entry_price=520.0, entry_time='2026-08-04 09:47:00',
             stop_loss=442.0, take_profit=1040.0, strategy='momo_rotation_63', status='open'),
        dict(symbol='INTRASYM', direction='BUY', entry_price=200.5, entry_time='2026-08-03 09:20:00',
             stop_loss=198.0, take_profit=205.0, strategy='bb_mean_reversion', status='open'),
    ])
    _make_positions_db(inc_db)
    _make_daily_csv(daily_dir, 'ROTSYM', n=200, start_price=520.0, end_date='2026-08-04', seed=21)
    rows = (_synthetic_minute_rows('INTRASYM', '2026-08-02', n=100, seed=31)
            + _synthetic_minute_rows('INTRASYM', '2026-08-03', n=100, seed=32))
    _make_zerodha_ohlcv_db(zdb, rows)
    _use_dbs(main_db, inc_db, zdb, daily_dir)
    now = datetime(2026, 8, 5, 10, 0, 0)

    rot = dashboard.build_chart_payload('ROTSYM', '2026-08-04', 'momo_rotation_63', 'main', now=now)
    assert rot['available'] is True, rot
    assert rot['chart_type'] == 'daily', rot
    assert rot['indicator']['indicator'] == 'momentum' and rot['indicator']['period'] == 63, rot['indicator']

    intra = dashboard.build_chart_payload('INTRASYM', '2026-08-03', 'bb_mean_reversion', 'main', now=now)
    assert intra['available'] is True, intra
    assert intra['chart_type'] == 'minute', intra
    assert intra['indicator']['indicator'] == 'bollinger', intra['indicator']

    return f"momo_rotation_63 -> chart_type={rot['chart_type']!r}; bb_mean_reversion -> chart_type={intra['chart_type']!r}"


# ---------------------------------------------------------------------------
# (g) rendered chart page contains container div, vendored JS reference, and
#     the params echo
# ---------------------------------------------------------------------------
def test_g_rendered_page_has_container_js_and_params_echo(tmp):
    main_db, inc_db, zdb = Path(tmp) / 'main.db', Path(tmp) / 'inc.db', Path(tmp) / 'z.db'
    daily_dir = Path(tmp) / 'daily'
    _make_positions_db(main_db, positions=[dict(
        symbol='PAGESYM', direction='BUY', entry_price=300.0, entry_time='2026-08-03 09:20:00',
        stop_loss=295.0, take_profit=310.0, strategy='cci_divergence', status='open',
    )])
    _make_positions_db(inc_db)
    rows = (_synthetic_minute_rows('PAGESYM', '2026-08-02', n=100, seed=41)
            + _synthetic_minute_rows('PAGESYM', '2026-08-03', n=100, seed=42))
    _make_zerodha_ohlcv_db(zdb, rows)
    _use_dbs(main_db, inc_db, zdb, daily_dir)

    html_out = dashboard.render_chart_page(
        'PAGESYM', '2026-08-03', 'cci_divergence', 'main', now=datetime(2026, 8, 5, 10, 0, 0))

    assert 'id="chart-container"' in html_out, 'chart container div missing'
    assert '/static/lightweight-charts.standalone.js' in html_out, 'vendored JS <script src> missing'
    assert '"indicator": "cci"' in html_out, 'params echo (indicator name) missing from embedded JSON'
    assert 'period=21' in html_out, 'params echo (period) missing from the human-readable line'
    return 'page has #chart-container, vendored <script src>, and the cci/period=21 params echo'


# ---------------------------------------------------------------------------
# extra: the main dashboard page's position rows are links (the one change
# the spec allows to the existing page) -- quick end-to-end coverage that
# render_page() itself keeps working and now emits /chart-view links.
# ---------------------------------------------------------------------------
def test_extra_position_rows_are_chart_links(tmp):
    main_db, inc_db, zdb = Path(tmp) / 'main.db', Path(tmp) / 'inc.db', Path(tmp) / 'z.db'
    daily_dir = Path(tmp) / 'daily'
    _make_positions_db(main_db, positions=[dict(
        symbol='LINKSYM', direction='BUY', entry_price=10.0, entry_time='2026-08-05 09:20:00',
        stop_loss=9.0, take_profit=12.0, strategy='rsi_trend_confirmation', status='open',
    )])
    _make_positions_db(inc_db)
    _make_zerodha_ohlcv_db(zdb, [])
    _use_dbs(main_db, inc_db, zdb, daily_dir)

    page = dashboard.render_page()
    assert 'href="/chart-view?' in page, 'no /chart-view link rendered on the main page'
    assert 'symbol=LINKSYM' in page and 'strategy=rsi_trend_confirmation' in page
    return "open position row on the main dashboard page links to /chart-view?..."


def test_tz_aware_chart_api_frame_normalized(tmp):
    """Reviewer regression (2026-08-05): the REAL chart API returns a
    tz-aware (+05:30) index while every other bar source is naive-IST; the
    first live fetch crashed window slicing with 'can't compare offset-naive
    and offset-aware datetimes'. get_today_minute_bars must strip the tz."""
    idx = pd.date_range('2026-08-05 09:15', periods=5, freq='1min',
                        tz='Asia/Kolkata')
    aware = pd.DataFrame({'open': 10.0, 'high': 11.0, 'low': 9.0,
                          'close': 10.5, 'volume': 100}, index=idx)
    orig_fetch = dashboard._chart_api_fetch
    dashboard._chart_api_fetch = lambda symbol, token: aware
    dashboard._chart_cache.clear()
    try:
        df = dashboard.get_today_minute_bars('TZSYM', 'FAKE_TOKEN')
    finally:
        dashboard._chart_api_fetch = orig_fetch
        dashboard._chart_cache.clear()
    assert df is not None and len(df) == 5
    assert getattr(df.index, 'tz', None) is None, 'tz must be stripped'
    assert str(df.index[0]) == '2026-08-05 09:15:00', df.index[0]
    return f"aware +05:30 frame normalized to naive-IST: first bar {df.index[0]}"


def main():
    tests = [
        test_a_endpoint_json_correct_on_synthetic_dbs,
        test_b_indicator_parity_with_signal_detector,
        test_c_cache_second_call_zero_fetches,
        test_d_no_token_no_db_unavailable,
        test_e_unknown_strategy_unavailable,
        test_f_rotation_daily_vs_intraday_minute,
        test_g_rendered_page_has_container_js_and_params_echo,
        test_extra_position_rows_are_chart_links,
        test_tz_aware_chart_api_frame_normalized,
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
                    _restore()
    finally:
        _restore()
    print('=' * 78)
    print(f'{passed}/{passed + failed} scenarios passed.')
    return 1 if failed else 0


if __name__ == '__main__':
    sys.exit(main())
