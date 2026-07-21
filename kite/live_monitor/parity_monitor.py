"""
Parity Monitor
==============
Nightly (16:15 IST Mon-Fri via systemd timer) pure-arithmetic health check.
Compares each live strategy's actual behavior against its frozen Expectation
Book (kite/live_monitor/expectations/<strategy>.json) and reports GREEN /
AMBER / RED. No AI anywhere in this file — a smoke detector must be
deterministic.

Spec (frozen thresholds, sections 3.2-3.5, 5):
    docs/superpowers/specs/2026-07-21-parity-monitor-design.md
Do not change any AMBER/RED threshold without a dated decision-log entry
in that file (section 6, amendment rule).

Side effects (and only these): one Telegram line, one append to
parity_history.jsonl, and (unless PARITY_LOG_ONLY) writes to
data/strategies_paused.json on a pausing RED. Never touches orders/exits.

Usage:
    python parity_monitor.py
    PARITY_LOG_ONLY=0 python parity_monitor.py   # arm pause-writes (after the soak week)
"""
import sys
from pathlib import Path
import os

# ---------------------------------------------------------------------------
# root / .env (same convention as monitor.py) -- must happen before other
# kite imports so TELEGRAM_* env vars are in place.
#
# Two different "roots" on purpose:
#   _CODE_ROOT -- always where this file's repo checkout actually lives
#                 (Path(__file__)-derived, NEVER overridden). sys.path and the
#                 .env load use this -- the `kite` package and credentials
#                 live with the code, regardless of where data is read from.
#   ROOT       -- KITE_ROOT-overridable data root. Every data/output path
#                 below (DBs, expectations, log, state files) is relative to
#                 this one, so a differently-laid-out deployment (or a test
#                 fixture) can point the monitor at its own data/ tree without
#                 needing a second copy of the code.
# ---------------------------------------------------------------------------
_CODE_ROOT = Path(__file__).resolve().parents[2]
ROOT = Path(os.environ.get('KITE_ROOT', str(_CODE_ROOT)))
sys.path.insert(0, str(_CODE_ROOT))

_env_file = _CODE_ROOT / '.env'
if _env_file.exists():
    with open(_env_file) as _f:
        for _line in _f:
            _line = _line.strip()
            if _line and not _line.startswith('#') and '=' in _line:
                _key, _, _val = _line.partition('=')
                _val = _val.strip()
                if _val.startswith(('"', "'")) and _val.endswith(_val[0]):
                    _val = _val[1:-1]
                else:
                    _val = _val.split('#')[0].strip()
                os.environ.setdefault(_key.strip(), _val)

import json
import re
import sqlite3
import traceback
from collections import Counter
from datetime import datetime, date, timedelta
from typing import Dict, List, Optional, Tuple

from scipy import stats

from kite.live_monitor.telegram_bot import TelegramBot

# Emoji-safe stdout (Windows consoles default to cp1252, which chokes on the
# stethoscope emoji below) -- best-effort, never fatal.
try:
    sys.stdout.reconfigure(encoding='utf-8')
except (AttributeError, ValueError):
    pass

# ---------------------------------------------------------------------------
# paths
# ---------------------------------------------------------------------------
PAPER_DB = ROOT / 'data' / 'paper_trades.db'
INCUBATOR_DB = ROOT / 'data' / 'incubator_trades.db'
EXPECTATIONS_DIR = ROOT / 'kite' / 'live_monitor' / 'expectations'
MONITOR_LOG = ROOT / 'data' / 'monitor.log'
MOMO_STATE_FILE = ROOT / 'data' / 'momo_rotation_state.json'
PAUSED_FILE = ROOT / 'data' / 'strategies_paused.json'
HISTORY_FILE = ROOT / 'kite' / 'live_monitor' / 'parity_history.jsonl'
DAILY_UNIVERSE_DIR = ROOT / 'data' / 'daily_universe'

LOG_TAIL_LINES = 5000
INITIAL_CAPITAL = 100_000.0

# Soak mode: compute + report, never write strategies_paused.json.
# Default ON (per build-plan step 4: dry-run week before REDs can pause).
PARITY_LOG_ONLY = os.environ.get('PARITY_LOG_ONLY', '1') not in ('0', 'false', 'False', 'no', 'NO')

