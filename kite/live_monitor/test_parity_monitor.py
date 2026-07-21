"""
Acceptance test suite for the Parity Monitor
=============================================
Companion to docs/superpowers/specs/2026-07-21-parity-monitor-design.md.
Section 1's incident table is the test list -- every historical disaster this
project has hit must be caught by one of parity_monitor.py's checks (P1-P12).

Plain assert + a main() runner -- no pytest dependency. Run standalone:

    python kite/live_monitor/test_parity_monitor.py

How it works: for each scenario this builds a synthetic KITE_ROOT fixture
directory (tempfile) containing its own data/paper_trades.db,
data/incubator_trades.db (same `positions` schema as the real PaperTrader --
see paper_trader.py:_init_database), data/monitor.log, a copy of the real
kite/live_monitor/expectations/*.json cards, and data/momo_rotation_state.json.
It then runs the REAL parity_monitor.py as a subprocess with KITE_ROOT (and,
where the scenario calls for it, PARITY_LOG_ONLY) pointed at the fixture --
never imports/monkeypatches the module under test -- and parses its printed
JSON result plus whatever it wrote into the fixture (parity_history.jsonl,
strategies_paused.json) to assert on check statuses.

Timestamps are all datetime.now()-relative (trading-day arithmetic duplicated
from parity_monitor.py purely to know WHERE to place synthetic trades in the
check windows -- this file never imports parity_monitor.py itself).
"""
import json
import os
import shutil
import sqlite3
import subprocess
import sys
import tempfile
from datetime import datetime, date, time, timedelta
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
PARITY_SCRIPT = REPO_ROOT / 'kite' / 'live_monitor' / 'parity_monitor.py'
EXPECTATIONS_SRC = REPO_ROOT / 'kite' / 'live_monitor' / 'expectations'
DAILY_UNIVERSE_SRC = REPO_ROOT / 'data' / 'daily_universe'

TODAY = date.today()


# ---------------------------------------------------------------------------
# Date-arithmetic helpers, duplicated (not imported) from parity_monitor.py.
# Needed only to compute WHERE (which trading day) a synthetic trade must
# land to fall inside/outside a given check's rolling window. Kept identical
# to the production functions on purpose -- if parity_monitor.py's own
# arithmetic ever changes, these should be updated to match (that's a
# maintenance cost of testing at arm's length via subprocess instead of
# importing, but it's what lets this suite exercise the exact code path the
# Oracle systemd timer runs, .env loading and all).
# ---------------------------------------------------------------------------
def trading_days_between(start: date, end: date) -> int:
    if start > end:
        return 0
    d, count = start, 0
    while d <= end:
        if d.weekday() < 5:
            count += 1
        d += timedelta(days=1)
    return count


def n_trading_days_ago(n: int, end: date = None) -> date:
    end = end or TODAY
    d, count = end, 0
    while count < n:
        d -= timedelta(days=1)
        if d.weekday() < 5:
            count += 1
    return d


def trading_days_list(start: date, end: date):
    out = []
    d = start
    while d <= end:
        if d.weekday() < 5:
            out.append(d)
        d += timedelta(days=1)
    return out


def is_market_day(d: date = None) -> bool:
    d = d or TODAY
    return d.weekday() < 5


# ---------------------------------------------------------------------------
# positions table schema -- copied verbatim from paper_trader.py:_init_database
# (plus the sibling account/daily_summary/latest_prices tables, for schema
# fidelity even though parity_monitor.py never queries them).
# ---------------------------------------------------------------------------
POSITIONS_SCHEMA = """
    CREATE TABLE IF NOT EXISTS positions (
        id INTEGER PRIMARY KEY,
        symbol TEXT NOT NULL,
        direction TEXT NOT NULL,
        entry_price REAL NOT NULL,
        entry_time TEXT NOT NULL,
        quantity INTEGER NOT NULL,
        stop_loss REAL NOT NULL,
        take_profit REAL NOT NULL,
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
"""
ACCOUNT_SCHEMA = """
    CREATE TABLE IF NOT EXISTS account (
        id INTEGER PRIMARY KEY,
        capital REAL NOT NULL,
        initial_capital REAL NOT NULL,
        trade_counter INTEGER DEFAULT 0,
        last_updated TEXT
    )
"""
DAILY_SUMMARY_SCHEMA = """
    CREATE TABLE IF NOT EXISTS daily_summary (
        date TEXT PRIMARY KEY,
        trades INTEGER DEFAULT 0,
        wins INTEGER DEFAULT 0,
        losses INTEGER DEFAULT 0,
        pnl REAL DEFAULT 0,
        capital REAL
    )
"""
LATEST_PRICES_SCHEMA = """
    CREATE TABLE IF NOT EXISTS latest_prices (
        symbol TEXT PRIMARY KEY,
        price REAL NOT NULL,
        updated_at TEXT NOT NULL
    )
"""


