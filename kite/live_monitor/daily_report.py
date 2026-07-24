"""
Daily Report
============
End-of-day (16:30 IST Mon-Fri via systemd timer, after paper_trader's own EOD
square-off and parity_monitor's 16:15 run) Telegram report. Read-only,
best-effort narrative on top of the same data parity_monitor/dashboard.py
already read: what closed today, what's still open, gate/filter activity,
and the running scorecard since inception.

This is a REPORT, not a monitor -- it never writes anywhere, never pauses
anything, and its thresholds (if it had any) would not gate real decisions.
Its only job is to make today's trading day legible in one Telegram message.

Data sources (every one wrapped to degrade to 'n/a' rather than crash):
    data/paper_trades.db        (MAIN book positions/account -- paper_trader.py schema)
    data/incubator_trades.db    (INCUBATOR book, same schema)
    data/zerodha_data.db        (ohlcv, interval='minute' -> latest close for
                                  unrealized P&L; fails soft to entry price)
    data/monitor.log            (today's 'gate:' / 'entry-blocked' / 'AnnouncementFilter:' lines)
    kite/live_monitor/parity_history.jsonl  (last line only)

Side effects: exactly one Telegram send (possibly split into 2 messages if
the rendered report exceeds ~3800 chars), or a stdout print when
TELEGRAM_BOT_TOKEN/TELEGRAM_CHAT_ID are unset (TelegramBot's own fail-soft
behavior -- see telegram_bot.py).

Usage:
    python daily_report.py
    KITE_ROOT=/path/to/data-root python daily_report.py
"""
import sys
from pathlib import Path
import os

# ---------------------------------------------------------------------------
# root / .env (identical convention to parity_monitor.py / monitor.py) -- must
# happen before other kite imports so TELEGRAM_* env vars are in place.
#
# Two different "roots" on purpose:
#   _CODE_ROOT -- always where this file's repo checkout actually lives
#                 (Path(__file__)-derived, NEVER overridden). sys.path and the
#                 .env load use this.
#   ROOT       -- KITE_ROOT-overridable data root. Every data/output path
#                 below (DBs, log, history file) is relative to this one.
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

import html
import json
import sqlite3
import traceback
from datetime import datetime
from typing import Dict, List, Optional, Tuple

from kite.live_monitor.telegram_bot import TelegramBot

# Emoji/unicode-safe stdout (Windows consoles default to cp1252) -- best-effort.
try:
    sys.stdout.reconfigure(encoding='utf-8')
except (AttributeError, ValueError):
    pass

# ---------------------------------------------------------------------------
# paths / constants
# ---------------------------------------------------------------------------
MAIN_DB = ROOT / 'data' / 'paper_trades.db'
INCUBATOR_DB = ROOT / 'data' / 'incubator_trades.db'
ZERODHA_DB = ROOT / 'data' / 'zerodha_data.db'
MONITOR_LOG = ROOT / 'data' / 'monitor.log'
PARITY_HISTORY = ROOT / 'kite' / 'live_monitor' / 'parity_history.jsonl'

BOOKS: List[Tuple[str, Path]] = [('MAIN', MAIN_DB), ('INCUBATOR', INCUBATOR_DB)]

DASHBOARD_URL = 'http://80.225.202.32:8050'
LOG_TAIL_LINES = 5000
CLOSED_LINE_CAP = 20          # per book: show every line up to this many
MSG_SPLIT_LIMIT = 3800        # split into a 2nd Telegram message past this


# ---------------------------------------------------------------------------
# small generic helpers
# ---------------------------------------------------------------------------
def esc(v) -> str:
    """HTML-escape for parse_mode=HTML -- symbol/strategy/log text may in
    principle contain <, > or &."""
    return html.escape('' if v is None else str(v))


def money(v) -> str:
    if v is None:
        return 'n/a'
    try:
        return f"Rs {v:,.2f}"
    except (TypeError, ValueError):
        return 'n/a'


