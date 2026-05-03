# Trading Dashboard Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build a real-time web dashboard to view paper trading P&L, open positions, closed trades, and equity curve — deployed on Oracle ARM alongside the existing kite-monitor service.

**Architecture:** Single-file Flask app that reads from the existing `paper_trades.db` SQLite database (read-only, no writes). Serves a dark-themed HTML page with auto-refresh via meta tag. No JS framework — vanilla HTML/CSS with inline `<script>` for the equity chart using lightweight Chart.js CDN.

**Tech Stack:** Flask, SQLite3 (read-only), HTML/CSS (dark theme), Chart.js (CDN), systemd service on Oracle ARM.

---

## File Structure

| File | Responsibility |
|------|---------------|
| `kite/live_monitor/dashboard.py` | Flask app — routes, DB queries, HTML rendering |
| `requirements.txt` | Add `flask` dependency (uncomment existing line) |

Everything in one file. DB schema already exists in `paper_trades.db` with tables: `positions`, `account`, `daily_summary`.

## Instance Details

- **IP**: 80.225.202.32
- **SSH Key**: `C:/Users/pc/Downloads/ssh-key-2026-04-24.key`
- **Existing services**: kite-monitor (no port), polymarket (port 8088)
- **Dashboard port**: 8050
- **DB path on Oracle**: `/home/ubuntu/projects/kite-monitor/data/paper_trades.db`

---

### Task 1: Build the Flask Dashboard App

**Files:**
- Create: `kite/live_monitor/dashboard.py`

- [ ] **Step 1: Create the Flask app with DB helper**

```python
"""
Paper Trading Dashboard
=======================
Read-only web dashboard for the kite paper trading monitor.
Reads from paper_trades.db and displays P&L, positions, trades.
"""
import sqlite3
import os
from datetime import datetime
from flask import Flask, Response

app = Flask(__name__)

DB_PATH = os.environ.get(
    "DASHBOARD_DB_PATH",
    os.path.join(os.path.dirname(__file__), "..", "..", "data", "paper_trades.db")
)


def get_db():
    conn = sqlite3.connect(DB_PATH, check_same_thread=False)
    conn.row_factory = sqlite3.Row
    return conn


def query_account():
    conn = get_db()
    row = conn.execute("SELECT capital, initial_capital, trade_counter, last_updated FROM account ORDER BY id DESC LIMIT 1").fetchone()
    conn.close()
    if not row:
        return {"capital": 0, "initial_capital": 100000, "trade_counter": 0, "last_updated": ""}
    return dict(row)


def query_open_positions():
    conn = get_db()
    rows = conn.execute(
        "SELECT symbol, direction, entry_price, quantity, stop_loss, take_profit, "
        "strategy, entry_time, trailing_stop FROM positions WHERE status='open' ORDER BY entry_time DESC"
    ).fetchall()
    conn.close()
    return [dict(r) for r in rows]


def query_closed_trades():
    conn = get_db()
    rows = conn.execute(
        "SELECT symbol, direction, entry_price, exit_price, quantity, pnl, pnl_pct, "
        "exit_reason, strategy, entry_time, exit_time FROM positions WHERE status='closed' ORDER BY exit_time DESC"
    ).fetchall()
    conn.close()
    return [dict(r) for r in rows]


def query_daily_summary():
    conn = get_db()
    rows = conn.execute(
        "SELECT date, trades, wins, losses, pnl, capital FROM daily_summary ORDER BY date"
    ).fetchall()
    conn.close()
    return [dict(r) for r in rows]
```

- [ ] **Step 2: Add the HTML rendering route**

Add the main route to `dashboard.py` that returns the full HTML page. This is a large block — the entire UI is server-rendered HTML with inline CSS and JS.

