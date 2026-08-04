"""
Report Positions
================
Read-only CLI report: today's closed trades (both books), open positions
with SL/TP, and live marks with unrealized P&L for open positions.

Replaces the reviewer's ad-hoc /tmp/pnl.py + /tmp/mark.py with one script.

CRITICAL SAFETY RULE
---------------------
Live quotes are fetched by reusing an EXISTING session token, read from
ZERODHA_ENCTOKEN (env/.env) or, failing that, repo-root enctoken.txt -- the
file the monitor persists at every login/refresh (and daily_collector.py's
long-standing token file).
This script NEVER imports or calls zerodha_auto_login.get_enctoken /
LiveMonitor._auto_login. A fresh TOTP login invalidates the currently running
monitor's Kite session (Zerodha allows one active web session per enctoken).

Marking has three tiers, in order, and each is tagged loudly so a reader can
never mistake one for another:
  1. Live quote (/oms/quote, batched) -- tag: [LIVE], no note.
  2. Chart fallback -- added 2026-08-04 because Zerodha's /oms/quote now 400s
     unconditionally for enctoken sessions (verified dead that day) while the
     chart/history endpoint (same token) still works. Same-token reuse, same
     safety rule -- still never a login. Tag: [CHART], note shows the bar:
         (chart 1-min close: <timestamp>)
  3. Stale DB mark -- if the token is missing/stale and both of the above
     fail, falls back to the newest available bar in data/zerodha_data.db for
     that symbol. Tag: [STALE], note:
         (stale DB mark: <timestamp>)
It never attempts to log in, refresh, or persist a token.

This report NEVER writes to any DB, never refreshes a token, never sends
Telegram. All DB connections are opened read-only (file:...?mode=ro).

Usage:
    python report_positions.py                    # today (IST), live quotes if token set
    python report_positions.py --date 2026-07-30   # a specific day's closed trades
    python report_positions.py --offline           # skip the live-quote attempt entirely
                                                     # (forces the stale-DB-mark fallback --
                                                     #  useful to demo/verify that path)
    KITE_ROOT=/path/to/data-root python report_positions.py

Data sources:
    data/paper_trades.db        MAIN book (paper_trader.py schema)
    data/incubator_trades.db    INCUBATOR book (same schema)
    data/zerodha_data.db        ohlcv, interval='minute' -> stale-mark fallback
"""
import sys
from pathlib import Path
import os

# ---------------------------------------------------------------------------
# root / .env -- identical convention to daily_report.py / parity_monitor.py /
# monitor.py. Must happen before other kite imports so ZERODHA_ENCTOKEN (if
# set in .env) is in place before we touch the data fetcher.
#
# Two different "roots" on purpose:
#   _CODE_ROOT -- always where this file's repo checkout actually lives
#                 (Path(__file__)-derived, NEVER overridden). sys.path and the
#                 .env load use this -- the `kite` package and credentials
#                 live with the code, regardless of where data is read from.
#   ROOT       -- KITE_ROOT-overridable data root. Every DB path below is
#                 relative to this one, so a differently-laid-out deployment
#                 (or a local self-test against a scratch data/ tree) can
#                 point this script at its own data without a second code copy.
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
                    _val = _val[1:-1]  # strip surrounding quotes
                else:
                    _val = _val.split('#')[0].strip()  # strip inline comments
                os.environ.setdefault(_key.strip(), _val)

import argparse
import sqlite3
import traceback
from datetime import datetime
from typing import Dict, List, Optional, Tuple

from kite.live_monitor.data_fetcher import ZerodhaDataFetcher

# Emoji/unicode-safe stdout (Windows consoles default to cp1252) -- best-effort,
# same as daily_report.py / parity_monitor.py.
try:
    sys.stdout.reconfigure(encoding='utf-8')
except (AttributeError, ValueError):
    pass

# ---------------------------------------------------------------------------
# paths
# ---------------------------------------------------------------------------
MAIN_DB = ROOT / 'data' / 'paper_trades.db'
INCUBATOR_DB = ROOT / 'data' / 'incubator_trades.db'
ZERODHA_DB = ROOT / 'data' / 'zerodha_data.db'

BOOKS: List[Tuple[str, Path]] = [('MAIN', MAIN_DB), ('INCUBATOR', INCUBATOR_DB)]


