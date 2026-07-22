"""
Read-only Trading Dashboard (stdlib only)
=========================================
Single-file dashboard built on http.server -- NO Flask, NO third-party deps.
Serves ONE self-contained HTML page (inline CSS/JS, auto-refresh every 60s).

It is strictly READ-ONLY: it never writes to any DB, file, or the trading path.
Every data source is wrapped so a missing file/table degrades to 'n/a' rather
than a 500. All SQLite connections are opened with ?mode=ro (immutable read).

Data sources
------------
  main book       data/paper_trades.db      (positions / account tables)
  incubator book  data/incubator_trades.db  (same PaperTrader schema)
  live-ish prices data/zerodha_data.db      (ohlcv, interval='minute' -> last close)
  parity strip    kite/live_monitor/parity_history.jsonl  (last line)
  filter strip    data/strategies_paused.json  +  data/monitor.log ('AnnouncementFilter:')

Usage
-----
    python -m kite.live_monitor.dashboard

Env
---
    DASHBOARD_PORT   TCP port to bind (default 8050) -- keep in sync with systemd/firewall.
"""
import html
import json
import os
import re
import sqlite3
from datetime import datetime
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

# --------------------------------------------------------------------------
# Paths (derived from this file's location; repo root is two levels up)
# --------------------------------------------------------------------------
_HERE = Path(__file__).resolve().parent
_ROOT = _HERE.parents[1]
_DATA = _ROOT / "data"

MAIN_DB = Path(os.environ.get("DASHBOARD_MAIN_DB", _DATA / "paper_trades.db"))
INCUBATOR_DB = Path(os.environ.get("DASHBOARD_INCUBATOR_DB", _DATA / "incubator_trades.db"))
ZERODHA_DB = Path(os.environ.get("DASHBOARD_ZERODHA_DB", _DATA / "zerodha_data.db"))
PARITY_JSONL = _HERE / "parity_history.jsonl"
PAUSED_JSON = _DATA / "strategies_paused.json"
MONITOR_LOG = _DATA / "monitor.log"

BOOKS = [("main", MAIN_DB), ("incubator", INCUBATOR_DB)]

# --------------------------------------------------------------------------
# Low-level read helpers -- every one fails soft (returns None / [] / {})
# --------------------------------------------------------------------------


def _ro_conn(path):
    """Open a strictly read-only connection, or None if unavailable."""
    try:
        if not Path(path).exists():
            return None
        conn = sqlite3.connect(f"file:{path}?mode=ro", uri=True)
        conn.row_factory = sqlite3.Row
        return conn
    except Exception:
        return None


def _latest_close(conn, symbol):
    """Latest 'minute' close for a symbol from zerodha ohlcv, or None."""
    try:
        row = conn.execute(
            "SELECT close FROM ohlcv WHERE symbol=? AND interval='minute' "
            "ORDER BY datetime DESC LIMIT 1",
            (symbol,),
        ).fetchone()
        return row[0] if row else None
    except Exception:
        return None


def latest_prices(symbols):
    """Return {symbol: last_close} for the given symbols. Missing -> absent."""
    out = {}
    if not symbols:
        return out
    conn = _ro_conn(ZERODHA_DB)
    if conn is None:
        return out
    try:
        for sym in symbols:
            price = _latest_close(conn, sym)
            if price is not None:
                out[sym] = price
    finally:
        try:
            conn.close()
        except Exception:
            pass
    return out


def _unrealized(direction, entry, qty, current):
    """Unrealized P&L honoring trade direction. None if any input missing."""
    if current is None or entry is None or qty is None:
        return None
    try:
        if str(direction).upper() == "SELL":
            return (entry - current) * qty
        return (current - entry) * qty
    except Exception:
        return None


