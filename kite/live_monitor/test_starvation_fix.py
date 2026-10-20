"""Acceptance tests for the 2026-10-20 incubator starvation fix
(docs/superpowers/specs/2026-10-20-incubator-starvation-fix-design.md).

  (a) check_open_positions: a held non-NIFTY-50 symbol with no quote and no
      data_cache entry is priced from the chart API, so its stop-loss fires.
  (b) a symbol nothing can price -> exactly one Telegram warning per day, and
      no exception escapes.
  (c) scan_swing_candidates: MAX_SWING_SLOTS=2 cap on ROTATION/SWING positions.
  (d) parity check_p3: data/p3_reset.json -> WARMING_UP; no file -> unchanged.
  (e) market_open_today(): no bars dated today after 09:20 -> scan cycle runs
      nothing (clock mocked); a today-dated bar -> runs.

Standalone: `python kite/live_monitor/test_starvation_fix.py` -- plain asserts,
no pytest, no network, no login, no enctoken. Everything runs against temp
dirs / temp sqlite files; the real data/ tree is never touched (monitor.py's
import-time FileHandler on data/monitor.log is neutralised below).
"""
import json
import logging
import os
import sys
import tempfile
from datetime import datetime, timedelta
from pathlib import Path
from types import SimpleNamespace

import pandas as pd

_CODE_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(_CODE_ROOT))

# monitor.py calls logging.basicConfig(...) at import with a FileHandler on
# data/monitor.log. basicConfig is a no-op when the root logger already has a
# handler, so give it one and the real log is never opened.
logging.getLogger().addHandler(logging.NullHandler())

from kite.live_monitor import monitor as monitor_mod            # noqa: E402
from kite.live_monitor.monitor import LiveMonitor                # noqa: E402
from kite.live_monitor.paper_trader import PaperTrader           # noqa: E402
from kite.live_monitor.entry_pipeline import EntryPipeline       # noqa: E402
from kite.live_monitor import parity_monitor                     # noqa: E402


class FakeTelegram:
    def __init__(self):
        self.messages = []

    def send_message(self, text, *a, **k):
        self.messages.append(text)

    def send_exit_alert(self, *a, **k):
        pass


class FakeFetcher:
    """get_quote always {} (dead enctoken session); chart data by symbol."""
    def __init__(self, charts=None, raises=()):
        self.charts = charts or {}
        self.raises = set(raises)
        self.chart_calls = []

    def get_quote(self, symbols):
        return {}

    def get_historical_data(self, symbol, interval="day", days=60):
        self.chart_calls.append(symbol)
        if symbol in self.raises:
            raise RuntimeError("chart api down")
        return self.charts.get(symbol)


def _sig(symbol, mode="ROTATION", price=100.0, qty=10, sl=90.0, tp=200.0, direction="BUY"):
    return SimpleNamespace(symbol=symbol, direction=direction, entry_price=price,
                           quantity=qty, stop_loss=sl, take_profit=tp,
                           strategy="test_strat", trade_mode=mode)


def _daily_df(close=100.0, n=60):
    idx = pd.date_range("2026-01-01", periods=n, freq="D")
    return pd.DataFrame({"close": [close] * n, "volume": [1_000_000] * n}, index=idx)


def _bare_monitor(tmp, fetcher=None):
    m = LiveMonitor.__new__(LiveMonitor)
    m.trader = PaperTrader(100000, 5, db_path=str(Path(tmp) / "main.db"))
    m.incubator = PaperTrader(100000, 5, db_path=str(Path(tmp) / "inc.db"))
    m.fetcher = fetcher
    m.telegram = FakeTelegram()
    m.data_cache = {}
    m._no_price_alerted = {}
    return m


# ---------------------------------------------------------------------------
def test_a_chart_fallback_prices_non_nifty_position():
    with tempfile.TemporaryDirectory() as tmp:
        chart = pd.DataFrame({"close": [1300.0, 1256.0]},
                             index=pd.date_range("2026-10-20 15:00", periods=2, freq="min"))
        f = FakeFetcher(charts={"BSEX": chart})
        m = _bare_monitor(tmp, f)
        # A: NIFTY-50 name held in main book, priced from data_cache (healthy).
        m.data_cache = {"AAA": pd.DataFrame({"close": [500.0]})}
        m.trader.open_position(_sig("AAA", mode="SWING", price=500, sl=400, tp=900))
        # B: non-N50 incubator swing position, stop ABOVE the chart price.
        m.incubator.open_position(_sig("BSEX", price=1500, sl=1465, tp=2000))
        assert "BSEX" in m.incubator.positions

        m.check_open_positions()

        assert "BSEX" not in m.incubator.positions, "stop-loss never fired"
        closed = m.incubator.closed_trades[-1]
        assert closed.exit_reason == "stop_loss" or "stop" in str(closed.exit_reason).lower(), closed.exit_reason
        assert "AAA" in m.trader.positions            # still open, priced from cache
        assert "AAA" not in f.chart_calls             # cache rung filled it, no chart call
        assert m.telegram.messages == []
    print("PASS (a) chart fallback closes non-N50 position on stop-loss")