# Live strategy roster: (strategy, book, trade_mode) -- mirrors monitor.py's
# INTRADAY_STRATEGIES/INCUBATOR_STRATEGIES/SWING_CANDIDATES + momo_rotation_63.
# 'book' selects which sqlite DB holds that strategy's trades.
# NOTE: cci_divergence is run twice live (5-min incubator AND daily-bar swing
# candidate) with the SAME strategy name -- trade_mode is what disambiguates
# them in the DB. See "Ambiguities" in the implementation report.
BOOKS: Dict[str, Path] = {'main': PAPER_DB, 'incubator': INCUBATOR_DB}
STRATEGIES: List[Tuple[str, str, str]] = [
    ('momo_rotation_63', 'main', 'ROTATION'),
    ('rsi_trend_confirmation', 'incubator', 'ROTATION'),
    ('cci_divergence', 'incubator', 'ROTATION'),       # swing-candidate incarnation
    ('choppiness_filter', 'incubator', 'INTRADAY'),
    ('cci_divergence', 'incubator', 'INTRADAY'),       # incubator (5-min) incarnation
    ('bb_mean_reversion', 'incubator', 'INTRADAY'),
    ('adx_filter', 'incubator', 'INTRADAY'),
]
# P3 (trade-rate) is explicitly "intraday/swing strategies only" per spec table 3.3 --
# momo_rotation_63 is monthly cadence and is covered by P4 (cadence) instead.
MONTHLY_STRATEGIES = {'momo_rotation_63'}

STATUS_RANK = {'GREEN': 0, 'AMBER': 1, 'RED': 2}


# ---------------------------------------------------------------------------
# small generic helpers
# ---------------------------------------------------------------------------
def is_market_day(d: Optional[date] = None) -> bool:
    """Mon-Fri. No NSE holiday calendar available -- see report ambiguities."""
    d = d or datetime.now().date()
    return d.weekday() < 5


def trading_days_between(start: date, end: date) -> int:
    """Weekday count from start to end inclusive (approximates trading days)."""
    if start > end:
        return 0
    d, count = start, 0
    while d <= end:
        if d.weekday() < 5:
            count += 1
        d += timedelta(days=1)
    return count


def _n_trading_days_ago(n: int, end: Optional[date] = None) -> date:
    end = end or datetime.now().date()
    d, count = end, 0
    while count < n:
        d -= timedelta(days=1)
        if d.weekday() < 5:
            count += 1
    return d


def read_log_tail(n: int = LOG_TAIL_LINES) -> List[str]:
    if not MONITOR_LOG.exists():
        return []
    with open(MONITOR_LOG, encoding='utf-8', errors='replace') as f:
        lines = f.readlines()
    return lines[-n:]


def todays_lines(lines: List[str], marker: str) -> List[str]:
    """Lines whose leading YYYY-MM-DD matches today and that contain marker."""
    today = datetime.now().strftime('%Y-%m-%d')
    return [ln for ln in lines if ln[:10] == today and marker in ln]


def _parse_int(pattern: str, text: Optional[str], default: int = 0) -> int:
    if not text:
        return default
    m = re.search(pattern, text)
    return int(m.group(1)) if m else default


# ---------------------------------------------------------------------------
# DB access (tolerant of missing files/tables -- both DBs may not exist yet)
# ---------------------------------------------------------------------------
def _rows(db_path: Path, where: str = "", params: tuple = ()) -> List[sqlite3.Row]:
    if not db_path.exists():
        return []
    try:
        conn = sqlite3.connect(str(db_path))
        conn.row_factory = sqlite3.Row
        cur = conn.cursor()
        cur.execute(f"SELECT * FROM positions {where}", params)
        rows = cur.fetchall()
        conn.close()
        return rows
    except sqlite3.OperationalError:
        return []


def book_rows(book: str, status: Optional[str] = None) -> List[sqlite3.Row]:
    db_path = BOOKS[book]
    if status:
        return _rows(db_path, "WHERE status = ?", (status,))
    return _rows(db_path)


def strategy_rows(book: str, strategy: str, trade_mode: str,
                   status: Optional[str] = None) -> List[sqlite3.Row]:
    where = "WHERE strategy = ? AND trade_mode = ?"
    params: list = [strategy, trade_mode]
    if status:
        where += " AND status = ?"
        params.append(status)
    return _rows(BOOKS[book], where, tuple(params))


# ---------------------------------------------------------------------------
# expectation cards (may not exist yet -- degrade gracefully)
# ---------------------------------------------------------------------------
# gen_expectations.py (kite/live_monitor/gen_expectations.py) files cards under
# <strategy>.json per spec §3.1, EXCEPT cci_divergence's intraday (5-min
# incubator) incarnation, which it files under the synthetic card name
# "cci_divergence_intraday.json" to disambiguate it from the daily-swing
# cci_divergence card -- the live DB still stores both under strategy=
# 'cci_divergence' (trade_mode is what distinguishes them there).
CARD_NAME_OVERRIDES = {
    ('cci_divergence', 'INTRADAY'): 'cci_divergence_intraday',
}


def load_card(strategy: str, trade_mode: str) -> Optional[dict]:
    card_name = CARD_NAME_OVERRIDES.get((strategy, trade_mode), strategy)
    p = EXPECTATIONS_DIR / f"{card_name}.json"
    if not p.exists():
        return None
    try:
        return json.loads(p.read_text())
    except (OSError, ValueError):
        return None


