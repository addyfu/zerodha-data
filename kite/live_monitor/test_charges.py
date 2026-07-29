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

    2026-07-29: paper fills are now slipped 0.05%/side (paper_slippage_pct),
    so the buy/sell values charges are computed on are the SLIPPED prices,
    not the quoted 1000.0/1010.0 handed to the signal. That slip step is
    mirrored here with the exact formula paper_trader.py uses — this test's
    job is to isolate the CHARGES formula (its actual purpose), not to
    re-derive slippage (test_slippage_applied_both_directions owns that).
    """
    t = _trader(tmp, 'long.db')
    quoted_entry, quoted_exit, qty = 1000.0, 1010.0, 20
    slip = zerodha_charges.paper_slippage_pct
    entry = quoted_entry * (1 + slip)   # BUY entry slips up:   1000.5
    exit_px = quoted_exit * (1 - slip)  # BUY exit slips down:  1009.495
    t.open_position(_Signal('TESTLONG', 'BUY', quoted_entry, qty))
    pos = t.close_position('TESTLONG', quoted_exit, ExitReason.TAKE_PROFIT)

    buy_value, sell_value = entry * qty, exit_px * qty              # 20010, 20189.9
    # Hand-computed, Zerodha equity INTRADAY (rates verified 2026-07-26):
    brokerage = min(buy_value * 0.0003, 20) + min(sell_value * 0.0003, 20)   # 12.060
    stt = sell_value * 0.00025                                               #  5.047
    exchange = (buy_value + sell_value) * 0.0000297   # NSE Rs 2.97/lakh      #  1.194
    sebi = (buy_value + sell_value) * 0.000001        # Rs 10/crore           #  0.040
    gst = (brokerage + exchange + sebi) * 0.18        # SEBI is in the base   #  2.393
    stamp = buy_value * 0.00003                       # intraday 0.003%       #  0.600
    expected_chg = brokerage + stt + exchange + gst + sebi + stamp           # 21.335
    expected_gross = (exit_px - entry) * qty                                 # 179.9

    assert abs(expected_chg - 21.3348) < 0.01, f'test arithmetic drifted: {expected_chg}'
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
    quoted_entry, quoted_exit, qty = 500.0, 490.0, 40
    slip = zerodha_charges.paper_slippage_pct
    # SELL entry slips down, SELL exit slips up (2026-07-29 paper_slippage_pct) —
    # same worsening direction as test_slippage_worsens_never_improves checks directly.
    expected_gross = (quoted_entry * (1 - slip) - quoted_exit * (1 + slip)) * qty
    t.open_position(_Signal('TESTSHORT', 'SELL', quoted_entry, qty))
    pos = t.close_position('TESTSHORT', quoted_exit, ExitReason.TAKE_PROFIT)
    assert abs(pos.gross_pnl - expected_gross) < 1e-6, (pos.gross_pnl, expected_gross)
    assert 0 < pos.pnl < pos.gross_pnl, (pos.pnl, pos.gross_pnl)
    return f'short gross +{expected_gross:.2f} -> net {pos.pnl:+.2f}'


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


def test_exit_reason_labels(tmp):
    """2026-07-27 label fix: trailing_stop is initialized == stop_loss at entry,
    so the old `if position.trailing_stop` ternary was always truthy and every
    plain stop-loss exit got mislabeled as trailing_stop. A stop exit is only
    TRAILING_STOP if the trail actually ratcheted away from the original stop.
    Exit price/timing/P&L logic is untouched by the fix; only the label.
    """
    t = PaperTrader(initial_capital=100000, max_positions=5,
                     db_path=str(Path(tmp) / 'exit_reason.db'),
                     use_trailing_stop=True, trailing_stop_pct=0.02)

    # Position 1: price falls straight through, trail never ratchets -> STOP_LOSS.
    t.open_position(_Signal('LBL1', 'BUY', 100.0, 10))   # stop_loss=99.0, take_profit=102.0
    closed = t.check_exits({'LBL1': 98.5})
    assert len(closed) == 1, closed
    pos1 = closed[0]
    assert pos1.exit_reason == ExitReason.STOP_LOSS.value, pos1.exit_reason
    assert pos1.pnl < 0, pos1.pnl

    # Position 2: favorable move ratchets the trail to 100.94, then price falls
    # back through the ratcheted trail while staying above the original 99.0
    # stop -> TRAILING_STOP.
    sig2 = _Signal('LBL2', 'BUY', 100.0, 10)
    sig2.take_profit = 120.0   # keep target out of reach so the favorable leg can't close it
    t.open_position(sig2)
    closed = t.check_exits({'LBL2': 103.0})     # ratchets trailing_stop to 103.0*0.98=100.94
    assert closed == [], closed
    assert abs(t.positions['LBL2'].trailing_stop - 100.94) < 1e-6, t.positions['LBL2'].trailing_stop
    closed = t.check_exits({'LBL2': 100.5})     # above original stop 99.0, below ratcheted 100.94
    assert len(closed) == 1, closed
    pos2 = closed[0]
    assert pos2.exit_reason == ExitReason.TRAILING_STOP.value, pos2.exit_reason
    assert pos2.exit_price > pos2.entry_price, (pos2.exit_price, pos2.entry_price)
    assert pos2.pnl > 0, pos2.pnl

    return f'stop_loss pnl {pos1.pnl:+.2f} | trailing_stop pnl {pos2.pnl:+.2f}'


def test_daily_summary_backfill(tmp):
    """daily_summary accumulates position.pnl per close (paper_trader
    ._update_daily_summary): rows written before the 2026-07-26 net-of-charges
    fix hold GROSS pnl for that day, rows written after hold NET — two
    meanings in one column. rebuild_daily_summary must restore the true net
    values from the positions table, and be a no-op the second time round.
    """
    import sqlite3
    db = Path(tmp) / 'daily.db'
    t = _trader(tmp, 'daily.db')
    t.open_position(_Signal('DSWIN', 'BUY', 1000.0, 20))
    t.close_position('DSWIN', 1010.0, ExitReason.TAKE_PROFIT)
    t.open_position(_Signal('DSLOSE', 'BUY', 1000.0, 20))
    t.close_position('DSLOSE', 990.0, ExitReason.STOP_LOSS)
    # A position entered TODAY that stays open past today. entry_time is
    # stored ISO-with-T; a raw string compare against "<date> 23:59:59"
    # silently drops same-day entries from open value ('T' > ' '), which is
    # exactly how the first version of the capital sub-query got it wrong.
    t.open_position(_Signal('DSHOLD', 'BUY', 500.0, 10))

    conn = sqlite3.connect(db)
    today = datetime.now().strftime('%Y-%m-%d')
    # Recompute expected values from positions directly, not from the
    # daily_summary row the app itself wrote (that row is exactly what this
    # test is trying to independently verify).
    expected_trades, expected_wins, expected_losses, expected_pnl = conn.execute(
        "SELECT COUNT(*), SUM(pnl > 0), SUM(pnl < 0), SUM(pnl) FROM positions "
        "WHERE status = 'closed'").fetchone()
    initial_capital = conn.execute(
        "SELECT initial_capital FROM account ORDER BY id DESC LIMIT 1").fetchone()[0]
    open_value = conn.execute(
        "SELECT COALESCE(SUM(entry_price * quantity), 0) FROM positions "
        "WHERE status = 'open'").fetchone()[0]
    # DSHOLD must be counted. entry_price is the SLIPPED fill (2026-07-29
    # paper_slippage_pct), not the quoted 500.0 handed to the signal.
    expected_open_value = 500.0 * (1 + zerodha_charges.paper_slippage_pct) * 10
    assert abs(open_value - expected_open_value) < 1e-6, (open_value, expected_open_value)
    expected_capital = initial_capital - open_value + expected_pnl

    # Corrupt the row to simulate a gross-era write: net + 500 in both cols.
    conn.execute("UPDATE daily_summary SET pnl = pnl + 500, capital = capital + 500 "
                 "WHERE date = ?", (today,))
    conn.commit()
    corrupted_pnl = conn.execute(
        "SELECT pnl FROM daily_summary WHERE date = ?", (today,)).fetchone()[0]
    assert abs(corrupted_pnl - (expected_pnl + 500)) < 1e-6, corrupted_pnl

    from kite.live_monitor.backfill_charges import rebuild_daily_summary
    repaired = rebuild_daily_summary('T', db, dry_run=False)
    assert repaired == 1, repaired

    row = conn.execute(
        "SELECT trades, wins, losses, pnl, capital FROM daily_summary WHERE date = ?",
        (today,)).fetchone()
    assert (row[0], row[1], row[2]) == (expected_trades, expected_wins, expected_losses), row
    assert abs(row[3] - expected_pnl) < 1e-6, (row[3], expected_pnl)
    assert abs(row[4] - expected_capital) < 1e-6, (row[4], expected_capital)

    repaired_again = rebuild_daily_summary('T', db, dry_run=False)
    conn.close()
    assert repaired_again == 0, repaired_again
    return (f'corrupted pnl {corrupted_pnl:+.2f} -> restored {row[3]:+.2f} '
            f'(2nd run repaired {repaired_again})')


def test_slippage_applied_both_directions(tmp):
    """2026-07-29: paper fills are slipped 0.05%/side (kite/config.py
    ZerodhaCharges.paper_slippage_pct) at both open_position and
    close_position, matching every backtest/expectation card's assumption.
    Hand-computed expected prices for all four legs: BUY entry/exit and
    SELL entry/exit.
    """
    slip = zerodha_charges.paper_slippage_pct
    assert abs(slip - 0.0005) < 1e-12, f'test assumes 0.05% — config drifted to {slip}'

    t = _trader(tmp, 'slip_buy.db')
    quoted_entry, quoted_exit, qty = 1000.0, 1010.0, 20
    pos = t.open_position(_Signal('SLIPBUY', 'BUY', quoted_entry, qty))
    expected_entry = quoted_entry * (1 + slip)   # BUY entry worsens UP: 1000.50
    assert abs(pos.entry_price - expected_entry) < 1e-9, (pos.entry_price, expected_entry)
    closed = t.close_position('SLIPBUY', quoted_exit, ExitReason.TAKE_PROFIT)
    expected_exit = quoted_exit * (1 - slip)     # BUY exit worsens DOWN: 1009.495
    assert abs(closed.exit_price - expected_exit) < 1e-9, (closed.exit_price, expected_exit)

    t2 = _trader(tmp, 'slip_sell.db')
    quoted_entry_s, quoted_exit_s = 500.0, 490.0
    pos_s = t2.open_position(_Signal('SLIPSELL', 'SELL', quoted_entry_s, qty))
    expected_entry_s = quoted_entry_s * (1 - slip)   # SELL entry worsens DOWN: 499.75
    assert abs(pos_s.entry_price - expected_entry_s) < 1e-9, (pos_s.entry_price, expected_entry_s)
    closed_s = t2.close_position('SLIPSELL', quoted_exit_s, ExitReason.TAKE_PROFIT)
    expected_exit_s = quoted_exit_s * (1 + slip)     # SELL exit worsens UP: 490.245
    assert abs(closed_s.exit_price - expected_exit_s) < 1e-9, (closed_s.exit_price, expected_exit_s)

    return (f'BUY entry {quoted_entry}->{pos.entry_price:.3f}, exit {quoted_exit}->{closed.exit_price:.3f} | '
            f'SELL entry {quoted_entry_s}->{pos_s.entry_price:.3f}, exit {quoted_exit_s}->{closed_s.exit_price:.3f}')


def test_slippage_worsens_never_improves(tmp):
    """The slipped fill must always be worse than the quoted price for the
    position holder — never better, in either direction, on either leg."""
    t = _trader(tmp, 'slip_worse_buy.db')
    pos = t.open_position(_Signal('WORSEBUY', 'BUY', 1000.0, 10))
    assert pos.entry_price > 1000.0, 'BUY entry must be slipped UP (pay more), not improved'
    closed = t.close_position('WORSEBUY', 1050.0, ExitReason.TAKE_PROFIT)
    assert closed.exit_price < 1050.0, 'BUY exit must be slipped DOWN (receive less), not improved'

    t2 = _trader(tmp, 'slip_worse_sell.db')
    pos_s = t2.open_position(_Signal('WORSESELL', 'SELL', 1000.0, 10))
    assert pos_s.entry_price < 1000.0, 'SELL entry must be slipped DOWN (short at a worse price)'
    closed_s = t2.close_position('WORSESELL', 950.0, ExitReason.TAKE_PROFIT)
    assert closed_s.exit_price > 950.0, 'SELL exit (buy-to-cover) must be slipped UP (pay more)'

    return (f'BUY entry {pos.entry_price:.2f}>1000, exit {closed.exit_price:.2f}<1050 | '
            f'SELL entry {pos_s.entry_price:.2f}<1000, exit {closed_s.exit_price:.2f}>950')


def main():
    tests = [test_long_intraday_net_of_charges, test_short_direction_sign,
             test_delivery_costs_more_than_intraday, test_dp_charge_delivery_only,
             test_capital_reflects_net,
             test_persisted_columns_roundtrip, test_backfill_idempotent,
             test_dry_run_writes_nothing, test_open_positions_unaffected,
             test_exit_reason_labels, test_daily_summary_backfill,
             test_slippage_applied_both_directions, test_slippage_worsens_never_improves]
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