def test_b_unpriceable_symbol_alerts_once_per_day():
    with tempfile.TemporaryDirectory() as tmp:
        f = FakeFetcher(raises={"CCC"})
        m = _bare_monitor(tmp, f)
        m.incubator.open_position(_sig("CCC", price=100, sl=90, tp=200))
        m.check_open_positions()
        m.check_open_positions()   # second call, same day
        warns = [t for t in m.telegram.messages if "no price for CCC" in t]
        assert len(warns) == 1, m.telegram.messages
        assert "incubator" in warns[0] and "stop-loss NOT checked" in warns[0]
        assert "CCC" in m.incubator.positions        # untouched, no crash
        # a new day re-arms the alert
        m._no_price_alerted = {(s, "2000-01-01"): True for s, _ in m._no_price_alerted}
        m.check_open_positions()
        assert len([t for t in m.telegram.messages if "no price for CCC" in t]) == 2
    print("PASS (b) one Telegram warning per symbol per day, no exception")


def test_c_swing_slot_cap():
    def run(n_rotation, n_intraday=0):
        with tempfile.TemporaryDirectory() as tmp:
            m = _bare_monitor(tmp)
            m.telegram = FakeTelegram()
            m.entry = EntryPipeline(SimpleNamespace(is_flagged=lambda s: None), m.telegram,
                                    offline=True,
                                    kill_switch_file=Path(tmp) / "kill.json")
            for i in range(n_rotation):
                assert m.incubator.open_position(_sig(f"ROT{i}", mode="ROTATION"))
            for i in range(n_intraday):
                assert m.incubator.open_position(_sig(f"INT{i}", mode="INTRADAY"))
            sig = _sig("NEWSYM")
            m.swing_candidate_detectors = [SimpleNamespace(
                strategy_name="test_strat", detect_signal=lambda s, df: sig)]
            m.wide_daily_cache = {"NEWSYM": _daily_df()}
            m.daily_data_cache = {}
            m.scan_swing_candidates()
            return "NEWSYM" in m.incubator.positions

    assert LiveMonitor.MAX_SWING_SLOTS == 2
    assert run(2) is False, "3rd swing position should be blocked"
    assert run(1) is True, "2nd swing position should be allowed"
    assert run(1, n_intraday=2) is True, "intraday positions must not count toward the cap"
    print("PASS (c) swing cap blocks at 2, allows at 1, ignores intraday")