# ---------------------------------------------------------------------------
# parity_history.jsonl (append-only run log; also our cross-run state store)
# ---------------------------------------------------------------------------
def read_history(n: int = 60) -> List[dict]:
    if not HISTORY_FILE.exists():
        return []
    out = []
    with open(HISTORY_FILE, encoding='utf-8', errors='replace') as f:
        lines = f.readlines()
    for ln in lines[-n:]:
        ln = ln.strip()
        if not ln:
            continue
        try:
            out.append(json.loads(ln))
        except ValueError:
            continue
    return out


def last_check_status(history: List[dict], check_id: str) -> Optional[str]:
    for entry in reversed(history):
        for chk in entry.get('per_check', []):
            if chk.get('id') == check_id:
                return chk.get('status')
    return None


def last_check_detail(history: List[dict], check_id: str) -> Optional[str]:
    for entry in reversed(history):
        for chk in entry.get('per_check', []):
            if chk.get('id') == check_id:
                return chk.get('detail')
    return None


def _consecutive_failed_days(history: List[dict], check_id: str) -> int:
    """Count immediately-preceding runs whose check was AMBER/RED, stopping at
    the first GREEN. NODATA/WARMING_UP runs (weekends, etc.) are skipped."""
    streak = 0
    for entry in reversed(history):
        chk = next((c for c in entry.get('per_check', []) if c.get('id') == check_id), None)
        if chk is None:
            continue
        if chk['status'] in ('AMBER', 'RED'):
            streak += 1
        elif chk['status'] == 'GREEN':
            break
    return streak


# ---------------------------------------------------------------------------
# P1 -- Liveness
# ---------------------------------------------------------------------------
def check_p1(log_lines: List[str]) -> dict:
    if not is_market_day():
        return {'id': 'P1', 'name': 'liveness', 'status': 'NODATA', 'detail': 'weekend'}
    count = len(todays_lines(log_lines, '--- Scan cycle starting'))
    if count == 0:
        return {'id': 'P1', 'name': 'liveness', 'status': 'RED',
                'detail': 'zero scan cycles logged today -- monitor may be dead'}
    return {'id': 'P1', 'name': 'liveness', 'status': 'GREEN',
            'detail': f'{count} scan cycles logged today'}


# ---------------------------------------------------------------------------
# P2 -- Data freshness
# ---------------------------------------------------------------------------
def check_p2(log_lines: List[str]) -> dict:
    if not is_market_day():
        return {'id': 'P2', 'name': 'data-freshness', 'status': 'NODATA', 'detail': 'weekend'}
    matches = todays_lines(log_lines, 'Daily data loaded for')
    if not matches:
        return {'id': 'P2', 'name': 'data-freshness', 'status': 'AMBER',
                'detail': 'no "Daily data loaded" line today (swing scan may not have run yet)'}
    m = re.search(r'Daily data loaded for (\d+)/(\d+) stocks', matches[-1])
    if not m:
        return {'id': 'P2', 'name': 'data-freshness', 'status': 'AMBER',
                'detail': 'unparseable daily-load line'}
    x, y = int(m.group(1)), int(m.group(2))
    pct = (x / y) if y else 0.0
    detail = f'{x}/{y} stocks ({pct:.0%})'
    if pct < 0.5:
        return {'id': 'P2', 'name': 'data-freshness', 'status': 'RED', 'detail': detail}
    if pct < 0.9:
        return {'id': 'P2', 'name': 'data-freshness', 'status': 'AMBER', 'detail': detail}
    return {'id': 'P2', 'name': 'data-freshness', 'status': 'GREEN', 'detail': detail}