# ---------------------------------------------------------------------------
# small generic helpers (money/time formatting -- same style as daily_report.py)
# ---------------------------------------------------------------------------
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
    if not ts:
        return 'n/a'
    try:
        return datetime.fromisoformat(ts).strftime('%H:%M')
    except (TypeError, ValueError):
        return ts[11:16] if len(ts) >= 16 else 'n/a'


def today_ist() -> str:
    """'Today' for the --date default. Every other live_monitor script
    (monitor.py's is_market_hours(), etc.) compares datetime.now() directly
    against IST wall-clock times with no tz conversion -- the deployment box's
    system clock is assumed to already be Asia/Kolkata. Matched here rather
    than introducing a second, inconsistent notion of 'today'."""
    return datetime.now().strftime('%Y-%m-%d')


def _valid_date(s: str) -> str:
    try:
        datetime.strptime(s, '%Y-%m-%d')
    except ValueError:
        raise argparse.ArgumentTypeError(f"{s!r} is not YYYY-MM-DD")
    return s


# ---------------------------------------------------------------------------
# DB access -- every helper fails soft (missing file/table -> [] / {} / None).
# Read-only URI connections only; this script must never be able to write.
# ---------------------------------------------------------------------------
def _ro_conn(path: Path) -> Optional[sqlite3.Connection]:
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


def _latest_bar(conn: sqlite3.Connection, symbol: str) -> Optional[Tuple[float, str]]:
    """(close, datetime) of the newest 'minute' bar for symbol, or None."""
    try:
        row = conn.execute(
            "SELECT close, datetime FROM ohlcv WHERE symbol=? AND interval='minute' "
            "ORDER BY datetime DESC LIMIT 1", (symbol,)
        ).fetchone()
        return (row[0], row[1]) if row else None
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


# ---------------------------------------------------------------------------
# per-book gather
# ---------------------------------------------------------------------------
def gather_book(db_path: Path, date_str: str) -> dict:
    """One book's raw state -- closed trades on date_str, open positions, and
    lifetime counts. Every field degrades to a safe empty value on any read
    failure (missing DB, missing table, corrupt row) rather than raising --
    a report tool must never crash because one book hasn't traded yet."""
    book = {
        'available': False,
        'capital': None,
        'closed': [],
        'open': [],
        'lifetime_closed': 0,
        'lifetime_wins': 0,
        'lifetime_realized': None,
    }
    conn = _ro_conn(db_path)
    if conn is None:
        return book
    book['available'] = True
    try:
        book['capital'] = _account(conn).get('capital')
        book['closed'] = _positions(
            conn, "WHERE status='closed' AND substr(exit_time,1,10)=? ORDER BY exit_time", (date_str,))
        book['open'] = _positions(conn, "WHERE status='open' ORDER BY entry_time")

        all_closed = _positions(conn, "WHERE status='closed'")
        book['lifetime_closed'] = len(all_closed)
        book['lifetime_wins'] = sum(1 for r in all_closed if (r.get('pnl') or 0) > 0)
        book['lifetime_realized'] = sum((r.get('pnl') or 0) for r in all_closed)
    finally:
        try:
            conn.close()
        except sqlite3.Error:
            pass
    return book