def init_trades_db(path: Path):
    conn = sqlite3.connect(str(path))
    conn.execute(POSITIONS_SCHEMA)
    conn.execute(ACCOUNT_SCHEMA)
    conn.execute(DAILY_SUMMARY_SCHEMA)
    conn.execute(LATEST_PRICES_SCHEMA)
    conn.commit()
    conn.close()


_next_id = [0]


def insert_position(db_path: Path, *, symbol, strategy, entry_price, entry_time,
                     direction='BUY', quantity=10, stop_loss=None, take_profit=None,
                     exit_price=None, exit_time=None, exit_reason=None,
                     pnl=0.0, pnl_pct=0.0, status='open', trailing_stop=None,
                     highest_price=None, lowest_price=None, trade_mode='INTRADAY'):
    _next_id[0] += 1
    if stop_loss is None:
        stop_loss = entry_price * 0.95
    if take_profit is None:
        take_profit = entry_price * 1.05

    def _iso(v):
        return v.isoformat() if hasattr(v, 'isoformat') else v

    conn = sqlite3.connect(str(db_path))
    conn.execute("""
        INSERT INTO positions (id, symbol, direction, entry_price, entry_time, quantity,
            stop_loss, take_profit, strategy, exit_price, exit_time, exit_reason,
            pnl, pnl_pct, status, trailing_stop, highest_price, lowest_price, trade_mode)
        VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)
    """, (_next_id[0], symbol, direction, entry_price, _iso(entry_time), quantity,
          stop_loss, take_profit, strategy, exit_price, _iso(exit_time), exit_reason,
          pnl, pnl_pct, status, trailing_stop, highest_price, lowest_price, trade_mode))
    conn.commit()
    conn.close()


# ---------------------------------------------------------------------------
# monitor.log line builders -- format mirrors monitor.py's logging.basicConfig:
#   '%(asctime)s - %(levelname)s - %(message)s'   (asctime default: "YYYY-MM-DD HH:MM:SS,mmm")
# ---------------------------------------------------------------------------
def log_line(dt: datetime, level: str, message: str) -> str:
    return f"{dt.strftime('%Y-%m-%d %H:%M:%S,%f')[:-3]} - {level} - {message}\n"


def write_log(path: Path, lines):
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, 'w', encoding='utf-8') as f:
        f.writelines(lines)


def healthy_lines(day: date = None, n_scan=50, daily_load=(47, 47), n_login=0, ann_flagged=2):
    """The 'nothing wrong' baseline: N scan-cycle lines, one daily-load line,
    N login lines, one ann-filter success line -- all dated `day` (default today).
    Individual scenarios override exactly the piece they're probing."""
    day = day or TODAY
    lines = []
    base = datetime.combine(day, time(9, 15, 0))
    for i in range(n_login):
        lines.append(log_line(base + timedelta(seconds=i), 'INFO', 'Login successful'))
    for i in range(n_scan):
        ts = base + timedelta(minutes=5 * i)
        lines.append(log_line(ts, 'INFO', f"--- Scan cycle starting ({ts.strftime('%H:%M:%S')}) ---"))
    x, y = daily_load
    lines.append(log_line(base + timedelta(minutes=1), 'INFO', f"Daily data loaded for {x}/{y} stocks"))
    lines.append(log_line(base + timedelta(minutes=2), 'INFO',
                           f"AnnouncementFilter: 40 announcements scanned, {ann_flagged} symbols red-flagged"))
    return lines