# ---------------------------------------------------------------------------
# P3 -- Trade rate (Poisson two-tail, per strategy, intraday/swing only)
# ---------------------------------------------------------------------------
def check_p3(strategy: str, book: str, trade_mode: str, card: Optional[dict]) -> Optional[dict]:
    cadence = card.get('cadence') if card else None
    if cadence == 'monthly' or (cadence is None and strategy in MONTHLY_STRATEGIES):
        return None  # monthly cadence -- not applicable, covered by P4 instead
    name = f'trade-rate ({strategy}/{trade_mode.lower()})'
    if card is None:
        return {'id': 'P3', 'name': name, 'status': 'AMBER', 'detail': f'no expectation card for {strategy}'}
    lam_month = card.get('trades_per_month', {}).get('lambda')
    if lam_month is None:
        return {'id': 'P3', 'name': name, 'status': 'AMBER', 'detail': 'card missing trades_per_month.lambda'}

    all_rows = strategy_rows(book, strategy, trade_mode)
    if not all_rows:
        return {'id': 'P3', 'name': name, 'status': 'WARMING_UP', 'detail': '0/10 trading days of live history'}
    first_dt = min(datetime.fromisoformat(r['entry_time']) for r in all_rows)
    days_live = trading_days_between(first_dt.date(), datetime.now().date())
    if days_live < 10:
        return {'id': 'P3', 'name': name, 'status': 'WARMING_UP',
                'detail': f'{days_live}/10 trading days of live history'}

    window_start = _n_trading_days_ago(20)
    window_td = trading_days_between(window_start, datetime.now().date())
    k = sum(1 for r in all_rows if datetime.fromisoformat(r['entry_time']).date() >= window_start)
    mu = lam_month * (window_td / 21.0)

    # Rough-extrapolation lambdas (intraday cards built from a 5-day/5-stock audit
    # sample) are order-of-magnitude estimates -- a precise Poisson test would
    # false-RED immediately. Degrade to silence/explosion detection only: the bug
    # signatures we actually hunt (enum-bug zero-trades, runaway loops).
    if card.get('trades_per_month', {}).get('lambda_quality') == 'rough-extrapolation' \
            or card.get('lambda_quality') == 'rough-extrapolation':
        if k == 0 and mu >= 10:
            status, why = 'RED', 'zero trades despite rough-expected activity'
        elif k > 0 and (k < mu / 5 or k > mu * 5):
            status, why = 'AMBER', 'rate >5x off rough estimate'
        else:
            status, why = 'GREEN', 'within rough band'
        detail = f'k={k} in {window_td}td vs rough mu={mu:.0f} ({why})'
        return {'id': 'P3', 'name': name, 'status': status, 'detail': detail}

    p = 2 * min(stats.poisson.cdf(k, mu), stats.poisson.sf(k - 1, mu))
    p = min(p, 1.0)
    detail = f'k={k} trades in {window_td}td window vs mu={mu:.2f}, p={p:.3f}'
    status = 'RED' if p < 0.01 else ('AMBER' if p < 0.05 else 'GREEN')
    return {'id': 'P3', 'name': name, 'status': status, 'detail': detail}


# ---------------------------------------------------------------------------
# P4 -- Cadence events (momo rebalance timing + EOD intraday square-off)
# ---------------------------------------------------------------------------
def check_p4(history: List[dict]) -> Tuple[dict, bool]:
    name = 'cadence (momo rebalance + EOD square-off)'
    today = datetime.now().date()

    try:
        momo_state = json.loads(MOMO_STATE_FILE.read_text())
    except (OSError, ValueError):
        momo_state = {}
    last_rebalance = momo_state.get('last_rebalance')
    cur_month = today.strftime('%Y-%m')
    trading_day_idx = trading_days_between(today.replace(day=1), today)
    rebalance_violated = trading_day_idx > 3 and last_rebalance != cur_month
    rebalance_detail = (f'rebalance ok (last={last_rebalance})' if not rebalance_violated
                         else f'NOT rebalanced this month (last={last_rebalance}, '
                              f'trading-day {trading_day_idx} of month)')

    open_intraday = [r for b in BOOKS for r in book_rows(b, status='open') if r['trade_mode'] == 'INTRADAY']
    squareoff_violated = len(open_intraday) > 0
    squareoff_detail = ('EOD square-off ok' if not squareoff_violated
                         else f'{len(open_intraday)} INTRADAY position(s) open past close: '
                              + ', '.join(sorted(r['symbol'] for r in open_intraday)))

    violated = rebalance_violated or squareoff_violated
    detail = f'{rebalance_detail} | {squareoff_detail}'
    if not violated:
        return {'id': 'P4', 'name': name, 'status': 'GREEN', 'detail': detail}, False

    is_repeat = last_check_status(history, 'P4') == 'RED'
    return {'id': 'P4', 'name': name, 'status': 'RED', 'detail': detail}, is_repeat