```python
@app.route("/")
def index():
    account = query_account()
    positions = query_open_positions()
    closed = query_closed_trades()
    daily = query_daily_summary()

    capital = account["capital"]
    initial = account["initial_capital"]
    total_pnl = capital - initial
    pnl_pct = (total_pnl / initial * 100) if initial else 0

    wins = sum(1 for t in closed if t["pnl"] > 0)
    losses = sum(1 for t in closed if t["pnl"] < 0)
    total_trades = len(closed)
    win_rate = (wins / total_trades * 100) if total_trades else 0
    avg_win = sum(t["pnl"] for t in closed if t["pnl"] > 0) / wins if wins else 0
    avg_loss = sum(t["pnl"] for t in closed if t["pnl"] < 0) / losses if losses else 0

    pnl_color = "#4ade80" if total_pnl >= 0 else "#f87171"

    # Build positions table rows
    pos_rows = ""
    for p in positions:
        pos_rows += f"""<tr>
            <td>{p['symbol']}</td>
            <td class="{'buy' if p['direction']=='BUY' else 'sell'}">{p['direction']}</td>
            <td>₹{p['entry_price']:,.2f}</td>
            <td>{p['quantity']}</td>
            <td>₹{p['stop_loss']:,.2f}</td>
            <td>₹{p['take_profit']:,.2f}</td>
            <td><span class="badge">{p['strategy']}</span></td>
        </tr>"""

    if not positions:
        pos_rows = '<tr><td colspan="7" class="empty">No open positions</td></tr>'

    # Build closed trades rows
    trade_rows = ""
    for t in closed:
        pnl_cls = "profit" if t["pnl"] > 0 else "loss"
        trade_rows += f"""<tr>
            <td>{t['symbol']}</td>
            <td class="{'buy' if t['direction']=='BUY' else 'sell'}">{t['direction']}</td>
            <td>₹{t['entry_price']:,.2f}</td>
            <td>₹{t['exit_price']:,.2f}</td>
            <td>{t['quantity']}</td>
            <td class="{pnl_cls}">₹{t['pnl']:+,.2f}</td>
            <td class="{pnl_cls}">{t['pnl_pct']:+.2f}%</td>
            <td><span class="badge">{t['exit_reason']}</span></td>
            <td><span class="badge">{t['strategy']}</span></td>
        </tr>"""

    if not closed:
        trade_rows = '<tr><td colspan="9" class="empty">No closed trades yet</td></tr>'

    # Equity curve data
    equity_labels = [d["date"] for d in daily]
    equity_values = [d["capital"] for d in daily]
    if not equity_labels:
        equity_labels = [datetime.now().strftime("%Y-%m-%d")]
        equity_values = [initial]

    now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")

    html = f"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<meta http-equiv="refresh" content="30">
<title>Kite Paper Trader</title>
<script src="https://cdn.jsdelivr.net/npm/chart.js@4/dist/chart.umd.min.js"></script>
<style>
  * {{ margin: 0; padding: 0; box-sizing: border-box; }}
  body {{ background: #0f172a; color: #e2e8f0; font-family: 'Segoe UI', system-ui, sans-serif; padding: 20px; }}
  .header {{ display: flex; justify-content: space-between; align-items: center; margin-bottom: 24px; }}
  .header h1 {{ font-size: 1.5rem; color: #f8fafc; }}
  .header .updated {{ font-size: 0.8rem; color: #64748b; }}
  .cards {{ display: grid; grid-template-columns: repeat(auto-fit, minmax(180px, 1fr)); gap: 16px; margin-bottom: 24px; }}
  .card {{ background: #1e293b; border-radius: 12px; padding: 16px; border: 1px solid #334155; }}
  .card .label {{ font-size: 0.75rem; color: #94a3b8; text-transform: uppercase; letter-spacing: 0.05em; }}
  .card .value {{ font-size: 1.5rem; font-weight: 700; margin-top: 4px; color: #f8fafc; }}
  .card .value.profit {{ color: #4ade80; }}
  .card .value.loss {{ color: #f87171; }}
  .chart-box {{ background: #1e293b; border-radius: 12px; padding: 16px; border: 1px solid #334155; margin-bottom: 24px; }}
  .chart-box h2 {{ font-size: 1rem; color: #94a3b8; margin-bottom: 12px; }}
  table {{ width: 100%; border-collapse: collapse; }}
  th {{ text-align: left; padding: 10px 12px; font-size: 0.75rem; color: #64748b; text-transform: uppercase;
        letter-spacing: 0.05em; border-bottom: 1px solid #334155; }}
  td {{ padding: 10px 12px; font-size: 0.85rem; border-bottom: 1px solid #1e293b; }}
  tr:hover {{ background: #1e293b; }}
  .buy {{ color: #4ade80; font-weight: 600; }}
  .sell {{ color: #f87171; font-weight: 600; }}
  .profit {{ color: #4ade80; font-weight: 600; }}
  .loss {{ color: #f87171; font-weight: 600; }}
  .badge {{ background: #334155; color: #94a3b8; padding: 2px 8px; border-radius: 4px; font-size: 0.75rem; }}
  .section {{ background: #1e293b; border-radius: 12px; padding: 16px; border: 1px solid #334155; margin-bottom: 24px; }}
  .section h2 {{ font-size: 1rem; color: #94a3b8; margin-bottom: 12px; }}
  .empty {{ text-align: center; color: #475569; padding: 24px; }}
  .live-dot {{ display: inline-block; width: 8px; height: 8px; background: #4ade80; border-radius: 50%;
               margin-right: 6px; animation: pulse 2s infinite; }}
  @keyframes pulse {{ 0%,100% {{ opacity: 1; }} 50% {{ opacity: 0.3; }} }}
</style>
</head>
<body>
<div class="header">
  <h1><span class="live-dot"></span> Kite Paper Trader</h1>
  <span class="updated">Last refresh: {now} &middot; Auto-refresh 30s</span>
</div>

<div class="cards">
  <div class="card">
    <div class="label">Capital</div>
    <div class="value">&#8377;{capital:,.0f}</div>
  </div>
  <div class="card">
    <div class="label">P&amp;L</div>
    <div class="value {'profit' if total_pnl >= 0 else 'loss'}">&#8377;{total_pnl:+,.0f} ({pnl_pct:+.2f}%)</div>
  </div>
  <div class="card">
    <div class="label">Trades</div>
    <div class="value">{total_trades}</div>
  </div>
  <div class="card">
    <div class="label">Win Rate</div>
    <div class="value">{win_rate:.0f}%</div>
  </div>
  <div class="card">
    <div class="label">Avg Win</div>
    <div class="value profit">&#8377;{avg_win:+,.0f}</div>
  </div>
  <div class="card">
    <div class="label">Avg Loss</div>
    <div class="value loss">&#8377;{avg_loss:,.0f}</div>
  </div>
  <div class="card">
    <div class="label">Open</div>
    <div class="value">{len(positions)}</div>
  </div>
</div>

<div class="chart-box">
  <h2>Equity Curve</h2>
  <canvas id="equity" height="80"></canvas>
</div>

<div class="section">
  <h2>Open Positions ({len(positions)})</h2>
  <table>
    <thead><tr><th>Symbol</th><th>Side</th><th>Entry</th><th>Qty</th><th>SL</th><th>TP</th><th>Strategy</th></tr></thead>
    <tbody>{pos_rows}</tbody>
  </table>
</div>

<div class="section">
  <h2>Closed Trades ({total_trades})</h2>
  <table>
    <thead><tr><th>Symbol</th><th>Side</th><th>Entry</th><th>Exit</th><th>Qty</th><th>P&amp;L</th><th>%</th><th>Exit</th><th>Strategy</th></tr></thead>
    <tbody>{trade_rows}</tbody>
  </table>
</div>

<script>
new Chart(document.getElementById('equity'), {{
  type: 'line',
  data: {{
    labels: {equity_labels},
    datasets: [{{
      label: 'Capital',
      data: {equity_values},
      borderColor: '#6366f1',
      backgroundColor: 'rgba(99,102,241,0.1)',
      fill: true,
      tension: 0.3,
      pointRadius: 3,
      pointBackgroundColor: '#6366f1'
    }}]
  }},
  options: {{
    responsive: true,
    plugins: {{ legend: {{ display: false }} }},
    scales: {{
      x: {{ ticks: {{ color: '#64748b' }}, grid: {{ color: '#1e293b' }} }},
      y: {{ ticks: {{ color: '#64748b', callback: v => '₹' + v.toLocaleString() }}, grid: {{ color: '#334155' }} }}
    }}
  }}
}});
</script>
</body>
</html>"""
    return Response(html, content_type="text/html; charset=utf-8")


if __name__ == "__main__":
    port = int(os.environ.get("DASHBOARD_PORT", 8050))
    app.run(host="0.0.0.0", port=port)
```