def signed_money(v) -> str:
    if v is None:
        return 'n/a'
    try:
        sign = '+' if v >= 0 else ''
        return f"{sign}{v:,.2f}"
    except (TypeError, ValueError):
        return 'n/a'


def hhmm(ts: Optional[str]) -> str:
    """'2026-07-24T15:20:01.02' -> '15:20'. Fails soft to a raw slice or n/a."""
    if not ts:
        return 'n/a'
    try:
        return datetime.fromisoformat(ts).strftime('%H:%M')
    except (TypeError, ValueError):
        return ts[11:16] if len(ts) >= 16 else 'n/a'


# ---------------------------------------------------------------------------
# DB access -- every helper fails soft (missing file/table -> [] / {} / None)
# ---------------------------------------------------------------------------
def _ro_conn(path: Path) -> Optional[sqlite3.Connection]:
    """Strictly read-only connection, or None if the file/open fails."""
    try:
        if not path.exists():
            return None
        conn = sqlite3.connect(f"file:{path}?mode=ro", uri=True)
        conn.row_factory = sqlite3.Row
        return conn
    except sqlite3.Error:
        return None


def _positions(conn: sqlite3.Connection, where: str = "", params: tuple = ()) -> List[dict]:
    try:
        rows = conn.execute(f"SELECT * FROM positions {where}", params).fetchall()
        return [dict(r) for r in rows]
    except sqlite3.OperationalError:
        return []


def _account(conn: sqlite3.Connection) -> dict:
    try:
        row = conn.execute("SELECT * FROM account ORDER BY id DESC LIMIT 1").fetchone()
        return dict(row) if row else {}
    except sqlite3.OperationalError:
        return {}


def _latest_close(conn: sqlite3.Connection, symbol: str) -> Optional[float]:
    """Latest 'minute' close for symbol from zerodha ohlcv, or None."""
    try:
        row = conn.execute(
            "SELECT close FROM ohlcv WHERE symbol=? AND interval='minute' "
            "ORDER BY datetime DESC LIMIT 1", (symbol,)
        ).fetchone()
        return row[0] if row else None
    except sqlite3.OperationalError:
        return None


def _unrealized(direction, entry, qty, current) -> Optional[float]:
    if current is None or entry is None or qty is None:
        return None
    try:
        if str(direction).upper() == 'SELL':
            return (entry - current) * qty
        return (current - entry) * qty
    except (TypeError, ValueError):
        return None


def gather_book(db_path: Path, today: str, zerodha_conn: Optional[sqlite3.Connection]) -> dict:
    """One book's full state for the report. Every field degrades to
    None/[]/False rather than raising -- a missing DB (e.g. incubator hasn't
    traded yet) must never crash the whole report."""
    book = {
        'available': False,
        'capital': None,
        'closed_today': [],
        'open': [],
        'today_realized': None,
        'all_time_realized': None,
        'all_time_closed': 0,
        'all_time_wins': 0,
    }
    conn = _ro_conn(db_path)
    if conn is None:
        return book
    book['available'] = True
    try:
        acct = _account(conn)
        book['capital'] = acct.get('capital')

        closed_today = _positions(conn, "WHERE status='closed' AND substr(exit_time,1,10)=?", (today,))
        book['closed_today'] = closed_today
        book['today_realized'] = sum((r.get('pnl') or 0) for r in closed_today)

        all_closed = _positions(conn, "WHERE status='closed'")
        book['all_time_closed'] = len(all_closed)
        book['all_time_realized'] = sum((r.get('pnl') or 0) for r in all_closed)
        book['all_time_wins'] = sum(1 for r in all_closed if (r.get('pnl') or 0) > 0)

        book['open'] = _positions(conn, "WHERE status='open'")
    finally:
        try:
            conn.close()
        except sqlite3.Error:
            pass

    # Enrich open positions with a current price + unrealized P&L. Fail-soft
    # per the spec: if zerodha_data.db/ohlcv has nothing for this symbol,
    # fall back to entry price (unrealized reads as 0 rather than crashing).
    for p in book['open']:
        cur = _latest_close(zerodha_conn, p.get('symbol')) if zerodha_conn is not None else None
        if cur is None:
            cur = p.get('entry_price')
        p['current'] = cur
        p['unrealized'] = _unrealized(p.get('direction'), p.get('entry_price'), p.get('quantity'), cur)

    return book


