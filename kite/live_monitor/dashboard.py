"""
Paper Trading Dashboard
=======================
Flask web dashboard for monitoring paper trading performance.
Single-file app with inline HTML/CSS/JS.

Usage:
    python -m kite.live_monitor.dashboard
"""
import os
import sqlite3
from flask import Flask, Response

app = Flask(__name__)

DB_PATH = os.environ.get(
    "DASHBOARD_DB_PATH",
    os.path.join(os.path.dirname(__file__), "..", "..", "data", "paper_trades.db"),
)


def get_db():
    """Get a read-only database connection."""
    conn = sqlite3.connect(f"file:{DB_PATH}?mode=ro", uri=True)
    conn.row_factory = sqlite3.Row
    return conn


def query_account():
    """Return account row or sensible defaults."""
    try:
        db = get_db()
        row = db.execute("SELECT * FROM account ORDER BY id DESC LIMIT 1").fetchone()
        db.close()
        if row:
            return dict(row)
    except Exception:
        pass
    return {"capital": 0, "initial_capital": 0, "trade_counter": 0, "last_updated": ""}


def query_open_positions():
    """Return list of open positions."""
    try:
        db = get_db()
        rows = db.execute(
            "SELECT * FROM positions WHERE status = 'open' ORDER BY entry_time DESC"
        ).fetchall()
        db.close()
        return [dict(r) for r in rows]
    except Exception:
        return []


def query_closed_trades():
    """Return list of closed trades, most recent first."""
    try:
        db = get_db()
        rows = db.execute(
            "SELECT * FROM positions WHERE status = 'closed' ORDER BY exit_time DESC"
        ).fetchall()
        db.close()
        return [dict(r) for r in rows]
    except Exception:
        return []


def query_daily_summary():
    """Return daily summary rows ordered by date."""
    try:
        db = get_db()
        rows = db.execute(
            "SELECT * FROM daily_summary ORDER BY date ASC"
        ).fetchall()
        db.close()
        return [dict(r) for r in rows]
    except Exception:
        return []


def query_latest_prices():
    """Return latest prices as {symbol: price}."""
    try:
        db = get_db()
        rows = db.execute("SELECT symbol, price FROM latest_prices").fetchall()
        db.close()
        return {r["symbol"]: r["price"] for r in rows}
    except Exception:
        return {}


def _fmt_price(val):
    """Format a number as a rupee string for use inside HTML."""
    if val is None:
        return "&#8377;0.00"
    return f"&#8377;{val:,.2f}"


def _pnl_color(val):
    """Return CSS color for a P&L value."""
    if val is None or val == 0:
        return "#e2e8f0"
    return "#4ade80" if val > 0 else "#f87171"


def _sign(val):
    """Return + prefix for positive numbers."""
    if val is None:
        return ""
    return "+" if val > 0 else ""


def _badge(text):
    """Return an HTML badge span."""
    if not text:
        return ""
    return (
        f'<span style="background:#334155;color:#94a3b8;padding:2px 8px;'
        f'border-radius:4px;font-size:0.75rem;">{text}</span>'
    )


def _side_badge(direction):
    """Return a colored side badge."""
    if not direction:
        return ""
    color = "#4ade80" if direction.upper() == "BUY" else "#f87171"
    return (
        f'<span style="color:{color};font-weight:600;">{direction.upper()}</span>'
    )


def _mode_badge(mode):
    """Return a colored mode badge."""
    if not mode:
        return ""
    if mode == "SWING":
        return '<span style="background:rgba(167,139,250,0.15);color:#a78bfa;padding:2px 8px;border-radius:4px;font-size:0.75rem;font-weight:600;">SWING</span>'
    return '<span style="background:rgba(96,165,250,0.15);color:#60a5fa;padding:2px 8px;border-radius:4px;font-size:0.75rem;font-weight:600;">INTRADAY</span>'


