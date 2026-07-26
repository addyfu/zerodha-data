"""Acceptance tests for net-of-charges P&L accounting (2026-07-26 fix).

Standalone: `python kite/live_monitor/test_charges.py` — plain asserts, no
pytest, no network. Every scenario runs against a throwaway sqlite file in a
temp dir, so the real books are never touched.
"""
import sys
import tempfile
from datetime import datetime
from pathlib import Path

_CODE_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(_CODE_ROOT))

from kite.config import zerodha_charges
from kite.live_monitor.paper_trader import PaperTrader, ExitReason, TradeMode


class _Signal:
    """Minimal stand-in for TradeSignal (open_position only reads attributes)."""
    def __init__(self, symbol, direction, entry, qty, mode='INTRADAY'):
        self.symbol = symbol
        self.direction = direction
        self.entry_price = entry
        self.stop_loss = entry * (0.99 if direction == 'BUY' else 1.01)
        self.take_profit = entry * (1.02 if direction == 'BUY' else 0.98)
        self.quantity = qty
        self.strategy = 'test_strategy'
        self.trade_mode = mode
        self.position_value = entry * qty


def _trader(tmp, name='book.db', capital=100000):
    return PaperTrader(initial_capital=capital, max_positions=5,
                       db_path=str(Path(tmp) / name), use_trailing_stop=False)


def test_long_intraday_net_of_charges(tmp):
    """Asserts the EXACT hand-computed charge, not just 'charges > 0'.

    The original version of this test compared against
    sum(calculate_charges(...).values()) — which is itself the double-counting
    bug (the dict carries its own 'total' alongside the six components), so a
    doubled charge passed happily. Hand-computed constants below are the only
    thing that catches that class of error.
    """
    t = _trader(tmp, 'long.db')
    entry, exit_px, qty = 1000.0, 1010.0, 20
    t.open_position(_Signal('TESTLONG', 'BUY', entry, qty))
    pos = t.close_position('TESTLONG', exit_px, ExitReason.TAKE_PROFIT)

    buy_value, sell_value = entry * qty, exit_px * qty              # 20000, 20200
    # Hand-computed, Zerodha equity INTRADAY (rates verified 2026-07-26):
    brokerage = min(buy_value * 0.0003, 20) + min(sell_value * 0.0003, 20)   # 12.06
    stt = sell_value * 0.00025                                               #  5.05
    exchange = (buy_value + sell_value) * 0.0000297   # NSE Rs 2.97/lakh      #  1.1939
    sebi = (buy_value + sell_value) * 0.000001        # Rs 10/crore           #  0.0402
    gst = (brokerage + exchange + sebi) * 0.18        # SEBI is in the base   #  2.3929
    stamp = buy_value * 0.00003                       # intraday 0.003%       #  0.60
    expected_chg = brokerage + stt + exchange + gst + sebi + stamp           # 21.337
    expected_gross = (exit_px - entry) * qty                                 # 200

    assert abs(expected_chg - 21.3371) < 0.01, f'test arithmetic drifted: {expected_chg}'
    assert abs(pos.gross_pnl - expected_gross) < 1e-6, pos.gross_pnl
    assert abs(pos.charges - expected_chg) < 1e-4, (
        f'charges {pos.charges:.4f} != hand-computed {expected_chg:.4f} '
        f'(ratio {pos.charges / expected_chg:.2f}x — 2.00x means the '
        f"sum(values()) double-count is back)")
    assert abs(pos.pnl - (expected_gross - expected_chg)) < 1e-4, pos.pnl
    return f'gross {expected_gross:+.2f} - charges {expected_chg:.2f} = net {pos.pnl:+.2f}'