# ---------------------------------------------------------------------------
# P5 -- Win rate (two-proportion z-test, per strategy, N>=60 closed)
# ---------------------------------------------------------------------------
def check_p5(strategy: str, book: str, trade_mode: str, card: Optional[dict]) -> Optional[dict]:
    name = f'win-rate ({strategy}/{trade_mode.lower()})'
    if card is None:
        return {'id': 'P5', 'name': name, 'status': 'AMBER', 'detail': f'no expectation card for {strategy}'}
    wr = card.get('win_rate')
    if wr is None:
        # gen_expectations.py deliberately omits win_rate for cadences whose source
        # CSV carries no win-rate column (e.g. cadence=intraday) -- not a data gap,
        # a documented "not applicable" contract. Skip, don't flag.
        return None
    p_card, n_bt = wr.get('p'), wr.get('n_backtest')
    if p_card is None or not n_bt:
        return {'id': 'P5', 'name': name, 'status': 'AMBER', 'detail': 'card win_rate present but malformed'}

    closed = strategy_rows(book, strategy, trade_mode, status='closed')
    n_live = len(closed)
    if n_live < 60:
        return {'id': 'P5', 'name': name, 'status': 'WARMING_UP', 'detail': f'{n_live}/60 closed trades'}

    wins = sum(1 for r in closed if (r['pnl'] or 0) > 0)
    p_live = wins / n_live
    p_pool = (wins + p_card * n_bt) / (n_live + n_bt)
    se = (p_pool * (1 - p_pool) * (1 / n_live + 1 / n_bt)) ** 0.5
    z = (p_live - p_card) / se if se else 0.0
    p_value = 2 * stats.norm.sf(abs(z))
    detail = f'live {wins}/{n_live}={p_live:.1%} vs card {p_card:.1%} (n_bt={n_bt}), p={p_value:.3f}'
    status = 'RED' if p_value < 0.01 else ('AMBER' if p_value < 0.05 else 'GREEN')
    return {'id': 'P5', 'name': name, 'status': status, 'detail': detail}


# ---------------------------------------------------------------------------
# P6 -- Drawdown (per book; equity curve from closed pnl cumulative + 100000)
# ---------------------------------------------------------------------------
def check_p6(book: str, cards_by_book: Dict[str, List[dict]]) -> dict:
    name = f'drawdown ({book})'
    all_rows = book_rows(book)
    if not all_rows:
        return {'id': 'P6', 'name': name, 'status': 'WARMING_UP',
                'detail': '0/20 trading days of live history (no trades yet)'}

    first_dt = min(datetime.fromisoformat(r['entry_time']) for r in all_rows)
    days_live = trading_days_between(first_dt.date(), datetime.now().date())
    if days_live < 20:
        return {'id': 'P6', 'name': name, 'status': 'WARMING_UP',
                'detail': f'{days_live}/20 trading days of live history'}

    closed = [r for r in all_rows if r['status'] == 'closed']
    if not closed:
        return {'id': 'P6', 'name': name, 'status': 'WARMING_UP',
                'detail': f'{days_live}/20 trading days live, but 0 closed trades yet'}

    ordered = sorted(closed, key=lambda r: r['exit_time'] or '')
    equity = peak = INITIAL_CAPITAL
    max_dd = 0.0
    for r in ordered:
        equity += (r['pnl'] or 0)
        peak = max(peak, equity)
        if peak:
            max_dd = min(max_dd, (equity - peak) / peak * 100)

    card_dds = [c['max_drawdown_pct'] for c in cards_by_book.get(book, [])
                if c.get('max_drawdown_pct') is not None]
    if not card_dds:
        return {'id': 'P6', 'name': name, 'status': 'AMBER',
                'detail': f'no card for {book} book -- live max DD {max_dd:.1f}%'}
    # Most permissive (largest-magnitude) threshold among strategies sharing this book.
    card_dd = min(card_dds)
    ratio = abs(max_dd) / abs(card_dd) if card_dd else float('inf')
    detail = f'live max DD {max_dd:.1f}% vs card {card_dd:.1f}% (ratio {ratio:.2f}x)'
    status = 'RED' if ratio > 2.0 else ('AMBER' if ratio > 1.5 else 'GREEN')
    return {'id': 'P6', 'name': name, 'status': status, 'detail': detail}


# ---------------------------------------------------------------------------
# P7 -- Hold time (live p50 vs card p95, amber only, per strategy)
# ---------------------------------------------------------------------------
def check_p7(strategy: str, book: str, trade_mode: str, card: Optional[dict]) -> dict:
    name = f'hold-time ({strategy}/{trade_mode.lower()})'
    if card is None:
        return {'id': 'P7', 'name': name, 'status': 'AMBER', 'detail': f'no expectation card for {strategy}'}
    p95 = card.get('hold_days', {}).get('p95')
    if p95 is None:
        return {'id': 'P7', 'name': name, 'status': 'AMBER', 'detail': 'card missing hold_days.p95'}

    closed = strategy_rows(book, strategy, trade_mode, status='closed')
    holds = []
    for r in closed:
        try:
            holds.append((datetime.fromisoformat(r['exit_time']) -
                           datetime.fromisoformat(r['entry_time'])).total_seconds() / 86400.0)
        except (TypeError, ValueError):
            continue
    if not holds:
        return {'id': 'P7', 'name': name, 'status': 'NODATA', 'detail': 'no closed trades yet'}

    holds.sort()
    mid = len(holds) // 2
    p50 = holds[mid] if len(holds) % 2 else (holds[mid - 1] + holds[mid]) / 2
    detail = f'live p50 hold {p50:.1f}d vs card p95 {p95:.1f}d'
    status = 'AMBER' if p50 > p95 else 'GREEN'
    return {'id': 'P7', 'name': name, 'status': status, 'detail': detail}