@app.route("/")
def index():
    account = query_account()
    open_pos = query_open_positions()
    closed = query_closed_trades()
    daily = query_daily_summary()

    swing_count = sum(1 for p in open_pos if p.get('trade_mode') == 'SWING')

    capital = account.get("capital", 0) or 0
    initial = account.get("initial_capital", 0) or 0
    prices = query_latest_prices()
    market_value = sum(
        prices.get(p.get("symbol"), p.get("entry_price", 0) or 0) * (p.get("quantity", 0) or 0)
        for p in open_pos
    )
    portfolio_value = capital + market_value
    total_pnl = portfolio_value - initial if initial else 0

    total_trades = len(closed)
    wins = sum(1 for t in closed if (t.get("pnl") or 0) > 0)
    losses = sum(1 for t in closed if (t.get("pnl") or 0) < 0)
    win_rate = (wins / total_trades * 100) if total_trades > 0 else 0

    win_pnls = [t["pnl"] for t in closed if (t.get("pnl") or 0) > 0]
    loss_pnls = [t["pnl"] for t in closed if (t.get("pnl") or 0) < 0]
    avg_win = sum(win_pnls) / len(win_pnls) if win_pnls else 0
    avg_loss = sum(loss_pnls) / len(loss_pnls) if loss_pnls else 0

    # Chart data
    chart_labels = [d["date"] for d in daily]
    chart_values = [d.get("capital", 0) or 0 for d in daily]
    chart_labels_js = str(chart_labels)
    chart_values_js = str(chart_values)

    # Build open positions rows
    open_rows = ""
    if open_pos:
        for p in open_pos:
            open_rows += f"""<tr>
                <td style="font-weight:600;">{p.get('symbol','')}</td>
                <td>{_side_badge(p.get('direction',''))}</td>
                <td>{_fmt_price(p.get('entry_price'))}</td>
                <td>{p.get('quantity','')}</td>
                <td>{_fmt_price(p.get('stop_loss'))}</td>
                <td>{_fmt_price(p.get('take_profit'))}</td>
                <td>{_badge(p.get('strategy',''))}</td>
                <td>{_mode_badge(p.get('trade_mode',''))}</td>
            </tr>"""
    else:
        open_rows = '<tr><td colspan="8" style="text-align:center;color:#64748b;padding:24px;">No open positions</td></tr>'

    # Build closed trades rows
    closed_rows = ""
    if closed:
        for t in closed:
            pnl = t.get("pnl") or 0
            pnl_pct = t.get("pnl_pct") or 0
            closed_rows += f"""<tr>
                <td style="font-weight:600;">{t.get('symbol','')}</td>
                <td>{_side_badge(t.get('direction',''))}</td>
                <td>{_fmt_price(t.get('entry_price'))}</td>
                <td>{_fmt_price(t.get('exit_price'))}</td>
                <td>{t.get('quantity','')}</td>
                <td style="color:{_pnl_color(pnl)};font-weight:600;">{_sign(pnl)}{_fmt_price(pnl)}</td>
                <td style="color:{_pnl_color(pnl)};">{_sign(pnl_pct)}{pnl_pct:.2f}%</td>
                <td>{_badge(t.get('exit_reason',''))}</td>
                <td>{_badge(t.get('strategy',''))}</td>
                <td>{_mode_badge(t.get('trade_mode',''))}</td>
            </tr>"""
    else:
        closed_rows = '<tr><td colspan="10" style="text-align:center;color:#64748b;padding:24px;">No closed trades yet</td></tr>'

    html = f"""<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="utf-8">
    <meta name="viewport" content="width=device-width, initial-scale=1">
    <meta http-equiv="refresh" content="30">
    <title>Paper Trading Dashboard</title>
    <style>
        * {{
            margin: 0;
            padding: 0;
            box-sizing: border-box;
        }}
        body {{
            background: #0f172a;
            color: #e2e8f0;
            font-family: 'Segoe UI', system-ui, -apple-system, sans-serif;
            padding: 24px;
            min-height: 100vh;
        }}
        .header {{
            display: flex;
            align-items: center;
            justify-content: space-between;
            margin-bottom: 24px;
        }}
        .header h1 {{
            font-size: 1.5rem;
            font-weight: 700;
            color: #f8fafc;
        }}
        .live-dot {{
            display: inline-flex;
            align-items: center;
            gap: 8px;
            font-size: 0.85rem;
            color: #94a3b8;
        }}
        .live-dot::before {{
            content: '';
            display: inline-block;
            width: 10px;
            height: 10px;
            border-radius: 50%;
            background: #4ade80;
            animation: pulse 2s ease-in-out infinite;
        }}
        @keyframes pulse {{
            0%, 100% {{ opacity: 1; transform: scale(1); }}
            50% {{ opacity: 0.5; transform: scale(0.85); }}
        }}
        .cards {{
            display: grid;
            grid-template-columns: repeat(auto-fit, minmax(180px, 1fr));
            gap: 16px;
            margin-bottom: 24px;
        }}
        .card {{
            background: #1e293b;
            border: 1px solid #334155;
            border-radius: 8px;
            padding: 16px;
        }}
        .card-label {{
            font-size: 0.75rem;
            text-transform: uppercase;
            color: #94a3b8;
            letter-spacing: 0.05em;
            margin-bottom: 6px;
        }}
        .card-value {{
            font-size: 1.5rem;
            font-weight: 700;
            color: #f8fafc;
        }}
        .section {{
            background: #1e293b;
            border: 1px solid #334155;
            border-radius: 8px;
            padding: 20px;
            margin-bottom: 24px;
        }}
        .section h2 {{
            font-size: 1.1rem;
            font-weight: 600;
            color: #f8fafc;
            margin-bottom: 16px;
        }}
        table {{
            width: 100%;
            border-collapse: collapse;
        }}
        th {{
            text-align: left;
            font-size: 0.75rem;
            text-transform: uppercase;
            color: #94a3b8;
            padding: 10px 12px;
            border-bottom: 1px solid #334155;
            letter-spacing: 0.05em;
        }}
        td {{
            padding: 10px 12px;
            border-bottom: 1px solid #1e293b;
            font-size: 0.875rem;
        }}
        tr:hover td {{
            background: rgba(51, 65, 85, 0.3);
        }}
        .chart-container {{
            position: relative;
            height: 280px;
        }}
        .footer {{
            text-align: center;
            color: #475569;
            font-size: 0.75rem;
            margin-top: 12px;
        }}
    </style>
</head>
<body>
    <div class="header">
        <h1>Paper Trading Dashboard</h1>
        <span class="live-dot">Live &mdash; auto-refresh 30s</span>
    </div>

    <div class="cards">
        <div class="card">
            <div class="card-label">Portfolio Value</div>
            <div class="card-value">{_fmt_price(portfolio_value)}</div>
        </div>
        <div class="card">
            <div class="card-label">Total P&amp;L</div>
            <div class="card-value" style="color:{_pnl_color(total_pnl)};">{_sign(total_pnl)}{_fmt_price(total_pnl)}</div>
        </div>
        <div class="card">
            <div class="card-label">Trades</div>
            <div class="card-value">{total_trades}</div>
        </div>
        <div class="card">
            <div class="card-label">Win Rate</div>
            <div class="card-value">{win_rate:.1f}%</div>
        </div>
        <div class="card">
            <div class="card-label">Avg Win</div>
            <div class="card-value" style="color:#4ade80;">{_fmt_price(avg_win)}</div>
        </div>
        <div class="card">
            <div class="card-label">Avg Loss</div>
            <div class="card-value" style="color:#f87171;">{_fmt_price(avg_loss)}</div>
        </div>
        <div class="card">
            <div class="card-label">Open Positions</div>
            <div class="card-value">{len(open_pos)}</div>
        </div>
        <div class="card">
            <div class="card-label">Swing Positions</div>
            <div class="card-value" style="color:#a78bfa;">{swing_count}</div>
        </div>
    </div>

    <div class="section">
        <h2>Equity Curve</h2>
        <div class="chart-container">
            <canvas id="equityChart"></canvas>
        </div>
    </div>

    <div class="section">
        <h2>Open Positions ({len(open_pos)})</h2>
        <div style="overflow-x:auto;">
            <table>
                <thead>
                    <tr>
                        <th>Symbol</th>
                        <th>Side</th>
                        <th>Entry Price</th>
                        <th>Qty</th>
                        <th>Stop Loss</th>
                        <th>Take Profit</th>
                        <th>Strategy</th>
                        <th>Mode</th>
                    </tr>
                </thead>
                <tbody>
                    {open_rows}
                </tbody>
            </table>
        </div>
    </div>

    <div class="section">
        <h2>Closed Trades ({total_trades})</h2>
        <div style="overflow-x:auto;">
            <table>
                <thead>
                    <tr>
                        <th>Symbol</th>
                        <th>Side</th>
                        <th>Entry</th>
                        <th>Exit</th>
                        <th>Qty</th>
                        <th>P&amp;L</th>
                        <th>%</th>
                        <th>Exit Reason</th>
                        <th>Strategy</th>
                        <th>Mode</th>
                    </tr>
                </thead>
                <tbody>
                    {closed_rows}
                </tbody>
            </table>
        </div>
    </div>

    <div class="footer">Last updated: {account.get('last_updated', 'N/A')}</div>

    <script src="https://cdn.jsdelivr.net/npm/chart.js@4/dist/chart.umd.min.js"></script>
    <script>
        (function() {{
            const labels = {chart_labels_js};
            const data = {chart_values_js};
            const ctx = document.getElementById('equityChart');
            if (!ctx) return;
            if (labels.length === 0) {{
                ctx.parentElement.innerHTML = '<p style="text-align:center;color:#64748b;padding:40px 0;">No daily summary data yet</p>';
                return;
            }}
            new Chart(ctx, {{
                type: 'line',
                data: {{
                    labels: labels,
                    datasets: [{{
                        label: 'Capital',
                        data: data,
                        borderColor: '#6366f1',
                        backgroundColor: 'rgba(99, 102, 241, 0.15)',
                        fill: true,
                        tension: 0.3,
                        pointRadius: 3,
                        pointBackgroundColor: '#6366f1',
                        borderWidth: 2,
                    }}]
                }},
                options: {{
                    responsive: true,
                    maintainAspectRatio: false,
                    plugins: {{
                        legend: {{ display: false }},
                        tooltip: {{
                            callbacks: {{
                                label: function(ctx) {{
                                    return '\\u20B9' + ctx.parsed.y.toLocaleString('en-IN', {{ minimumFractionDigits: 2 }});
                                }}
                            }}
                        }}
                    }},
                    scales: {{
                        x: {{
                            ticks: {{ color: '#94a3b8', maxRotation: 45 }},
                            grid: {{ color: 'rgba(51,65,85,0.4)' }}
                        }},
                        y: {{
                            ticks: {{
                                color: '#94a3b8',
                                callback: function(v) {{ return '\\u20B9' + v.toLocaleString('en-IN'); }}
                            }},
                            grid: {{ color: 'rgba(51,65,85,0.4)' }}
                        }}
                    }}
                }}
            }});
        }})();
    </script>
</body>
</html>"""

    return Response(html, content_type="text/html; charset=utf-8")


if __name__ == "__main__":
    port = int(os.environ.get("DASHBOARD_PORT", 8050))
    app.run(host="0.0.0.0", port=port, debug=False)