def test_short_direction_sign(tmp):
    """A profitable SHORT must still be net-positive-but-reduced, not inverted."""
    t = _trader(tmp, 'short.db')
    entry, exit_px, qty = 500.0, 490.0, 40
    t.open_position(_Signal('TESTSHORT', 'SELL', entry, qty))
    pos = t.close_position('TESTSHORT', exit_px, ExitReason.TAKE_PROFIT)
    assert abs(pos.gross_pnl - 400.0) < 1e-6, pos.gross_pnl
    assert 0 < pos.pnl < pos.gross_pnl, (pos.pnl, pos.gross_pnl)
    return f'short gross +400.00 -> net {pos.pnl:+.2f}'


def test_delivery_costs_more_than_intraday(tmp):
    """ROTATION/SWING hold overnight -> delivery STT on BOTH legs -> pricier."""
    intraday = _trader(tmp, 'intra.db')
    intraday.open_position(_Signal('AAA', 'BUY', 1000.0, 20, mode='INTRADAY'))
    p_intra = intraday.close_position('AAA', 1010.0, ExitReason.END_OF_DAY)

    delivery = _trader(tmp, 'deliv.db')
    delivery.open_position(_Signal('AAA', 'BUY', 1000.0, 20, mode='ROTATION'))
    p_deliv = delivery.close_position('AAA', 1010.0, ExitReason.STRATEGY_EXIT)

    assert p_deliv.charges > p_intra.charges, (p_deliv.charges, p_intra.charges)
    assert p_intra.gross_pnl == p_deliv.gross_pnl, 'same trade, same gross'
    return f'intraday {p_intra.charges:.2f} < delivery {p_deliv.charges:.2f}'


def test_dp_charge_delivery_only(tmp):
    """DP (depository) charge: flat Rs 13.5 + GST per delivery SELL, never on
    intraday (nothing leaves the demat account). Missing entirely until
    2026-07-26, which understated every swing/rotation trade by ~36%."""
    intraday = zerodha_charges.calculate_charges(20000, 20200, is_intraday=True)
    delivery = zerodha_charges.calculate_charges(20000, 20200, is_intraday=False)
    assert intraday['dp'] == 0.0, intraday['dp']
    assert abs(delivery['dp'] - 13.5) < 1e-9, delivery['dp']
    # GST must be levied on the DP charge too. Check the base directly rather
    # than comparing the two modes — delivery has zero brokerage while intraday
    # has ~12, so their GST bases are not a simple offset (an earlier version of
    # this assertion made exactly that mistake).
    expected_gst = (delivery['brokerage'] + delivery['exchange']
                    + delivery['sebi'] + delivery['dp']) * 0.18
    assert abs(delivery['gst'] - expected_gst) < 1e-6, (delivery['gst'], expected_gst)
    assert delivery['gst'] > 13.5 * 0.18, 'GST base must include the DP charge'
    # Flat fee => strictly worse in % terms for smaller positions
    small = zerodha_charges.calculate_charges(19000, 19190, is_intraday=False)
    big = zerodha_charges.calculate_charges(150000, 151500, is_intraday=False)
    assert small['total'] / 19000 > big['total'] / 150000, 'flat DP must bite small harder'
    return (f"intraday dp 0.00 | delivery dp 13.50 | "
            f"small {small['total']/19000*100:.3f}% > big {big['total']/150000*100:.3f}%")


def test_capital_reflects_net(tmp):
    """Capital must move by NET, otherwise the book slowly invents money."""
    t = _trader(tmp, 'cap.db', capital=100000)
    start = t.capital
    t.open_position(_Signal('CAPTEST', 'BUY', 1000.0, 15))
    pos = t.close_position('CAPTEST', 1005.0, ExitReason.TAKE_PROFIT)
    assert abs((t.capital - start) - pos.pnl) < 1e-6, (t.capital - start, pos.pnl)
    return f'capital moved {t.capital - start:+.2f} == net pnl {pos.pnl:+.2f}'