# ---------------------------------------------------------------------------
# live quote fetch (the safety-critical part) + stale-DB fallback marking
# ---------------------------------------------------------------------------
def fetch_live_quotes(symbols: List[str], offline: bool) -> Tuple[Dict[str, dict], str]:
    """ONE batched call for every open symbol across both books -- data_fetcher's
    get_quote() already builds a single HTTP request with multiple 'i=NSE:SYM'
    params, so there is no per-symbol looping/pacing to do here (the ~0.3s
    pacing the build brief anticipates would only matter for a fetcher that
    required one call per symbol; this one doesn't).

    Returns (quotes, status). status is one of:
      'offline'        --offline was passed; live quotes never attempted
      'no-symbols'     nothing open to quote
      'no-token'       ZERODHA_ENCTOKEN unset/blank AND repo-root enctoken.txt
                        missing/empty -- get_quote() would just
                        warn-and-return-{} anyway; we skip constructing the
                        fetcher (and its instrument-list network call) entirely
      'quote-failed'   token present but neither the batched quote call nor
                        the per-symbol chart fallback (below) produced anything
                        (expired token, network error, HTTP failure -- all of
                        which get_quote()/get_historical_data() already
                        swallow internally)
      'chart'          the batched /oms/quote call returned nothing (as of
                        2026-08-04 it 400s unconditionally for enctoken
                        sessions -- dead), but the chart/history endpoint
                        (same token, still alive) produced a last-minute
                        close for at least one symbol
      'live'           at least one symbol came back with a live price
    """
    if offline:
        return {}, 'offline'
    if not symbols:
        return {}, 'no-symbols'

    # Token sources, in order: ZERODHA_ENCTOKEN from env/.env, then repo-root
    # enctoken.txt (the file the monitor persists at login/refresh, and the
    # same file daily_collector.py already reads -- gitignored, chmod 600).
    # Both are read-only reuse of an EXISTING session: this script still never
    # attempts a login of its own.
    token = os.environ.get('ZERODHA_ENCTOKEN', '').strip()
    if not token:
        try:
            _tf = _CODE_ROOT / 'enctoken.txt'
            token = _tf.read_text().strip() if _tf.exists() else ''
        except OSError:
            token = ''
    if not token:
        return {}, 'no-token'

    try:
        fetcher = ZerodhaDataFetcher(token)
        quotes = fetcher.get_quote(symbols)
    except Exception as e:
        print(f"WARNING: live quote fetch raised {e!r} -- falling back to stale DB marks",
              file=sys.stderr)
        quotes = {}
        fetcher = None

    if quotes:
        return quotes, 'live'

    # Middle fallback tier (added 2026-08-04): Zerodha's /oms/quote endpoint now
    # 400s unconditionally for enctoken-based sessions -- dead. The chart/history
    # endpoint still works off the same token (it's how the live monitor itself
    # prices everything), so try that next, one symbol at a time, before giving
    # up to the stale-DB fallback below. days=5 (not 1) so a pre-market or
    # post-holiday run still finds the last session's bars. Per-symbol
    # try/except so one bad instrument can't take the rest down with it.
    if fetcher is None:
        return {}, 'quote-failed'

    chart_quotes: Dict[str, dict] = {}
    for symbol in symbols:
        try:
            df = fetcher.get_historical_data(symbol, interval="minute", days=5)
        except Exception as e:
            print(f"WARNING: chart-fallback fetch raised {e!r} for {symbol} -- skipping",
                  file=sys.stderr)
            continue
        if df is None or len(df) == 0:
            continue
        last_bar = df.iloc[-1]
        chart_quotes[symbol] = {
            'last_price': float(last_bar['close']),
            'timestamp': df.index[-1],
            'source': 'chart',  # loud tag: mark_open_positions/render use this to
                                 # label these 'CHART', never silently as 'LIVE'
        }

    if chart_quotes:
        return chart_quotes, 'chart'
    return {}, 'quote-failed'


def mark_open_positions(open_rows: List[dict], quotes: Dict[str, dict],
                         zerodha_conn: Optional[sqlite3.Connection]) -> None:
    """Mutates each row in place: mark_price, mark_source ('LIVE'/'CHART'/'STALE'/'NONE'),
    mark_note (the chart-fallback bar timestamp, the loud stale-DB tag, or
    '(no mark available)'), unrealized.

    'CHART' marks (quotes dict entries carrying 'source': 'chart', set by
    fetch_live_quotes' chart fallback) are deliberately never relabeled 'LIVE' --
    this project treats silently-wrong-looking-right data as the worst failure
    mode, so a last-minute chart close must stay visibly distinct from a true
    live tick even though both come from the same 'quotes' dict."""
    for row in open_rows:
        symbol = row.get('symbol')
        q = quotes.get(symbol) if quotes else None
        live_price = q.get('last_price') if q else None
        if live_price and q.get('source') == 'chart':
            row['mark_price'] = live_price
            row['mark_source'] = 'CHART'
            ts = q.get('timestamp')
            ts_txt = ts.strftime('%Y-%m-%d %H:%M') if hasattr(ts, 'strftime') else str(ts)
            row['mark_note'] = f"(chart 1-min close: {ts_txt})"
        elif live_price:
            row['mark_price'] = live_price
            row['mark_source'] = 'LIVE'
            row['mark_note'] = ''
        else:
            bar = _latest_bar(zerodha_conn, symbol) if zerodha_conn is not None else None
            if bar is not None:
                price, ts = bar
                row['mark_price'] = price
                row['mark_source'] = 'STALE'
                row['mark_note'] = f"(stale DB mark: {ts})"
            else:
                row['mark_price'] = None
                row['mark_source'] = 'NONE'
                row['mark_note'] = '(no mark available)'
        row['unrealized'] = _unrealized(row.get('direction'), row.get('entry_price'),
                                         row.get('quantity'), row.get('mark_price'))