- [ ] **Step 3: Test locally**

Run: `cd D:\study\kite && python -m kite.live_monitor.dashboard`
Expected: Flask starts on port 8050. Open `http://localhost:8050` — dark dashboard loads with current DB data.

- [ ] **Step 4: Commit**

```bash
git add kite/live_monitor/dashboard.py
git commit -m "feat: add paper trading web dashboard"
```

---

### Task 2: Update requirements.txt

**Files:**
- Modify: `requirements.txt`

- [ ] **Step 1: Uncomment flask dependency**

Change the optional flask lines from commented to active:

```
flask>=2.3.0
```

- [ ] **Step 2: Commit**

```bash
git add requirements.txt
git commit -m "chore: add flask to requirements"
```

---

### Task 3: Deploy Dashboard to Oracle

**Files:**
- No local file changes — all remote operations

- [ ] **Step 1: Repackage and upload project**

```bash
cd D:\study\kite
tar -czf /tmp/kite-monitor.tar.gz --exclude='.git' --exclude='__pycache__' --exclude='venv' --exclude='node_modules' --exclude='TradingAgents' --exclude='data/*.db' --exclude='.specstory' -C . .

scp -i "C:/Users/pc/Downloads/ssh-key-2026-04-24.key" -o StrictHostKeyChecking=no /tmp/kite-monitor.tar.gz ubuntu@80.225.202.32:/tmp/
```