def read_book(db_path, today):
    """
    Gather one book's state. Returns a dict; every field degrades to a
    fail-soft default (None / [] / 'n/a') so a missing DB never raises.
    """
    book = {
        "available": False,
        "capital": None,
        "initial_capital": None,
        "last_updated": None,
        "open": [],            # list of position dicts (+ current/unrealized)
        "closed_today": [],    # list of closed-today position dicts
        "today_realized": None,
        "all_time_realized": None,
        "unrealized_total": None,
    }
    conn = _ro_conn(db_path)
    if conn is None:
        return book
    book["available"] = True
    try:
        # account
        try:
            row = conn.execute(
                "SELECT * FROM account ORDER BY id DESC LIMIT 1"
            ).fetchone()
            if row:
                book["capital"] = row["capital"]
                book["initial_capital"] = row["initial_capital"]
                book["last_updated"] = row["last_updated"]
        except Exception:
            pass

        # open positions
        try:
            rows = conn.execute(
                "SELECT * FROM positions WHERE status='open' ORDER BY entry_time DESC"
            ).fetchall()
            book["open"] = [dict(r) for r in rows]
        except Exception:
            book["open"] = []

        # closed today
        try:
            rows = conn.execute(
                "SELECT * FROM positions WHERE status='closed' "
                "AND substr(exit_time,1,10)=? ORDER BY exit_time DESC",
                (today,),
            ).fetchall()
            book["closed_today"] = [dict(r) for r in rows]
        except Exception:
            book["closed_today"] = []

        # realized aggregates
        try:
            book["all_time_realized"] = conn.execute(
                "SELECT COALESCE(SUM(pnl),0) FROM positions WHERE status='closed'"
            ).fetchone()[0]
        except Exception:
            book["all_time_realized"] = None
        try:
            book["today_realized"] = conn.execute(
                "SELECT COALESCE(SUM(pnl),0) FROM positions "
                "WHERE status='closed' AND substr(exit_time,1,10)=?",
                (today,),
            ).fetchone()[0]
        except Exception:
            book["today_realized"] = None
    finally:
        try:
            conn.close()
        except Exception:
            pass

    # enrich open positions with live-ish current price + unrealized
    syms = sorted({p.get("symbol") for p in book["open"] if p.get("symbol")})
    prices = latest_prices(syms)
    total_unreal = 0.0
    have_unreal = False
    for p in book["open"]:
        cur = prices.get(p.get("symbol"))
        p["current"] = cur
        u = _unrealized(p.get("direction"), p.get("entry_price"),
                        p.get("quantity"), cur)
        p["unrealized"] = u
        if u is not None:
            total_unreal += u
            have_unreal = True
    book["unrealized_total"] = total_unreal if have_unreal else None
    return book


def read_parity():
    """Parse the LAST line of parity_history.jsonl. Returns dict or None."""
    try:
        raw = _tail_bytes(PARITY_JSONL, 256 * 1024)
        if not raw:
            return None
        last = None
        for line in raw.splitlines():
            line = line.strip()
            if line:
                last = line
        if not last:
            return None
        return json.loads(last)
    except Exception:
        return None


def read_paused():
    """Return {strategy: {reason, since}} from strategies_paused.json, or {}."""
    try:
        if not PAUSED_JSON.exists():
            return {}
        data = json.loads(PAUSED_JSON.read_text(encoding="utf-8"))
        return data if isinstance(data, dict) else {}
    except Exception:
        return {}


def _tail_bytes(path, nbytes):
    """Read up to the last nbytes of a file as text. '' on any failure."""
    try:
        with open(path, "rb") as f:
            f.seek(0, os.SEEK_END)
            size = f.tell()
            f.seek(max(0, size - nbytes))
            return f.read().decode("utf-8", "replace")
    except Exception:
        return ""


def read_announcement_flags():
    """
    Cheaply grep the tail of monitor.log for the last 'AnnouncementFilter:'
    line and extract the red-flagged symbol count. Returns int or None.
    """
    try:
        text = _tail_bytes(MONITOR_LOG, 128 * 1024)
        if not text:
            return None
        last = None
        for line in text.splitlines():
            if "AnnouncementFilter:" in line:
                last = line
        if last is None:
            return None
        m = re.search(r"(\d+)\s+symbols?\s+red-flagged", last)
        if m:
            return int(m.group(1))
        return None
    except Exception:
        return None


# --------------------------------------------------------------------------
# HTML rendering helpers
# --------------------------------------------------------------------------
NA = '<span class="na">n/a</span>'