def test_d_p3_reset():
    saved_file = parity_monitor.P3_RESET_FILE
    saved_rows = parity_monitor.strategy_rows
    saved_env = os.environ.get(parity_monitor.PARITY_TODAY_OVERRIDE_VAR)
    os.environ[parity_monitor.PARITY_TODAY_OVERRIDE_VAR] = "2026-10-20"
    try:
        first = (datetime(2026, 10, 20) - timedelta(days=40)).isoformat()
        parity_monitor.strategy_rows = lambda *a, **k: [{"entry_time": first}]
        card = {"trades_per_month": {"lambda": 100.0, "lambda_quality": "rough-extrapolation"}}
        today = parity_monitor._today()

        with tempfile.TemporaryDirectory() as tmp:
            # no reset file -> today's RED behaviour (k=0, rough mu>=10)
            parity_monitor.P3_RESET_FILE = Path(tmp) / "p3_reset.json"
            r = parity_monitor.check_p3("x", "incubator", "INTRADAY", card)
            assert r["status"] == "RED", r

            # corrupt file -> same as missing
            parity_monitor.P3_RESET_FILE.write_text("{not json")
            assert parity_monitor.check_p3("x", "incubator", "INTRADAY", card)["status"] == "RED"
            parity_monitor.P3_RESET_FILE.write_text(json.dumps({"date": "garbage"}))
            assert parity_monitor.check_p3("x", "incubator", "INTRADAY", card)["status"] == "RED"

            # reset 3 trading days ago -> WARMING_UP
            reset = parity_monitor._n_trading_days_ago(3)
            parity_monitor.P3_RESET_FILE.write_text(json.dumps({"date": reset.isoformat()}))
            r = parity_monitor.check_p3("x", "incubator", "INTRADAY", card)
            assert r["status"] == "WARMING_UP", r
            assert "since P3 reset" in r["detail"] and "/10" in r["detail"], r

            # reset 12 trading days ago -> past warm-up, window clipped, k=0 -> RED again
            reset = parity_monitor._n_trading_days_ago(12)
            parity_monitor.P3_RESET_FILE.write_text(json.dumps({"date": reset.isoformat()}))
            r = parity_monitor.check_p3("x", "incubator", "INTRADAY", card)
            assert r["status"] != "WARMING_UP", r
            n_td = parity_monitor.trading_days_between(reset, today)
            assert f"in {n_td}td" in r["detail"], (r, n_td)
    finally:
        parity_monitor.P3_RESET_FILE = saved_file
        parity_monitor.strategy_rows = saved_rows
        if saved_env is None:
            os.environ.pop(parity_monitor.PARITY_TODAY_OVERRIDE_VAR, None)
        else:
            os.environ[parity_monitor.PARITY_TODAY_OVERRIDE_VAR] = saved_env
    print("PASS (d) p3_reset -> WARMING_UP; missing/corrupt -> unchanged RED")


def test_e_market_holiday_guard():
    NOW = datetime(2026, 10, 20, 10, 0)

    class FakeDT(datetime):
        @classmethod
        def now(cls, tz=None):
            return NOW

    def bars(day):
        return pd.DataFrame({"close": [1.0]}, index=pd.DatetimeIndex([day]))

    saved_dt = monitor_mod.datetime
    monitor_mod.datetime = FakeDT
    try:
        def make(day):
            m = _bare_monitor(tempfile.mkdtemp(dir=tmp_root))
            m.offline = False
            m.history_loaded = True
            m._market_open_date = None
            m._closed_alert_date = None
            m.data_cache = {"AAA": bars(day)}
            calls = []
            m.is_market_hours = lambda: True
            m._refresh_token_if_needed = lambda: None
            m.entry = SimpleNamespace(reload_paused=lambda: None)
            m.update_with_latest_candle = lambda: None
            for name in ("check_open_positions", "scan_for_signals", "process_signals",
                         "scan_incubator", "scan_swing_candidates", "run_momentum_rotation"):
                setattr(m, name, (lambda n: lambda *a, **k: calls.append(n) or [])(name))
            m.swing_scanned_today = False
            return m, calls

        with tempfile.TemporaryDirectory() as tmp_root:
            # holiday: only yesterday-dated bars at 10:00
            m, calls = make(datetime(2026, 10, 19, 15, 25))
            assert m.market_open_today(NOW) is False
            m.run_scan_cycle()
            m.run_scan_cycle()
            assert calls == [], calls
            closed_msgs = [t for t in m.telegram.messages if "Market closed" in t]
            assert len(closed_msgs) == 1, m.telegram.messages     # once per day

            # trading day: a today-dated bar -> True, cycle proceeds, answer cached
            m, calls = make(datetime(2026, 10, 20, 9, 55))
            assert m.market_open_today(NOW) is True
            m.data_cache = {}                                      # cached for the day
            assert m.market_open_today(NOW) is True
            m._market_open_date = None
            assert m.market_open_today(NOW) is False               # cache gone, no bars
            # before 09:20 never blocks the open
            assert m.market_open_today(datetime(2026, 10, 20, 9, 10)) is True
            m, calls = make(datetime(2026, 10, 20, 9, 55))
            m.run_scan_cycle()
            assert "check_open_positions" in calls and "scan_incubator" in calls, calls
    finally:
        monitor_mod.datetime = saved_dt
    print("PASS (e) holiday guard: no bars today -> nothing runs; bar today -> runs")


if __name__ == "__main__":
    test_a_chart_fallback_prices_non_nifty_position()
    test_b_unpriceable_symbol_alerts_once_per_day()
    test_c_swing_slot_cap()
    test_d_p3_reset()
    test_e_market_holiday_guard()
    print("ALL PASS")