# ---------------------------------------------------------------------------
# monitor.log (gates + ann-filter) -- same tail/todays_lines convention as
# parity_monitor.py, duplicated here on purpose (this script is standalone).
# ---------------------------------------------------------------------------
def read_log_tail(path: Path, n: int = LOG_TAIL_LINES) -> List[str]:
    if not path.exists():
        return []
    try:
        with open(path, encoding='utf-8', errors='replace') as f:
            lines = f.readlines()
        return lines[-n:]
    except OSError:
        return []


def todays_lines(lines: List[str], marker: str, today: str) -> List[str]:
    return [ln for ln in lines if ln[:10] == today and marker in ln]


def gate_breakdown(gate_lines: List[str]) -> Dict[str, int]:
    """entry_pipeline.py's three gate reasons, by substring of its own log
    text (see entry_pipeline.py try_enter): cutoff / paused / red-flag."""
    cutoff = sum(1 for ln in gate_lines if 'entry cutoff' in ln)
    paused = sum(1 for ln in gate_lines if 'strategy paused' in ln)
    redflag = sum(1 for ln in gate_lines if 'red flag' in ln)
    other = len(gate_lines) - cutoff - paused - redflag
    return {'cutoff': cutoff, 'paused': paused, 'redflag': redflag, 'other': max(other, 0)}


def last_ann_filter_line(lines: List[str]) -> Optional[str]:
    """Last 'AnnouncementFilter:' line in the tail, not restricted to today
    (mirrors dashboard.py's read_announcement_flags -- the status line is a
    heartbeat, useful even if it's from a prior day)."""
    for ln in reversed(lines):
        if 'AnnouncementFilter:' in ln:
            return ln.strip()
    return None


# ---------------------------------------------------------------------------
# parity_history.jsonl -- last line only
# ---------------------------------------------------------------------------
def read_last_parity(path: Path) -> Optional[dict]:
    if not path.exists():
        return None
    try:
        with open(path, encoding='utf-8', errors='replace') as f:
            lines = f.readlines()
    except OSError:
        return None
    for ln in reversed(lines):
        ln = ln.strip()
        if not ln:
            continue
        try:
            return json.loads(ln)
        except ValueError:
            return None
    return None


# ---------------------------------------------------------------------------
# section builders (each returns one already-<b>-headed block of text)
# ---------------------------------------------------------------------------
def format_closed_line(r: dict) -> str:
    entry, exitp = r.get('entry_price'), r.get('exit_price')
    price_txt = f"{entry:.2f}→{exitp:.2f}" if entry is not None and exitp is not None else 'n/a'
    qty = r.get('quantity')
    return (f"{hhmm(r.get('exit_time'))} {esc(r.get('symbol') or '?')} "
            f"{esc(r.get('direction') or '?')} x{qty if qty is not None else '?'} "
            f"{price_txt} {signed_money(r.get('pnl'))} "
            f"({esc(r.get('exit_reason') or '?')}) [{esc(r.get('strategy') or '?')}]")


def render_closed_section(closed: List[dict]) -> List[str]:
    if not closed:
        return ["Closed today: none"]
    if len(closed) <= CLOSED_LINE_CAP:
        ordered = sorted(closed, key=lambda r: r.get('exit_time') or '')
        return [f"Closed today ({len(closed)}):"] + [format_closed_line(r) for r in ordered]
    winners = sorted(closed, key=lambda r: (r.get('pnl') or 0), reverse=True)[:5]
    losers = sorted(closed, key=lambda r: (r.get('pnl') or 0))[:5]
    out = [f"Closed today: {len(closed)} trades (showing top 5 winners / top 5 losers)", "Winners:"]
    out += [format_closed_line(r) for r in winners]
    out.append("Losers:")
    out += [format_closed_line(r) for r in losers]
    return out