def esc(v):
    return html.escape("" if v is None else str(v))


def money(v):
    """Rupee-formatted string, or the n/a chip."""
    if v is None:
        return NA
    try:
        return f"&#8377;{v:,.2f}"
    except Exception:
        return NA


def signed_money(v):
    """Rupee-formatted with explicit + sign for positives."""
    if v is None:
        return NA
    try:
        sign = "+" if v > 0 else ""
        return f"{sign}&#8377;{v:,.2f}"
    except Exception:
        return NA


def pnl_class(v):
    if v is None:
        return "flat"
    return "pos" if v > 0 else ("neg" if v < 0 else "flat")


def num(v):
    if v is None:
        return NA
    try:
        return f"{v:,}"
    except Exception:
        return esc(v)


def short_time(v):
    """Trim ISO timestamp to 'YYYY-MM-DD HH:MM' for compact display."""
    if not v:
        return NA
    s = str(v).replace("T", " ")
    return esc(s[:16])


PARITY_COLOR = {
    "GREEN": "chip-green",
    "RED": "chip-red",
    "AMBER": "chip-amber",
    "YELLOW": "chip-amber",
    "WARMING_UP": "chip-grey",
    "NODATA": "chip-grey",
    "NO_DATA": "chip-grey",
}


def parity_chip_class(status):
    return PARITY_COLOR.get(str(status).upper(), "chip-grey")


def side_span(direction):
    d = ("" if direction is None else str(direction)).upper()
    cls = "pos" if d == "BUY" else ("neg" if d == "SELL" else "flat")
    return f'<span class="{cls}" style="font-weight:600">{esc(d) or "&mdash;"}</span>'


def badge(text):
    if not text:
        return "&mdash;"
    return f'<span class="badge">{esc(text)}</span>'


def mode_badge(mode):
    if not mode:
        return "&mdash;"
    m = str(mode).upper()
    cls = "mode-swing" if "SWING" in m or "CANDIDATE" in m else "mode-intraday"
    return f'<span class="badge {cls}">{esc(m)}</span>'


# --------------------------------------------------------------------------
# Section builders
# --------------------------------------------------------------------------


def render_book_card(name, book):
    if not book["available"]:
        return f"""
        <div class="bookcard">
          <div class="bookcard-title">{esc(name).upper()} BOOK</div>
          <div class="unavail">database unavailable &mdash; {NA}</div>
        </div>"""
    cap = money(book["capital"])
    init = money(book["initial_capital"])
    unreal = book["unrealized_total"]
    tr = book["today_realized"]
    at = book["all_time_realized"]
    return f"""
    <div class="bookcard">
      <div class="bookcard-title">{esc(name).upper()} BOOK</div>
      <div class="stat-row">
        <div class="stat"><span class="lbl">Capital</span><span class="val">{cap}</span></div>
        <div class="stat"><span class="lbl">Initial</span><span class="val">{init}</span></div>
        <div class="stat"><span class="lbl">Open</span><span class="val">{len(book['open'])}</span></div>
      </div>
      <div class="stat-row">
        <div class="stat"><span class="lbl">Unrealized</span><span class="val {pnl_class(unreal)}">{signed_money(unreal)}</span></div>
        <div class="stat"><span class="lbl">Today realized</span><span class="val {pnl_class(tr)}">{signed_money(tr)}</span></div>
        <div class="stat"><span class="lbl">All-time realized</span><span class="val {pnl_class(at)}">{signed_money(at)}</span></div>
      </div>
      <div class="upd">updated {short_time(book['last_updated'])}</div>
    </div>"""