# ---------------------------------------------------------------------------
# rendering (plain text -- this is a terminal report, not a Telegram message)
# ---------------------------------------------------------------------------
def render_closed(closed: List[dict]) -> List[str]:
    if not closed:
        return ["Closed today: none"]
    lines = [f"Closed today ({len(closed)}):"]
    tot_gross = tot_charges = tot_net = 0.0
    for r in closed:
        entry, exitp = r.get('entry_price'), r.get('exit_price')
        price_txt = f"{entry:.2f}->{exitp:.2f}" if entry is not None and exitp is not None else 'n/a'
        symbol_txt = str(r.get('symbol') or '?')
        direction_txt = str(r.get('direction') or '?')
        qty = r.get('quantity')
        qty_txt = str(qty) if qty is not None else '?'
        gross = r.get('gross_pnl') or 0.0
        charges = r.get('charges') or 0.0
        net = r.get('pnl') or 0.0
        tot_gross += gross
        tot_charges += charges
        tot_net += net
        lines.append(
            f"  {hhmm(r.get('exit_time'))} {symbol_txt:<12} "
            f"{direction_txt:<4} x{qty_txt:<5} "
            f"{price_txt:<18} gross {signed_money(gross):>10}  charges -{charges:,.2f}  "
            f"net {signed_money(net):>10}  ({r.get('exit_reason') or '?'}) [{r.get('strategy') or '?'}]"
        )
    lines.append(f"  TOTALS: gross {signed_money(tot_gross)}  charges -{tot_charges:,.2f}  "
                 f"net {signed_money(tot_net)}  ({len(closed)} trade(s))")
    return lines


def render_open(open_rows: List[dict]) -> List[str]:
    if not open_rows:
        return ["Open: none"]
    lines = [f"Open ({len(open_rows)}):"]
    total_unreal = 0.0
    have_any_unreal = False
    for p in open_rows:
        entry = p.get('entry_price')
        sl, tp = p.get('stop_loss'), p.get('take_profit')
        trail = p.get('trailing_stop')
        eff_sl_txt = f" eff-SL {trail:.2f}" if trail is not None and trail != sl else ""
        mark = p.get('mark_price')
        unreal = p.get('unrealized')
        if unreal is not None:
            total_unreal += unreal
            have_any_unreal = True
        mark_txt = f"{mark:.2f} [{p.get('mark_source')}]" if mark is not None else f"n/a [{p.get('mark_source')}]"
        entry_txt = f"{entry:.2f}" if entry is not None else 'n/a'
        sl_txt = f"{sl:.2f}" if sl is not None else 'n/a'
        tp_txt = f"{tp:.2f}" if tp is not None else 'n/a'
        symbol_txt = str(p.get('symbol') or '?')
        direction_txt = str(p.get('direction') or '?')
        lines.append(
            f"  {symbol_txt:<12} {direction_txt:<4} "
            f"x{p.get('quantity')}  entry {entry_txt}  SL {sl_txt}  TP {tp_txt}{eff_sl_txt}  "
            f"[{p.get('trade_mode') or '?'}] [{p.get('strategy') or '?'}]"
        )
        lines.append(f"      mark {mark_txt}  unrealized {signed_money(unreal)}  {p.get('mark_note') or ''}".rstrip())
    lines.append(f"  Total unrealized: {signed_money(total_unreal if have_any_unreal else None)}")
    return lines