def render_open_section(open_rows: List[dict]) -> List[str]:
    if not open_rows:
        return ["Open: none"]
    lines = [f"Open ({len(open_rows)}):"]
    have_any_unreal = False
    total_unreal = 0.0
    for p in open_rows:
        entry, cur = p.get('entry_price'), p.get('current')
        unreal = p.get('unrealized')
        if unreal is not None:
            total_unreal += unreal
            have_any_unreal = True
        if entry is not None and cur is not None:
            lines.append(f"  {esc(p.get('symbol') or '?')} {esc(p.get('direction') or '?')} "
                         f"x{p.get('quantity')} entry {entry:.2f} cur {cur:.2f} "
                         f"unreal {signed_money(unreal)}")
        else:
            lines.append(f"  {esc(p.get('symbol') or '?')} {esc(p.get('direction') or '?')} "
                         f"x{p.get('quantity')} (price n/a)")
    lines.append(f"Total unrealized: {signed_money(total_unreal if have_any_unreal else None)}")
    return lines


def render_book_section(label: str, book: dict) -> str:
    if not book['available']:
        return f"<b>{esc(label)} book</b>\ndatabase unavailable — n/a"
    lines = [f"<b>{esc(label)} book</b>"]
    lines += render_closed_section(book['closed_today'])
    lines.append(f"Realized today: {signed_money(book['today_realized'])}")
    lines += render_open_section(book['open'])
    lines.append(f"Capital: {money(book['capital'])}")
    return "\n".join(lines)


def render_strategy_section(books: List[Tuple[str, dict]]) -> str:
    stats: Dict[Tuple[str, str], dict] = {}
    for label, book in books:
        for r in book.get('closed_today', []):
            key = (r.get('strategy') or 'unknown', label)
            st = stats.setdefault(key, {'trades': 0, 'pnl': 0.0, 'wins': 0, 'losses': 0})
            st['trades'] += 1
            pnl = r.get('pnl') or 0
            st['pnl'] += pnl
            if pnl > 0:
                st['wins'] += 1
            elif pnl < 0:
                st['losses'] += 1

    lines = ["<b>Per-strategy today</b>"]
    if not stats:
        lines.append("No trades closed today.")
        return "\n".join(lines)
    for (strategy, label), st in sorted(stats.items(), key=lambda kv: (kv[0][1], kv[0][0])):
        lines.append(f"{esc(strategy)} [{esc(label)}]: {st['trades']} trades, "
                     f"{signed_money(st['pnl'])}, {st['wins']}W/{st['losses']}L")
    return "\n".join(lines)


def render_gates_section(log_lines: List[str], today: str) -> str:
    gate_lines = todays_lines(log_lines, 'gate:', today)
    blocked_lines = todays_lines(log_lines, 'entry-blocked', today)
    bd = gate_breakdown(gate_lines)
    ann_line = last_ann_filter_line(log_lines)

    lines = ["<b>Gates</b>"]
    breakdown_txt = f"cutoff {bd['cutoff']}, paused {bd['paused']}, red-flag {bd['redflag']}"
    if bd['other']:
        breakdown_txt += f", other {bd['other']}"
    lines.append(f"Entries blocked (gate:): {len(gate_lines)} ({breakdown_txt})")
    lines.append(f"Rotation ann-filter blocks (entry-blocked): {len(blocked_lines)} line(s) today")
    lines.append(f"Ann-filter status: {esc(ann_line) if ann_line else 'n/a'}")
    return "\n".join(lines)


def render_parity_section(parity: Optional[dict]) -> str:
    lines = ["<b>Parity</b>"]
    if not parity:
        lines.append("n/a (no parity_history.jsonl entry)")
        return "\n".join(lines)
    overall = parity.get('overall', '?')
    ts = parity.get('ts')
    ts_txt = hhmm(ts) if ts else '?'
    try:
        date_txt = ts.split('T')[0] if ts else '?'
    except (AttributeError, IndexError):
        date_txt = '?'
    lines.append(f"Overall: {esc(overall)} (as of {esc(date_txt)} {esc(ts_txt)})")
    non_green = [c for c in (parity.get('per_check') or []) if c.get('status') != 'GREEN']
    if non_green:
        for c in non_green:
            lines.append(f"- {esc(c.get('id', '?'))} {esc(c.get('name', ''))}: "
                         f"{esc(c.get('status', '?'))} — {esc(c.get('detail', ''))}")
    else:
        lines.append("All checks green.")
    return "\n".join(lines)


