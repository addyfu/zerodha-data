"""One-time backfill: recompute closed-trade P&L net of real Zerodha charges.

Context (2026-07-26): PaperTrader.close_position booked P&L as pure price
difference — no brokerage, STT, exchange charges, GST or stamp duty — while
every backtest and expectation card is net of the full charge stack. Live
results were therefore systematically flattered relative to the expectations
they are judged against.

close_position now charges correctly going forward. This script repairs the
history so the ledger is on one basis end to end. It is deterministic: entry
price, exit price, quantity and trade_mode are all stored, so the charge for
each historical trade is recomputed exactly, never estimated.

Idempotent: a row whose charges are already non-zero is left alone, so running
this twice cannot double-charge.

Usage:
    python kite/live_monitor/backfill_charges.py --dry-run   # report only
    python kite/live_monitor/backfill_charges.py             # apply
"""
import argparse
import sqlite3
import sys
from pathlib import Path

_CODE_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(_CODE_ROOT))

from kite.config import zerodha_charges
from kite.live_monitor.paper_trader import TradeMode

BOOKS = {
    'MAIN': _CODE_ROOT / 'data' / 'paper_trades.db',
    'INCUBATOR': _CODE_ROOT / 'data' / 'incubator_trades.db',
}


def ensure_columns(conn):
    """Additive migration, mirroring PaperTrader._init_database."""
    cur = conn.cursor()
    for col, decl in (('gross_pnl', 'REAL DEFAULT 0'), ('charges', 'REAL DEFAULT 0')):
        try:
            cur.execute(f"ALTER TABLE positions ADD COLUMN {col} {decl}")
        except sqlite3.OperationalError:
            pass
    conn.commit()


def backfill(label, db_path, dry_run):
    if not db_path.exists():
        print(f"{label}: {db_path.name} not found — skipped")
        return 0.0, 0.0, 0
    conn = sqlite3.connect(db_path)
    ensure_columns(conn)
    cur = conn.cursor()
    rows = cur.execute(
        "SELECT id, symbol, direction, entry_price, exit_price, quantity, "
        "       trade_mode, pnl, COALESCE(charges, 0) "
        "FROM positions WHERE status = 'closed' AND exit_price IS NOT NULL"
    ).fetchall()

    tot_gross = tot_chg = 0.0
    repaired = 0
    for pid, sym, direction, entry, exit_px, qty, mode, old_pnl, existing_chg in rows:
        if existing_chg:                      # already net — idempotent skip
            continue
        gross = ((exit_px - entry) if direction == 'BUY' else (entry - exit_px)) * qty
        buy_value, sell_value = entry * qty, exit_px * qty
        # ['total'], not sum(values()) — the dict carries its own total, so
        # summing values double-charges (see paper_trader.close_position note).
        charges = zerodha_charges.calculate_charges(
            buy_value, sell_value,
            is_intraday=TradeMode.of(mode).eod_squareoff)['total']
        net = gross - charges
        pct = net / buy_value * 100 if buy_value else 0.0
        tot_gross += gross
        tot_chg += charges
        repaired += 1
        if not dry_run:
            cur.execute(
                "UPDATE positions SET gross_pnl = ?, charges = ?, pnl = ?, pnl_pct = ? "
                "WHERE id = ?", (gross, charges, net, pct, pid))

    if not dry_run:
        conn.commit()
    conn.close()
    print(f"{label}: {repaired} trades repaired | gross {tot_gross:+,.0f} "
          f"| charges -{tot_chg:,.0f} | net {tot_gross - tot_chg:+,.0f}")
    return tot_gross, tot_chg, repaired


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--dry-run', action='store_true', help='report only, write nothing')
    args = ap.parse_args()

    print('DRY RUN — nothing will be written\n' if args.dry_run else 'APPLYING\n')
    g = c = n = 0.0
    for label, path in BOOKS.items():
        gg, cc, nn = backfill(label, path, args.dry_run)
        g += gg; c += cc; n += nn
    print(f"\nTOTAL: {int(n)} trades | gross {g:+,.0f} | charges -{c:,.0f} | NET {g - c:+,.0f}")
    if args.dry_run:
        print("Re-run without --dry-run to apply.")


if __name__ == '__main__':
    main()