def render_book(label: str, book: dict) -> List[str]:
    sep = "-" * 80
    if not book['available']:
        return [f"{label} book", sep, "database unavailable -- n/a", sep]
    lines = [f"{label} book", sep]
    lines += render_closed(book['closed'])
    lines.append("")
    lines += render_open(book['open'])
    lines.append("")
    closed_n = book['lifetime_closed']
    wins = book['lifetime_wins']
    wr_txt = f"{(wins / closed_n * 100):.1f}% win rate" if closed_n else "n/a (0 closed trades)"
    lines.append(f"Lifetime: {closed_n} closed, {wins} wins ({wr_txt}), "
                 f"realized {money(book['lifetime_realized'])}")
    lines.append(f"Capital: {money(book['capital'])}")
    lines.append(sep)
    return lines


def build_report(date_str: str, offline: bool) -> str:
    zerodha_conn = _ro_conn(ZERODHA_DB)

    books = {label: gather_book(path, date_str) for label, path in BOOKS}

    all_open_symbols = sorted({
        p['symbol'] for book in books.values() if book['available']
        for p in book['open'] if p.get('symbol')
    })
    quotes, quote_status = fetch_live_quotes(all_open_symbols, offline)
    for book in books.values():
        if book['available'] and book['open']:
            mark_open_positions(book['open'], quotes, zerodha_conn)

    if zerodha_conn is not None:
        try:
            zerodha_conn.close()
        except sqlite3.Error:
            pass

    lines = [
        "=" * 80,
        f"POSITION REPORT -- {date_str}  (generated {datetime.now().strftime('%Y-%m-%d %H:%M:%S')})",
        "=" * 80,
        "",
    ]
    for label, _path in BOOKS:
        lines += render_book(label, books[label])
        lines.append("")

    combined_today = sum((r.get('pnl') or 0) for book in books.values() for r in book['closed'])
    combined_unreal_parts = [p.get('unrealized') for book in books.values() for p in book['open']
                              if p.get('unrealized') is not None]
    combined_unreal = sum(combined_unreal_parts) if combined_unreal_parts else None
    combined_lifetime = sum((book.get('lifetime_realized') or 0) for book in books.values()
                             if book['available'])

    lines.append("COMBINED (both books)")
    lines.append(f"  Today realized:      {signed_money(combined_today)}")
    lines.append(f"  Open unrealized:     {signed_money(combined_unreal)}")
    lines.append(f"  Lifetime realized:   {signed_money(combined_lifetime)}")
    lines.append("")

    n_marked = sum(1 for s in all_open_symbols if quotes.get(s, {}).get('last_price'))
    status_txt = {
        'offline': '--offline passed -- live quote fetch skipped, all marks forced to stale-DB/none',
        'no-symbols': 'no open positions to mark',
        'no-token': 'no token in env or enctoken.txt -- never attempted login, went straight to stale-DB fallback',
        'quote-failed': 'quote call returned nothing (expired/invalid token or network failure) -- fell back to stale-DB marks',
        'chart': f'quote endpoint dead (HTTP 400) -- used chart-API last-minute closes instead '
                 f'({n_marked}/{len(all_open_symbols)} symbol(s))'
                 + (f'; {len(all_open_symbols) - n_marked} fell back to stale-DB marks' if n_marked < len(all_open_symbols) else ''),
        'live': f'{n_marked}/{len(all_open_symbols)} open symbol(s) got a live quote'
                + (f'; {len(all_open_symbols) - n_marked} fell back to stale-DB marks' if n_marked < len(all_open_symbols) else ''),
    }.get(quote_status, quote_status)
    lines.append(f"Quote source: {status_txt}")
    lines.append("=" * 80)

    return "\n".join(lines)


def main():
    parser = argparse.ArgumentParser(description='Read-only position report (both paper-trading books).')
    parser.add_argument('--date', type=_valid_date, default=None,
                         help='YYYY-MM-DD; default = today (IST, matches system clock)')
    parser.add_argument('--offline', action='store_true',
                         help='Skip the live-quote attempt entirely; every open position marks '
                              'from the stale DB fallback (or "(no mark available)"). Never touches '
                              'ZERODHA_ENCTOKEN or the network for quotes.')
    args = parser.parse_args()

    date_str = args.date or today_ist()

    try:
        report = build_report(date_str, args.offline)
    except Exception as e:
        traceback.print_exc()
        print(f"REPORT FAILED: {e}", file=sys.stderr)
        sys.exit(1)

    print(report)


if __name__ == '__main__':
    main()