# ---------------------------------------------------------------------------
# P8 -- Slippage/fill sanity (fill outside day's [low,high]; rolling 7-day count)
# ---------------------------------------------------------------------------
_csv_cache: Dict[str, object] = {}


def _day_range(symbol: str, d: date) -> Tuple[Optional[float], Optional[float]]:
    if symbol not in _csv_cache:
        path = DAILY_UNIVERSE_DIR / f'{symbol}_day.csv'
        if not path.exists():
            _csv_cache[symbol] = None
        else:
            import pandas as pd
            try:
                df = pd.read_csv(path, parse_dates=['datetime'])
                df['_date'] = df['datetime'].dt.date
                _csv_cache[symbol] = df.set_index('_date')[['low', 'high']]
            except Exception:
                _csv_cache[symbol] = None
    tbl = _csv_cache[symbol]
    if tbl is None or d not in tbl.index:
        return None, None
    row = tbl.loc[d]
    return float(row['low']), float(row['high'])


def check_p8() -> Tuple[dict, set]:
    name = 'fill-sanity'
    since = datetime.now().date() - timedelta(days=7)
    events = []
    offenders: set = set()

    for book in BOOKS:
        for r in book_rows(book):
            for ts_col, price_col, label in (('entry_time', 'entry_price', 'entry'),
                                              ('exit_time', 'exit_price', 'exit')):
                ts, price = r[ts_col], r[price_col]
                if not ts or price is None:
                    continue
                try:
                    dt = datetime.fromisoformat(ts)
                except ValueError:
                    continue
                if dt.date() < since:
                    continue
                lo, hi = _day_range(r['symbol'], dt.date())
                if lo is None:  # file absent or date missing -- skip this fill's check
                    continue
                if price < lo or price > hi:
                    events.append(f"{r['strategy']}/{r['symbol']} {label}@{price:.2f} "
                                  f"not in [{lo:.2f},{hi:.2f}] on {dt.date()}")
                    offenders.add(r['strategy'])

    n = len(events)
    detail = f'{n} fill(s) outside day range in trailing 7 days'
    if events:
        detail += ': ' + '; '.join(events[:5])
    status = 'RED' if n >= 2 else ('AMBER' if n == 1 else 'GREEN')
    return {'id': 'P8', 'name': name, 'status': status, 'detail': detail}, offenders


# ---------------------------------------------------------------------------
# P9 -- Auth events
# ---------------------------------------------------------------------------
def check_p9(log_lines: List[str]) -> dict:
    if not is_market_day():
        return {'id': 'P9', 'name': 'auth-events', 'status': 'NODATA', 'detail': 'weekend'}
    count = (len(todays_lines(log_lines, 'Login successful'))
             + len(todays_lines(log_lines, 'Token refreshed successfully')))
    detail = f'{count} login/refresh events today'
    status = 'RED' if count > 10 else ('AMBER' if count > 3 else 'GREEN')
    return {'id': 'P9', 'name': 'auth-events', 'status': status, 'detail': detail}


# ---------------------------------------------------------------------------
# P10 -- Ann-filter refresh failures (consecutive days)
# ---------------------------------------------------------------------------
def check_p10(log_lines: List[str], history: List[dict]) -> dict:
    name = 'ann-filter-refresh'
    success_today = any('announcements scanned' in ln for ln in todays_lines(log_lines, 'AnnouncementFilter:'))
    fail_today = bool(todays_lines(log_lines, 'refresh failed'))
    if not success_today and not fail_today:
        return {'id': 'P10', 'name': name, 'status': 'NODATA', 'detail': 'no ann-filter activity logged today'}
    if success_today:
        return {'id': 'P10', 'name': name, 'status': 'GREEN', 'detail': 'refresh succeeded today'}
    streak = _consecutive_failed_days(history, 'P10') + 1
    status = 'RED' if streak >= 3 else 'AMBER'
    return {'id': 'P10', 'name': name, 'status': status,
            'detail': f'refresh failed today (consecutive fail streak {streak})'}


# ---------------------------------------------------------------------------
# P11 -- Ann-filter category drift (0 red-flags for 15 consecutive market days)
# ---------------------------------------------------------------------------
def check_p11(log_lines: List[str], history: List[dict]) -> dict:
    name = 'ann-filter-category-drift'
    matches = todays_lines(log_lines, 'AnnouncementFilter:')
    m = None
    for ln in reversed(matches):
        mm = re.search(r'AnnouncementFilter: (\d+) announcements scanned, (\d+) symbols red-flagged', ln)
        if mm:
            m = mm
            break
    if m is None:
        return {'id': 'P11', 'name': name, 'status': 'NODATA', 'detail': 'no ann-filter scan logged today'}

    flagged = int(m.group(2))
    prev_streak = _parse_int(r'zero-streak=(\d+)', last_check_detail(history, 'P11'), default=0)
    streak = 0 if flagged > 0 else prev_streak + 1
    detail = f'{flagged} symbols red-flagged today (zero-streak={streak}/15)'
    status = 'RED' if streak >= 15 else 'GREEN'
    return {'id': 'P11', 'name': name, 'status': status, 'detail': detail}