def render_open_table(name, book):
    if not book["available"]:
        return f'<div class="section"><h2>Open Positions &mdash; {esc(name)}</h2>' \
               f'<div class="empty">database unavailable ({NA})</div></div>'
    rows = ""
    for p in book["open"]:
        u = p.get("unrealized")
        rows += f"""<tr>
          <td class="sym">{esc(p.get('symbol'))}</td>
          <td>{side_span(p.get('direction'))}</td>
          <td class="mono">{num(p.get('quantity'))}</td>
          <td class="mono">{money(p.get('entry_price'))}</td>
          <td class="mono">{money(p.get('current'))}</td>
          <td class="mono {pnl_class(u)}">{signed_money(u)}</td>
          <td>{badge(p.get('strategy'))}</td>
          <td>{mode_badge(p.get('trade_mode'))}</td>
          <td class="mono dim">{short_time(p.get('entry_time'))}</td>
        </tr>"""
    if not rows:
        rows = '<tr><td colspan="9" class="empty">No open positions</td></tr>'
    return f"""<div class="section">
      <h2>Open Positions &mdash; {esc(name)} <span class="count">({len(book['open'])})</span></h2>
      <div class="scroll"><table>
        <thead><tr>
          <th>Symbol</th><th>Dir</th><th>Qty</th><th>Entry</th><th>Current</th>
          <th>Unreal P&amp;L</th><th>Strategy</th><th>Mode</th><th>Entry Time</th>
        </tr></thead>
        <tbody>{rows}</tbody>
      </table></div>
    </div>"""


def render_closed_today(books):
    rows = ""
    total = 0
    for name, book in books:
        if not book["available"]:
            continue
        for t in book["closed_today"]:
            total += 1
            pnl = t.get("pnl")
            pct = t.get("pnl_pct")
            pct_txt = NA if pct is None else f'{"+" if (pct or 0) > 0 else ""}{pct:.2f}%'
            rows += f"""<tr>
              <td>{badge(name)}</td>
              <td class="sym">{esc(t.get('symbol'))}</td>
              <td>{side_span(t.get('direction'))}</td>
              <td class="mono">{num(t.get('quantity'))}</td>
              <td class="mono">{money(t.get('entry_price'))}</td>
              <td class="mono">{money(t.get('exit_price'))}</td>
              <td class="mono {pnl_class(pnl)}">{signed_money(pnl)}</td>
              <td class="mono {pnl_class(pnl)}">{pct_txt}</td>
              <td>{badge(t.get('exit_reason'))}</td>
              <td>{badge(t.get('strategy'))}</td>
              <td class="mono dim">{short_time(t.get('exit_time'))}</td>
            </tr>"""
    if not rows:
        rows = '<tr><td colspan="11" class="empty">No trades closed today</td></tr>'
    return f"""<div class="section">
      <h2>Today's Closed Trades <span class="count">({total})</span></h2>
      <div class="scroll"><table>
        <thead><tr>
          <th>Book</th><th>Symbol</th><th>Dir</th><th>Qty</th><th>Entry</th>
          <th>Exit</th><th>P&amp;L</th><th>%</th><th>Exit Reason</th>
          <th>Strategy</th><th>Exit Time</th>
        </tr></thead>
        <tbody>{rows}</tbody>
      </table></div>
    </div>"""


def render_parity(parity):
    if not parity:
        return '<div class="section"><h2>Parity Monitor</h2>' \
               f'<div class="empty">parity_history.jsonl unavailable ({NA})</div></div>'
    overall = str(parity.get("overall", "?")).upper()
    ts = short_time(parity.get("ts"))
    chips = ""
    for chk in parity.get("per_check", []) or []:
        cls = parity_chip_class(chk.get("status"))
        cid = esc(chk.get("id", "?"))
        cname = esc(chk.get("name", ""))
        detail = esc(chk.get("detail", ""))
        status = esc(chk.get("status", ""))
        chips += (
            f'<span class="chip {cls}" title="{status} &mdash; {detail}">'
            f'<b>{cid}</b> {cname}</span>'
        )
    if not chips:
        chips = f'<span class="empty">no checks ({NA})</span>'
    return f"""<div class="section">
      <h2>Parity Monitor
        <span class="chip {parity_chip_class(overall)}" style="margin-left:8px">OVERALL: {esc(overall)}</span>
        <span class="count">as of {ts}</span>
      </h2>
      <div class="chips">{chips}</div>
    </div>"""