# ---------------------------------------------------------------------------
# Fixture: one temp KITE_ROOT per scenario
# ---------------------------------------------------------------------------
class Fixture:
    def __init__(self):
        self.root = Path(tempfile.mkdtemp(prefix='parity_fixture_'))
        self.data = self.root / 'data'
        self.data.mkdir(parents=True, exist_ok=True)
        self.expectations_dir = self.root / 'kite' / 'live_monitor' / 'expectations'
        self.paper_db = self.data / 'paper_trades.db'
        self.incubator_db = self.data / 'incubator_trades.db'
        self.log_path = self.data / 'monitor.log'
        self.momo_state_path = self.data / 'momo_rotation_state.json'
        self.paused_path = self.data / 'strategies_paused.json'
        self.history_path = self.root / 'kite' / 'live_monitor' / 'parity_history.jsonl'
        self.daily_universe_dir = self.data / 'daily_universe'

        init_trades_db(self.paper_db)
        init_trades_db(self.incubator_db)
        shutil.copytree(EXPECTATIONS_SRC, self.expectations_dir)
        # sane defaults every scenario can override
        self.set_log(healthy_lines())
        self.set_momo_state(TODAY.strftime('%Y-%m'))  # rebalanced this month

    def set_log(self, lines):
        write_log(self.log_path, lines)

    def set_momo_state(self, last_rebalance):
        self.momo_state_path.write_text(json.dumps({'last_rebalance': last_rebalance}))

    def add_daily_universe_csv(self, symbol: str):
        self.daily_universe_dir.mkdir(parents=True, exist_ok=True)
        src = DAILY_UNIVERSE_SRC / f'{symbol}_day.csv'
        shutil.copy2(src, self.daily_universe_dir / f'{symbol}_day.csv')

    def write_daily_universe_bar(self, symbol: str, d: date, low: float, high: float):
        """Write a synthetic one-bar daily_universe CSV (same header/format as the
        real snapshot) giving P8 a known [low,high] for date `d`. Used instead of
        copying the committed snapshot when a scenario needs a candle dated TODAY:
        the real snapshot only extends to its last fetch, so a copy-based scenario
        silently no-ops (P8 skips fills whose day has no candle) the moment the
        wall-clock run date advances past the snapshot's final bar."""
        self.daily_universe_dir.mkdir(parents=True, exist_ok=True)
        mid = (low + high) / 2.0
        path = self.daily_universe_dir / f'{symbol}_day.csv'
        path.write_text(
            "datetime,open,high,low,close,volume,oi\n"
            f"{d.isoformat()} 00:00:00+05:30,{mid},{high},{low},{mid},1000,0\n",
            encoding='utf-8')

    def run(self, log_only=True):
        return run_parity(self.root, log_only=log_only)

    def cleanup(self):
        shutil.rmtree(self.root, ignore_errors=True)


# ---------------------------------------------------------------------------
# subprocess runner + output parser
# ---------------------------------------------------------------------------
def run_parity(kite_root: Path, log_only: bool = True):
    env = os.environ.copy()
    env['KITE_ROOT'] = str(kite_root)
    env['PARITY_LOG_ONLY'] = '1' if log_only else '0'
    # Hard-disable Telegram regardless of the real repo's .env (parity_monitor.py
    # loads _CODE_ROOT/.env with os.environ.setdefault -- pre-seeding these two
    # keys, even as empty strings, means setdefault is a no-op and TelegramBot
    # falls back to console-only mode. Without this, real credentials in the
    # checked-out .env would cause this test suite to send live Telegram
    # messages every run.)
    env['TELEGRAM_BOT_TOKEN'] = ''
    env['TELEGRAM_CHAT_ID'] = ''

    proc = subprocess.run(
        [sys.executable, str(PARITY_SCRIPT)],
        cwd=str(REPO_ROOT),
        env=env,
        capture_output=True,
        text=True,
        encoding='utf-8',
        errors='replace',
        timeout=120,
    )
    lines = proc.stdout.splitlines()
    json_start = next((i for i, ln in enumerate(lines) if ln.strip() == '{'), None)
    result = None
    if json_start is not None:
        try:
            result = json.loads('\n'.join(lines[json_start:]))
        except json.JSONDecodeError:
            result = None
    return proc, result