# ---------------------------------------------------------------------------
# P12 -- Parity dead-man (gap since last parity_history.jsonl entry)
# ---------------------------------------------------------------------------
def check_p12(history: List[dict]) -> dict:
    name = 'parity-deadman'
    if not history:
        return {'id': 'P12', 'name': name, 'status': 'NODATA', 'detail': 'no prior history entry -- first run'}
    try:
        last_dt = datetime.fromisoformat(history[-1]['ts'])
    except (KeyError, TypeError, ValueError):
        return {'id': 'P12', 'name': name, 'status': 'AMBER', 'detail': 'prior entry has unparseable timestamp'}
    gap = trading_days_between(last_dt.date() + timedelta(days=1), datetime.now().date())
    detail = f'last parity run {last_dt.date()} ({gap} market day(s) since, incl. today)'
    status = 'RED' if gap > 1 else 'GREEN'
    return {'id': 'P12', 'name': name, 'status': status, 'detail': detail}


# ---------------------------------------------------------------------------
# pause mechanics (§3.5)
# ---------------------------------------------------------------------------
def apply_pauses(pause_requests: Dict[str, str]) -> List[dict]:
    if not pause_requests:
        return []
    try:
        existing = json.loads(PAUSED_FILE.read_text()) if PAUSED_FILE.exists() else {}
    except (OSError, ValueError):
        existing = {}

    actions = []
    changed = False
    today_str = datetime.now().strftime('%Y-%m-%d')
    for strategy, reason in pause_requests.items():
        already = strategy in existing
        actions.append({'strategy': strategy, 'reason': reason, 'already_paused': already,
                         'written': (not PARITY_LOG_ONLY) and not already})
        if not already:
            existing[strategy] = {'reason': reason, 'since': today_str}
            changed = True

    if changed and not PARITY_LOG_ONLY:
        PAUSED_FILE.parent.mkdir(parents=True, exist_ok=True)
        PAUSED_FILE.write_text(json.dumps(existing, indent=2))
    return actions


# ---------------------------------------------------------------------------
# main run
# ---------------------------------------------------------------------------
def run() -> dict:
    ts = datetime.now().isoformat()
    log_lines = read_log_tail()
    history = read_history()

    per_check: List[dict] = []
    pause_requests: Dict[str, str] = {}

    # -- system-level checks --
    per_check.append(check_p1(log_lines))
    per_check.append(check_p2(log_lines))

    p4_check, p4_repeat = check_p4(history)
    per_check.append(p4_check)
    if p4_check['status'] == 'RED' and p4_repeat:
        pause_requests['momo_rotation_63'] = f"P4 cadence violation (repeat): {p4_check['detail']}"

    p8_check, p8_offenders = check_p8()
    per_check.append(p8_check)
    if p8_check['status'] == 'RED':
        for s in p8_offenders:
            pause_requests[s] = f"P8 fill-sanity: {p8_check['detail']}"

    per_check.append(check_p9(log_lines))
    per_check.append(check_p10(log_lines, history))
    per_check.append(check_p11(log_lines, history))
    per_check.append(check_p12(history))

    # -- expectation cards --
    cards: Dict[Tuple[str, str, str], Optional[dict]] = {}
    cards_by_book: Dict[str, List[dict]] = {b: [] for b in BOOKS}
    for (strategy, book, trade_mode) in STRATEGIES:
        card = load_card(strategy, trade_mode)
        cards[(strategy, book, trade_mode)] = card
        if card is not None:
            cards_by_book[book].append(card)

    # -- per-strategy checks: P3, P5, P7 --
    for (strategy, book, trade_mode) in STRATEGIES:
        card = cards[(strategy, book, trade_mode)]

        p3 = check_p3(strategy, book, trade_mode, card)
        if p3 is not None:
            per_check.append(p3)
            if p3['status'] == 'RED':
                pause_requests[strategy] = f"P3 trade-rate: {p3['detail']}"

        p5 = check_p5(strategy, book, trade_mode, card)
        if p5 is not None:
            per_check.append(p5)
            if p5['status'] == 'RED':
                pause_requests[strategy] = f"P5 win-rate: {p5['detail']}"

        per_check.append(check_p7(strategy, book, trade_mode, card))  # amber-only, never pauses

    # -- per-book check: P6 --
    for book in BOOKS:
        p6 = check_p6(book, cards_by_book)
        per_check.append(p6)
        if p6['status'] == 'RED':
            for (strategy, b, _tm) in STRATEGIES:
                if b == book:
                    pause_requests[strategy] = f"P6 drawdown ({book} book): {p6['detail']}"

    paused_actions = apply_pauses(pause_requests)

    colored = [c['status'] for c in per_check if c['status'] in STATUS_RANK]
    overall = max(colored, key=lambda s: STATUS_RANK[s]) if colored else 'GREEN'

    return {'ts': ts, 'overall': overall, 'per_check': per_check, 'paused_actions': paused_actions}