def test_persisted_columns_roundtrip(tmp):
    """gross_pnl/charges must survive the DB write (not just live objects)."""
    import sqlite3
    db = Path(tmp) / 'persist.db'
    t = _trader(tmp, 'persist.db')
    t.open_position(_Signal('PERSIST', 'BUY', 800.0, 25))
    pos = t.close_position('PERSIST', 812.0, ExitReason.TAKE_PROFIT)
    row = sqlite3.connect(db).execute(
        "SELECT gross_pnl, charges, pnl FROM positions WHERE symbol='PERSIST'").fetchone()
    assert abs(row[0] - pos.gross_pnl) < 1e-6, row
    assert abs(row[1] - pos.charges) < 1e-6, row
    assert abs(row[2] - pos.pnl) < 1e-6, row
    return f'db row gross {row[0]:+.2f} charges {row[1]:.2f} net {row[2]:+.2f}'


def test_backfill_idempotent(tmp):
    """Backfilling twice must not double-charge."""
    import sqlite3
    import subprocess
    db = Path(tmp) / 'backfill.db'
    t = _trader(tmp, 'backfill.db')
    t.open_position(_Signal('BF', 'BUY', 1000.0, 20))
    t.close_position('BF', 1010.0, ExitReason.TAKE_PROFIT)
    # Simulate a legacy gross-only row: wipe the charge columns.
    conn = sqlite3.connect(db)
    conn.execute("UPDATE positions SET pnl = 200.0, gross_pnl = 0, charges = 0")
    conn.commit()

    from kite.live_monitor.backfill_charges import backfill
    backfill('T', db, dry_run=False)
    after_one = conn.execute("SELECT pnl, charges FROM positions").fetchone()
    backfill('T', db, dry_run=False)          # second run must be a no-op
    after_two = conn.execute("SELECT pnl, charges FROM positions").fetchone()
    conn.close()
    assert after_one[1] > 0, after_one
    assert abs(after_one[0] - after_two[0]) < 1e-9, (after_one, after_two)
    return f'first run net {after_one[0]:+.2f}, second run unchanged'


def test_dry_run_writes_nothing(tmp):
    import sqlite3
    db = Path(tmp) / 'dry.db'
    t = _trader(tmp, 'dry.db')
    t.open_position(_Signal('DRY', 'BUY', 1000.0, 20))
    t.close_position('DRY', 1010.0, ExitReason.TAKE_PROFIT)
    conn = sqlite3.connect(db)
    conn.execute("UPDATE positions SET pnl = 200.0, gross_pnl = 0, charges = 0")
    conn.commit()
    before = conn.execute("SELECT pnl, charges FROM positions").fetchone()

    from kite.live_monitor.backfill_charges import backfill
    backfill('T', db, dry_run=True)
    after = conn.execute("SELECT pnl, charges FROM positions").fetchone()
    conn.close()
    assert before == after, (before, after)
    return 'dry run left the row untouched'


def test_open_positions_unaffected(tmp):
    """Charges apply at close only — an open position must book nothing."""
    t = _trader(tmp, 'open.db')
    pos = t.open_position(_Signal('OPENPOS', 'BUY', 1000.0, 15))
    assert pos.charges == 0.0 and pos.gross_pnl == 0.0, (pos.charges, pos.gross_pnl)
    assert 'OPENPOS' in t.positions
    return 'open position carries no charges until it closes'


def main():
    tests = [test_long_intraday_net_of_charges, test_short_direction_sign,
             test_delivery_costs_more_than_intraday, test_dp_charge_delivery_only,
             test_capital_reflects_net,
             test_persisted_columns_roundtrip, test_backfill_idempotent,
             test_dry_run_writes_nothing, test_open_positions_unaffected]
    passed = failed = 0
    print('=' * 78)
    for fn in tests:
        with tempfile.TemporaryDirectory() as tmp:
            try:
                detail = fn(tmp)
                print(f'PASS  {fn.__name__:42} {detail}')
                passed += 1
            except Exception as e:
                print(f'FAIL  {fn.__name__:42} {type(e).__name__}: {e}')
                failed += 1
    print('=' * 78)
    print(f'{passed}/{passed + failed} scenarios passed.')
    return 1 if failed else 0


if __name__ == '__main__':
    sys.exit(main())