def render_inception_section(books: List[Tuple[str, dict]]) -> str:
    lines = ["<b>Since inception</b>"]
    combined = 0.0
    have_any = False
    all_available = True
    for label, book in books:
        if not book['available']:
            lines.append(f"{esc(label)}: unavailable — n/a")
            all_available = False
            continue
        closed_n = book['all_time_closed']
        realized = book['all_time_realized']
        wins = book['all_time_wins']
        wr_txt = f"{(wins / closed_n * 100):.1f}% win rate" if closed_n else "n/a (0 closed trades)"
        lines.append(f"{esc(label)}: {money(realized)} realized, {closed_n} closed trades, {wr_txt}")
        if realized is not None:
            combined += realized
            have_any = True
    combined_txt = money(combined if have_any else None)
    if not all_available:
        combined_txt += " (partial — some books unavailable)"
    lines.append(f"Combined: {combined_txt}")
    return "\n".join(lines)


# ---------------------------------------------------------------------------
# message assembly / splitting
# ---------------------------------------------------------------------------
def chunk_sections(sections: List[str], limit: int = MSG_SPLIT_LIMIT) -> List[str]:
    """Greedy-pack sections into <=limit-char chunks, splitting only at
    section boundaries (never mid-section)."""
    chunks: List[str] = []
    current: List[str] = []
    current_len = 0
    for sec in sections:
        add_len = len(sec) + (2 if current else 0)  # '\n\n' join cost
        if current and current_len + add_len > limit:
            chunks.append("\n\n".join(current))
            current, current_len = [sec], len(sec)
        else:
            current.append(sec)
            current_len += add_len
    if current:
        chunks.append("\n\n".join(current))
    return chunks


def build_report() -> List[str]:
    today = datetime.now().strftime('%Y-%m-%d')

    zerodha_conn = _ro_conn(ZERODHA_DB)
    try:
        books = [(label, gather_book(path, today, zerodha_conn)) for label, path in BOOKS]
    finally:
        if zerodha_conn is not None:
            try:
                zerodha_conn.close()
            except sqlite3.Error:
                pass

    log_lines = read_log_tail(MONITOR_LOG)
    parity = read_last_parity(PARITY_HISTORY)

    sections = [f"<b>DAY REPORT — {today}</b>"]
    sections += [render_book_section(label, book) for label, book in books]
    sections.append(render_strategy_section(books))
    sections.append(render_gates_section(log_lines, today))
    sections.append(render_parity_section(parity))
    sections.append(render_inception_section(books))
    sections.append(f"Dashboard: {DASHBOARD_URL}")

    return chunk_sections(sections)


# ---------------------------------------------------------------------------
# send / main
# ---------------------------------------------------------------------------
def _send(chunks: List[str]):
    token = os.environ.get('TELEGRAM_BOT_TOKEN')
    chat = os.environ.get('TELEGRAM_CHAT_ID')
    bot = TelegramBot(token, chat)
    for chunk in chunks:
        bot.send_message(chunk)


def main():
    # Top-level try/except: ANY internal exception must still produce one
    # loud line, never a silent cron failure. Mirrors parity_monitor.py.
    try:
        chunks = build_report()
    except Exception as e:
        traceback.print_exc()
        message = f"DAY REPORT failed: {e}"
        _send([message])
        print(message)
        return

    _send(chunks)
    for i, chunk in enumerate(chunks):
        if len(chunks) > 1:
            print(f"--- message {i + 1}/{len(chunks)} ---")
        print(chunk)


if __name__ == '__main__':
    main()