- [ ] **Step 2: Extract and install flask**

```bash
ssh ... "cd ~/projects/kite-monitor && tar -xzf /tmp/kite-monitor.tar.gz && source venv/bin/activate && pip install flask"
```

- [ ] **Step 3: Create systemd service for dashboard**

```bash
ssh ... "sudo tee /etc/systemd/system/kite-dashboard.service > /dev/null << 'UNIT'
[Unit]
Description=Kite Paper Trading Dashboard
After=network-online.target
Wants=network-online.target

[Service]
Type=simple
User=ubuntu
WorkingDirectory=/home/ubuntu/projects/kite-monitor
ExecStart=/home/ubuntu/projects/kite-monitor/venv/bin/python -m kite.live_monitor.dashboard
Restart=always
RestartSec=10
Environment=PYTHONUNBUFFERED=1
Environment=DASHBOARD_DB_PATH=/home/ubuntu/projects/kite-monitor/data/paper_trades.db
Environment=DASHBOARD_PORT=8050

[Install]
WantedBy=multi-user.target
UNIT
sudo systemctl daemon-reload && sudo systemctl enable kite-dashboard && sudo systemctl start kite-dashboard"
```

- [ ] **Step 4: Open port 8050 in iptables**

```bash
ssh ... "sudo iptables -I INPUT -p tcp --dport 8050 -j ACCEPT && sudo netfilter-persistent save"
```

- [ ] **Step 5: Open port 8050 in Oracle Cloud Security List**

Use OCI CLI to add ingress rule for TCP 8050 to the existing security list (same process used for port 8088).

- [ ] **Step 6: Verify deployment**

```bash
ssh ... "sudo systemctl status kite-dashboard --no-pager"
curl -s -o /dev/null -w "HTTP %{http_code}" http://80.225.202.32:8050/
```

Expected: service active, HTTP 200.

- [ ] **Step 7: Report dashboard URL to user**

Dashboard live at: `http://80.225.202.32:8050`