def append_history(result: dict):
    HISTORY_FILE.parent.mkdir(parents=True, exist_ok=True)
    with open(HISTORY_FILE, 'a', encoding='utf-8') as f:
        f.write(json.dumps(result) + '\n')


def build_message(result: dict) -> str:
    """Format per spec §3.4: one line, always. AMBERs -> count only. REDs -> detail + action."""
    per_check = result['per_check']
    by_id: Dict[str, List[dict]] = {}
    for c in per_check:
        by_id.setdefault(c['id'], []).append(c)

    name_counts = Counter(s for s, _b, _tm in STRATEGIES)
    strategy_units = []  # (label, worst_status_or_None, red_detail)
    for (strategy, book, trade_mode) in STRATEGIES:
        label = strategy if name_counts[strategy] == 1 else f'{strategy}[{trade_mode}]'
        relevant = [c for c in per_check
                    if f'({strategy}/{trade_mode.lower()})' in c['name']]
        book_check = next((c for c in by_id.get('P6', []) if c['name'] == f'drawdown ({book})'), None)
        statuses = [c['status'] for c in relevant]
        if book_check:
            statuses.append(book_check['status'])
        colored = [s for s in statuses if s in STATUS_RANK]
        worst = max(colored, key=lambda s: STATUS_RANK[s]) if colored else None
        red_bits = [c['detail'] for c in relevant if c['status'] == 'RED']
        if book_check and book_check['status'] == 'RED':
            red_bits.append(book_check['detail'])
        strategy_units.append((label, worst, '; '.join(red_bits)))

    system_ids = ['P1', 'P2', 'P4', 'P9', 'P10', 'P11', 'P12']
    system_units = [(f"{cid} {c['name']}", c['status'], c['detail'])
                     for cid in system_ids for c in by_id.get(cid, [])]

    all_units = [(lbl, st, det) for lbl, st, det in strategy_units if st is not None] + \
                [(lbl, st, det) for lbl, st, det in system_units if st in STATUS_RANK]

    green_n = sum(1 for _l, st, _d in all_units if st == 'GREEN')
    amber_n = sum(1 for _l, st, _d in all_units if st == 'AMBER')
    red_units = [(lbl, det) for lbl, st, det in all_units if st == 'RED']

    if red_units:
        red_parts = [f"RED {lbl} ({det})" if det else f"RED {lbl}" for lbl, det in red_units]
        paused_names = sorted({a['strategy'] for a in result['paused_actions']})
        if paused_names:
            verb = 'would pause' if PARITY_LOG_ONLY else 'entries paused'
            action = f"{verb}: {', '.join(paused_names)}"
        else:
            action = 'alert only, nothing to pause'
        tail = f"{green_n} green" + (f", {amber_n} amber" if amber_n else "")
        msg = f"\U0001fa7a parity: {'; '.join(red_parts)} — {action}; {tail}"
    else:
        tail = f"{green_n} strategies green" if not amber_n else f"{green_n} green, {amber_n} amber"
        msg = f"\U0001fa7a parity: {tail}"

    if PARITY_LOG_ONLY:
        msg += " [log-only]"
    return msg


def main():
    # Top-level try/except per spec §5.6: ANY internal exception must fail loud
    # via the one Telegram line, never fail silent. Deliberately does not
    # re-raise -- the Telegram message IS the loud failure signal here.
    try:
        result = run()
        append_history(result)
        message = build_message(result)
    except Exception as e:
        traceback.print_exc()
        message = f"\U0001fa7a parity INTERNAL ERROR: {e}"
        try:
            append_history({'ts': datetime.now().isoformat(), 'overall': 'ERROR',
                             'per_check': [], 'paused_actions': [], 'error': str(e)})
        except Exception:
            pass
        _send(message)
        print(message)
        return

    _send(message)
    print(message)
    print(json.dumps(result, indent=2, default=str))


def _send(message: str):
    token = os.environ.get('TELEGRAM_BOT_TOKEN')
    chat = os.environ.get('TELEGRAM_CHAT_ID')
    bot = TelegramBot(token, chat)
    bot.send_message(message)


if __name__ == '__main__':
    main()