def render_filters(paused, ann_count):
    # paused strategies
    if paused:
        pchips = "".join(
            f'<span class="chip chip-red" title="{esc((v or {}).get("reason",""))}">'
            f'{esc(k)}</span>'
            for k, v in paused.items()
        )
    else:
        pchips = '<span class="chip chip-green">none paused</span>'
    ann_txt = NA if ann_count is None else f"{ann_count} symbol(s) red-flagged"
    ann_cls = "chip-grey" if ann_count in (None, 0) else "chip-amber"
    return f"""<div class="section">
      <h2>Filters</h2>
      <div class="filterline"><span class="flabel">Paused strategies</span>
        <div class="chips">{pchips}</div></div>
      <div class="filterline"><span class="flabel">Announcement filter</span>
        <div class="chips"><span class="chip {ann_cls}">{ann_txt}</span></div></div>
    </div>"""


# --------------------------------------------------------------------------
# Page
# --------------------------------------------------------------------------
STYLE = """
* { margin:0; padding:0; box-sizing:border-box; }
body { background:#0b1220; color:#e2e8f0;
  font-family:'Segoe UI',system-ui,-apple-system,sans-serif;
  padding:18px; min-height:100vh; -webkit-text-size-adjust:100%; }
.mono, .val, .sym, td.mono { font-family:'SFMono-Regular',Consolas,'Roboto Mono',monospace; }
.pos { color:#4ade80; } .neg { color:#f87171; } .flat { color:#cbd5e1; }
.na { color:#64748b; font-style:italic; }
.dim { color:#7c8aa5; }
.topbar { display:flex; align-items:center; justify-content:space-between;
  flex-wrap:wrap; gap:8px; margin-bottom:16px; }
.topbar h1 { font-size:1.25rem; color:#f8fafc; font-weight:700; }
.live { font-size:.8rem; color:#94a3b8; display:inline-flex; align-items:center; gap:6px; }
.live::before { content:''; width:9px; height:9px; border-radius:50%;
  background:#4ade80; display:inline-block; animation:pulse 2s ease-in-out infinite; }
@keyframes pulse { 0%,100%{opacity:1;transform:scale(1);} 50%{opacity:.45;transform:scale(.82);} }
.books { display:grid; grid-template-columns:repeat(auto-fit,minmax(320px,1fr));
  gap:14px; margin-bottom:18px; }
.bookcard { background:#131c2e; border:1px solid #263149; border-radius:10px; padding:14px 16px; }
.bookcard-title { font-size:.72rem; letter-spacing:.08em; color:#8ea2c4;
  text-transform:uppercase; margin-bottom:10px; font-weight:700; }
.stat-row { display:flex; gap:10px; margin-bottom:8px; flex-wrap:wrap; }
.stat { flex:1; min-width:90px; display:flex; flex-direction:column; }
.stat .lbl { font-size:.64rem; text-transform:uppercase; letter-spacing:.05em; color:#8194b5; }
.stat .val { font-size:1.02rem; font-weight:700; color:#f1f5f9; margin-top:2px; }
.upd { font-size:.66rem; color:#5b6b88; margin-top:4px; }
.unavail { color:#f59e0b; font-size:.85rem; }
.section { background:#131c2e; border:1px solid #263149; border-radius:10px;
  padding:14px 16px; margin-bottom:16px; }
.section h2 { font-size:.98rem; color:#f1f5f9; font-weight:600; margin-bottom:12px;
  display:flex; align-items:center; flex-wrap:wrap; gap:6px; }
.count { font-size:.72rem; color:#7c8aa5; font-weight:400; }
.scroll { overflow-x:auto; }
table { width:100%; border-collapse:collapse; min-width:640px; }
th { text-align:left; font-size:.66rem; text-transform:uppercase; letter-spacing:.04em;
  color:#8194b5; padding:8px 10px; border-bottom:1px solid #263149; white-space:nowrap; }
td { padding:8px 10px; border-bottom:1px solid #1a2740; font-size:.82rem; white-space:nowrap; }
tr:hover td { background:rgba(38,49,73,.35); }
td.sym { font-weight:600; color:#f8fafc; }
.empty { text-align:center; color:#64748b; padding:18px; }
.badge { background:#22304d; color:#a9bcdf; padding:2px 7px; border-radius:5px;
  font-size:.7rem; white-space:nowrap; }
.mode-swing { background:rgba(167,139,250,.16); color:#c4b5fd; }
.mode-intraday { background:rgba(96,165,250,.16); color:#93c5fd; }
.chips { display:flex; flex-wrap:wrap; gap:6px; }
.chip { padding:3px 9px; border-radius:20px; font-size:.72rem; border:1px solid transparent;
  white-space:nowrap; cursor:default; }
.chip b { font-weight:700; }
.chip-green { background:rgba(74,222,128,.12); color:#86efac; border-color:rgba(74,222,128,.35); }
.chip-red   { background:rgba(248,113,113,.13); color:#fca5a5; border-color:rgba(248,113,113,.4); }
.chip-amber { background:rgba(251,191,36,.13); color:#fcd34d; border-color:rgba(251,191,36,.38); }
.chip-grey  { background:rgba(100,116,139,.15); color:#94a3b8; border-color:rgba(100,116,139,.3); }
.filterline { display:flex; align-items:center; gap:12px; margin-bottom:10px; flex-wrap:wrap; }
.flabel { font-size:.72rem; text-transform:uppercase; letter-spacing:.05em; color:#8194b5;
  min-width:150px; }
.foot { text-align:center; color:#475569; font-size:.7rem; margin-top:10px; }
@media (max-width:560px){ body{padding:10px;} .flabel{min-width:100%;} }
"""