def find_check(result, check_id, name_substr=None):
    for c in result.get('per_check', []):
        if c['id'] == check_id and (name_substr is None or name_substr in c['name']):
            return c
    return None


def reds(result):
    return [c for c in result.get('per_check', []) if c['status'] == 'RED']


def fail(msg):
    raise AssertionError(msg)


def require(cond, msg):
    if not cond:
        fail(msg)


def require_result(proc, result):
    require(result is not None,
            f"could not parse JSON result from parity_monitor.py stdout "
            f"(exit={proc.returncode})\n--- stdout ---\n{proc.stdout}\n--- stderr ---\n{proc.stderr}")


# ---------------------------------------------------------------------------
# Scenario 1 -- CLEAN DAY (control)
# ---------------------------------------------------------------------------
def scenario_clean_day():
    fx = Fixture()
    try:
        # bb_mean_reversion: trades at ~the card's own rough-extrapolation rate,
        # spread across the full rolling-20-trading-day window used by P3, so
        # both the "10 trading days of live history" gate and the "within rough
        # band" classification are satisfied -- the intended GREEN contrast
        # against scenario 2's zero-trades RED.
        card = json.loads((EXPECTATIONS_SRC / 'bb_mean_reversion.json').read_text())
        lam = card['trades_per_month']['lambda']
        window_start = n_trading_days_ago(20)
        window_td = trading_days_between(window_start, TODAY)
        mu = lam * (window_td / 21.0)
        k = max(1, round(mu))
        days = trading_days_list(window_start, TODAY)
        for i in range(k):
            day = days[i % len(days)]
            ts = datetime.combine(day, time(9, 20)) + timedelta(minutes=(i // len(days)))
            insert_position(fx.incubator_db, symbol='RELIANCE', strategy='bb_mean_reversion',
                             entry_price=100.0, entry_time=ts, exit_price=100.5,
                             exit_time=ts + timedelta(minutes=5), pnl=50.0, pnl_pct=0.5,
                             status='closed', trade_mode='INTRADAY')

        # momo_rotation_63: a few plausible historical rotation trades (main book)
        for i, sym in enumerate(['TCS', 'INFY', 'HDFCBANK']):
            entry_d = n_trading_days_ago(90 - i * 5)
            exit_d = n_trading_days_ago(60 - i * 5)
            insert_position(fx.paper_db, symbol=sym, strategy='momo_rotation_63',
                             entry_price=1000.0, entry_time=datetime.combine(entry_d, time(9, 20)),
                             exit_price=1050.0, exit_time=datetime.combine(exit_d, time(15, 20)),
                             pnl=500.0, pnl_pct=5.0, status='closed', trade_mode='ROTATION')

        proc, result = fx.run()
        require_result(proc, result)

        require(not reds(result), f"expected no REDs on a clean day, got: {reds(result)}")
        p1 = find_check(result, 'P1')
        p2 = find_check(result, 'P2')
        require(p1 and p1['status'] == 'GREEN', f"P1 expected GREEN, got {p1}")
        require(p2 and p2['status'] == 'GREEN', f"P2 expected GREEN, got {p2}")
        return True, f"P1={p1['status']}, P2={p2['status']}, 0 REDs, overall={result['overall']}"
    finally:
        fx.cleanup()


# ---------------------------------------------------------------------------
# Scenario 2 -- ENUM-BUG SILENCE
# ---------------------------------------------------------------------------
def build_enum_bug_fixture():
    """Shared with scenario 9: bb_mean_reversion has exactly one trade, dated
    well outside the rolling-20-trading-day P3 window (so days_live >= 10 but
    k == 0 in-window) -- the enum-bug signature (signal detector silently
    firing zero trades while everything else looks healthy)."""
    fx = Fixture()
    old_day = n_trading_days_ago(25)
    insert_position(fx.incubator_db, symbol='RELIANCE', strategy='bb_mean_reversion',
                     entry_price=100.0, entry_time=datetime.combine(old_day, time(9, 20)),
                     exit_price=101.0, exit_time=datetime.combine(old_day, time(9, 30)),
                     pnl=100.0, pnl_pct=1.0, status='closed', trade_mode='INTRADAY')
    return fx


def scenario_enum_bug_silence():
    fx = build_enum_bug_fixture()
    try:
        proc, result = fx.run()
        require_result(proc, result)
        p3 = find_check(result, 'P3', 'bb_mean_reversion/intraday')
        require(p3 is not None, "no P3 check emitted for bb_mean_reversion/intraday")
        require(p3['status'] == 'RED', f"P3 expected RED (zero-vs-rough-mu), got {p3}")
        require('zero trades' in p3['detail'], f"expected zero-trades detail, got: {p3['detail']}")
        return True, f"P3 bb_mean_reversion = {p3['status']} ({p3['detail']})"
    finally:
        fx.cleanup()


# ---------------------------------------------------------------------------
# Scenario 3 -- DEAD MONITOR
# ---------------------------------------------------------------------------
def scenario_dead_monitor():
    fx = Fixture()
    try:
        yesterday = TODAY - timedelta(days=1)
        lines = healthy_lines(day=yesterday)  # log file is not empty/missing --
        # it just has nothing dated TODAY with the scan-cycle marker.
        lines.append(log_line(datetime.combine(TODAY, time(9, 0)), 'INFO',
                               "Initializing Live Monitor..."))
        fx.set_log(lines)

        proc, result = fx.run()
        require_result(proc, result)
        p1 = find_check(result, 'P1')
        require(p1 and p1['status'] == 'RED', f"P1 expected RED (dead monitor), got {p1}")
        return True, f"P1 = {p1['status']} ({p1['detail']})"
    finally:
        fx.cleanup()


# ---------------------------------------------------------------------------
# Scenario 4 -- DEAD TOKEN/DATA
# ---------------------------------------------------------------------------
def scenario_dead_token_data():
    fx = Fixture()
    try:
        fx.set_log(healthy_lines(daily_load=(0, 47)))
        proc, result = fx.run()
        require_result(proc, result)
        p2 = find_check(result, 'P2')
        require(p2 and p2['status'] == 'RED', f"P2 expected RED (0/47 loaded), got {p2}")
        return True, f"P2 = {p2['status']} ({p2['detail']})"
    finally:
        fx.cleanup()


# ---------------------------------------------------------------------------
# Scenario 5 -- LOGIN LOOP
# ---------------------------------------------------------------------------
def scenario_login_loop():
    fx = Fixture()
    try:
        fx.set_log(healthy_lines(n_login=15))
        proc, result = fx.run()
        require_result(proc, result)
        p9 = find_check(result, 'P9')
        require(p9 and p9['status'] == 'RED', f"P9 expected RED (15 logins), got {p9}")
        return True, f"P9 = {p9['status']} ({p9['detail']})"
    finally:
        fx.cleanup()


# ---------------------------------------------------------------------------
# Scenario 6 -- OVERNIGHT ORPHANS
# ---------------------------------------------------------------------------
def scenario_overnight_orphans():
    fx = Fixture()
    try:
        insert_position(fx.incubator_db, symbol='TCS', strategy='bb_mean_reversion',
                         entry_price=3500.0, entry_time=datetime.combine(TODAY, time(9, 20)),
                         status='open', trade_mode='INTRADAY')
        proc, result = fx.run()
        require_result(proc, result)
        p4 = find_check(result, 'P4')
        require(p4 and p4['status'] == 'RED', f"P4 expected RED (overnight orphan), got {p4}")
        require('open past close' in p4['detail'], f"expected square-off detail, got: {p4['detail']}")
        # First offense (no prior history entry) -- alert only, not a pause yet
        # (repeat-only escalation per spec 3.5 / parity_monitor.py check_p4).
        require(not result['paused_actions'],
                f"first-offense P4 RED should not pause yet, paused_actions={result['paused_actions']}")
        return True, f"P4 = {p4['status']} ({p4['detail']}); not yet paused (first offense)"
    finally:
        fx.cleanup()


# ---------------------------------------------------------------------------
# Scenario 7 -- MISSED REBALANCE
# ---------------------------------------------------------------------------
def scenario_missed_rebalance():
    fx = Fixture()
    try:
        last_month = (TODAY.replace(day=1) - timedelta(days=1)).strftime('%Y-%m')
        fx.set_momo_state(last_month)
        proc, result = fx.run()
        require_result(proc, result)
        p4 = find_check(result, 'P4')
        require(p4 and p4['status'] == 'RED', f"P4 expected RED (missed rebalance), got {p4}")
        require('NOT rebalanced this month' in p4['detail'], f"expected rebalance detail, got: {p4['detail']}")
        return True, f"P4 = {p4['status']} ({p4['detail']})"
    finally:
        fx.cleanup()


# ---------------------------------------------------------------------------
# Scenario 8 -- IMPOSSIBLE FILL
# ---------------------------------------------------------------------------
def scenario_impossible_fill():
    fx = Fixture()
    try:
        # Synthetic candles dated TODAY with known ranges -> deterministic
        # regardless of the committed snapshot's last bar or the run date. Each
        # entry@999999 sits far outside its bar's [low,high] = two impossible
        # fills -> P8 RED. (valid exit prices stay inside range so only entries
        # trip the check.)
        ranges = (('360ONE', 1080.0, 1135.0, 1120.0), ('3MINDIA', 34000.0, 36000.0, 35000.0))
        for sym, lo, hi, valid_exit in ranges:
            fx.write_daily_universe_bar(sym, TODAY, lo, hi)
            insert_position(fx.incubator_db, symbol=sym, strategy='cci_divergence',
                             entry_price=999999.0, entry_time=datetime.combine(TODAY, time(10, 0)),
                             exit_price=valid_exit, exit_time=datetime.combine(TODAY, time(14, 0)),
                             pnl=1.0, pnl_pct=0.0, status='closed', trade_mode='SWING')

        proc, result = fx.run()
        require_result(proc, result)
        p8 = find_check(result, 'P8')
        require(p8 and p8['status'] == 'RED', f"P8 expected RED (>=2 impossible fills), got {p8}")
        return True, f"P8 = {p8['status']} ({p8['detail']})"
    finally:
        fx.cleanup()


# ---------------------------------------------------------------------------
# Scenario 9 -- PAUSE ARMING (and no auto-unpause)
# ---------------------------------------------------------------------------
def scenario_pause_arming():
    fx = build_enum_bug_fixture()
    try:
        # Run 1: arm pause-writes on the enum-bug (P3 RED) fixture.
        proc1, result1 = fx.run(log_only=False)
        require_result(proc1, result1)
        p3_run1 = find_check(result1, 'P3', 'bb_mean_reversion/intraday')
        require(p3_run1 and p3_run1['status'] == 'RED',
                f"expected P3 RED on run 1 (enum-bug fixture), got {p3_run1}")

        require(fx.paused_path.exists(), "strategies_paused.json was not written with PARITY_LOG_ONLY=0")
        paused_after_run1 = json.loads(fx.paused_path.read_text())
        require('bb_mean_reversion' in paused_after_run1,
                f"expected bb_mean_reversion in strategies_paused.json, got {paused_after_run1}")

        # Run 2: same fixture dir, but now feed it clean scenario-1-style trade
        # data for bb_mean_reversion (rate back within the card's rough band).
        # The pre-existing (>20-trading-day-old) trade stays in the DB; we ADD
        # enough recent trades to bring k back within band -- P3 should clear.
        card = json.loads((EXPECTATIONS_SRC / 'bb_mean_reversion.json').read_text())
        lam = card['trades_per_month']['lambda']
        window_start = n_trading_days_ago(20)
        window_td = trading_days_between(window_start, TODAY)
        mu = lam * (window_td / 21.0)
        k = max(1, round(mu))
        days = trading_days_list(window_start, TODAY)
        for i in range(k):
            day = days[i % len(days)]
            ts = datetime.combine(day, time(9, 20)) + timedelta(minutes=(i // len(days)))
            insert_position(fx.incubator_db, symbol='RELIANCE', strategy='bb_mean_reversion',
                             entry_price=100.0, entry_time=ts, exit_price=100.5,
                             exit_time=ts + timedelta(minutes=5), pnl=50.0, pnl_pct=0.5,
                             status='closed', trade_mode='INTRADAY')

        proc2, result2 = fx.run(log_only=False)
        require_result(proc2, result2)
        p3_run2 = find_check(result2, 'P3', 'bb_mean_reversion/intraday')
        require(p3_run2 and p3_run2['status'] != 'RED',
                f"expected P3 no longer RED on run 2 (clean data fed in), got {p3_run2}")

        # The key assertion: strategies_paused.json is NOT auto-cleared just
        # because the underlying condition recovered -- per spec 3.5, unpause
        # is a human action only.
        require(fx.paused_path.exists(), "strategies_paused.json disappeared after run 2")
        paused_after_run2 = json.loads(fx.paused_path.read_text())
        require('bb_mean_reversion' in paused_after_run2,
                f"bb_mean_reversion was auto-cleared from strategies_paused.json "
                f"after recovery -- violates spec 3.5 no-auto-unpause rule. "
                f"Contents: {paused_after_run2}")

        return True, (f"run1 P3={p3_run1['status']} -> paused; "
                       f"run2 P3={p3_run2['status']} -> still paused (no auto-unpause)")
    finally:
        fx.cleanup()


# ---------------------------------------------------------------------------
# Scenario 10 -- CARD STALENESS (P13)
# ---------------------------------------------------------------------------
def scenario_card_staleness():
    """P13 must AMBER when a card's stamped code_hash no longer matches the
    current git hash of its strategy source.

    The two-root split is the whole point of this scenario. The fixture copies
    the REAL expectation cards into a temp KITE_ROOT and corrupts ONE card's
    code_hash to '0000000'. parity_monitor.py reads cards from KITE_ROOT (so it
    sees the corrupted fixture card), but check_p13 recomputes the source file's
    hash by running `git log` against _CODE_ROOT -- the real repo checkout,
    which KITE_ROOT never overrides. '0000000' is not a reachable commit, so it
    is guaranteed to mismatch the real repo hash -> AMBER. The other six cards
    keep their real (matching) hashes, so they stay silent and only the injected
    one is reported stale."""
    fx = Fixture()
    try:
        card_path = fx.expectations_dir / 'bb_mean_reversion.json'
        card = json.loads(card_path.read_text())
        card['code_hash'] = '0000000'
        card_path.write_text(json.dumps(card, indent=2))

        proc, result = fx.run()
        require_result(proc, result)
        p13 = find_check(result, 'P13')
        require(p13 is not None, "no P13 card-staleness check emitted")
        require(p13['status'] == 'AMBER',
                f"P13 expected AMBER (fake code_hash vs real repo hash), got {p13}")
        require('bb_mean_reversion' in p13['detail'] and '0000000' in p13['detail'],
                f"expected bb_mean_reversion/0000000 staleness in detail, got: {p13['detail']}")
        # Advisory only: staleness must never RED and never pause a strategy.
        require(p13['status'] != 'RED', "P13 must never be RED (staleness is advisory)")
        require('bb_mean_reversion' not in {a['strategy'] for a in result['paused_actions']},
                f"P13 staleness must not pause; paused_actions={result['paused_actions']}")
        return True, f"P13 = {p13['status']} ({p13['detail'][:90]})"
    finally:
        fx.cleanup()


# ---------------------------------------------------------------------------
# Scenario 11 -- HOLIDAY HANDLING (is_market_day + windowing helpers)
# ---------------------------------------------------------------------------
def scenario_holiday_handling():
    """Pure-function unit test of the NSE-holiday awareness. Mocking 'today' in
    the subprocess model is impractical, so this is the ONE scenario that imports
    parity_monitor.py directly and calls its date helpers -- KITE_ROOT is
    irrelevant for pure functions (they touch no data root). Asserts a known 2026
    weekday holiday is not a market day and that the window helpers skip it."""
    sys.path.insert(0, str(REPO_ROOT))
    import importlib
    pm = importlib.import_module('kite.live_monitor.parity_monitor')

    holiday = date(2026, 1, 26)  # Republic Day -- a Monday NSE holiday
    require(holiday.weekday() < 5, "sanity: Republic Day 2026 falls on a weekday")
    require(not pm.is_market_day(holiday),
            "Republic Day 2026-01-26 (a weekday) must NOT be a market day")
    require(pm.is_market_day(date(2026, 1, 27)),
            "2026-01-27 (ordinary Tuesday, not a holiday) should be a market day")

    # Inclusive span Fri 01-23 .. Wed 01-28 has 4 raw weekdays (23,26,27,28) but
    # 26 is the holiday -> trading_days_between must return 3.
    span = pm.trading_days_between(date(2026, 1, 23), date(2026, 1, 28))
    require(len(trading_days_list(date(2026, 1, 23), date(2026, 1, 28))) == 4,
            "span sanity: expected 4 raw weekdays in 01-23..01-28")
    require(span == 3,
            f"trading_days_between must skip Republic Day: expected 3, got {span}")

    # 1 trading day before Tue 01-27 is Fri 01-23 (skips holiday Mon 01-26 and
    # the 24/25 weekend).
    prev = pm._n_trading_days_ago(1, end=date(2026, 1, 27))
    require(prev == date(2026, 1, 23),
            f"_n_trading_days_ago(1) from 2026-01-27 should land on 2026-01-23, got {prev}")

    return True, ("is_market_day(2026-01-26 Republic Day)=False; "
                  "trading_days_between(01-23..01-28)=3 skips holiday; "
                  "_n_trading_days_ago(1 from 01-27)=2026-01-23")


# ---------------------------------------------------------------------------
# main
# ---------------------------------------------------------------------------
SCENARIOS = [
    ('1 CLEAN DAY (control)', scenario_clean_day),
    ('2 ENUM-BUG SILENCE', scenario_enum_bug_silence),
    ('3 DEAD MONITOR', scenario_dead_monitor),
    ('4 DEAD TOKEN/DATA', scenario_dead_token_data),
    ('5 LOGIN LOOP', scenario_login_loop),
    ('6 OVERNIGHT ORPHANS', scenario_overnight_orphans),
    ('7 MISSED REBALANCE', scenario_missed_rebalance),
    ('8 IMPOSSIBLE FILL', scenario_impossible_fill),
    ('9 PAUSE ARMING', scenario_pause_arming),
    ('10 CARD STALENESS', scenario_card_staleness),
    ('11 HOLIDAY HANDLING', scenario_holiday_handling),
]


def main():
    if not PARITY_SCRIPT.exists():
        print(f"FATAL: {PARITY_SCRIPT} not found")
        return 1
    if not is_market_day():
        print(f"WARNING: today ({TODAY}) is not a market day (weekend) -- "
              f"P1/P2/P9 will return NODATA regardless of log content, "
              f"and several scenario assertions below will legitimately FAIL. "
              f"Re-run on a weekday for a meaningful result.")

    rows = []
    for name, fn in SCENARIOS:
        try:
            passed, detail = fn()
            rows.append((name, 'PASS', detail))
        except AssertionError as e:
            rows.append((name, 'FAIL', str(e)))
        except Exception as e:
            rows.append((name, 'ERROR', f"{type(e).__name__}: {e}"))

    print()
    print("=" * 100)
    print(f"{'SCENARIO':<28} {'RESULT':<8} DETAIL")
    print("-" * 100)
    for name, status, detail in rows:
        detail_1line = detail.replace('\n', ' | ')
        if len(detail_1line) > 140:
            detail_1line = detail_1line[:137] + '...'
        print(f"{name:<28} {status:<8} {detail_1line}")
    print("=" * 100)

    n_fail = sum(1 for _, s, _ in rows if s != 'PASS')
    print(f"\n{len(rows) - n_fail}/{len(rows)} scenarios passed.")
    return 1 if n_fail else 0


if __name__ == '__main__':
    sys.exit(main())