def render_page():
    today = datetime.now().strftime("%Y-%m-%d")
    now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")

    books = [(name, read_book(path, today)) for name, path in BOOKS]
    parity = read_parity()
    paused = read_paused()
    ann_count = read_announcement_flags()

    book_cards = "".join(render_book_card(n, b) for n, b in books)
    open_tables = "".join(render_open_table(n, b) for n, b in books)
    closed = render_closed_today(books)
    parity_html = render_parity(parity)
    filters_html = render_filters(paused, ann_count)

    return f"""<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <meta http-equiv="refresh" content="60">
  <title>Trading Dashboard</title>
  <style>{STYLE}</style>
</head>
<body>
  <div class="topbar">
    <h1>Trading Dashboard</h1>
    <span class="live">read-only &mdash; auto-refresh 60s</span>
  </div>

  <div class="books">{book_cards}</div>

  {parity_html}
  {filters_html}
  {open_tables}
  {closed}

  <div class="foot">Rendered {esc(now)} &middot; today = {esc(today)} &middot; read-only, no writes</div>
</body>
</html>"""


# --------------------------------------------------------------------------
# HTTP server (stdlib)
# --------------------------------------------------------------------------
class DashboardHandler(BaseHTTPRequestHandler):
    server_version = "KiteDashboard/2.0"

    def _send(self, code, body, ctype="text/html; charset=utf-8"):
        data = body.encode("utf-8") if isinstance(body, str) else body
        self.send_response(code)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(data)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        if self.command != "HEAD":
            self.wfile.write(data)

    def do_GET(self):
        if self.path in ("/favicon.ico",):
            self._send(204, b"", "image/x-icon")
            return
        if self.path in ("/health", "/healthz"):
            self._send(200, "ok", "text/plain; charset=utf-8")
            return
        try:
            page = render_page()
            self._send(200, page)
        except Exception as e:
            # Absolute last-resort guard: still 200, never leak a stack trace as 500.
            self._send(
                200,
                "<!DOCTYPE html><meta http-equiv='refresh' content='60'>"
                f"<body style='background:#0b1220;color:#f87171;font-family:monospace;"
                f"padding:24px'>dashboard render error (fail-soft): {esc(e)}</body>",
            )

    do_HEAD = do_GET

    def log_message(self, *args):
        # Quiet by default; systemd/journald captures stderr if needed.
        return


def main():
    port = int(os.environ.get("DASHBOARD_PORT", 8050))
    httpd = ThreadingHTTPServer(("0.0.0.0", port), DashboardHandler)
    print(f"Read-only trading dashboard on http://0.0.0.0:{port}  (Ctrl-C to stop)")
    try:
        httpd.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        httpd.server_close()


if __name__ == "__main__":
    main()
