"""Acceptance tests for the entry-pipeline kill switch (2026-07-29 circuit
breaker vs runaway-loop bugs — see entry_pipeline.py module docstring and
kite/config.py TradingConfig.max_entries_per_day_*).

Standalone: `python kite/live_monitor/test_entry_pipeline.py` — plain
asserts, no pytest, no network. Every scenario runs against throwaway sqlite
(PaperTrader) and JSON (kill switch counter) files in a temp dir, so the real
books and data/entry_kill_switch.json are never touched. Matches the house
style of test_charges.py.
"""
import sys
import tempfile
from pathlib import Path

_CODE_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(_CODE_ROOT))

from kite.config import trading_config
from kite.live_monitor.entry_pipeline import EntryPipeline
from kite.live_monitor.paper_trader import PaperTrader, ExitReason
from kite.live_monitor.telegram_bot import TelegramBot


class _Signal:
    """Minimal stand-in for TradeSignal (open_position/try_enter only read attributes)."""
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


class _StubAnnFilter:
    """Always-clear red-flag filter -- these tests are about the kill switch
    gate only, not the announcement gate."""
    def is_flagged(self, symbol):
        return None


def _pipeline(tmp, kill_switch_file=None):
    """EntryPipeline pointed at an isolated counter file. offline=True so the
    late-entry-cutoff gate (15:05 IST) never interferes regardless of when
    this test happens to run."""
    kf = kill_switch_file or (Path(tmp) / 'entry_kill_switch.json')
    return EntryPipeline(_StubAnnFilter(), TelegramBot(), offline=True, kill_switch_file=kf)


def _trader(tmp, name='book.db', capital=10_000_000, max_positions=1000):
    """Deep bench (huge capital/max_positions) so PaperTrader's OWN gates
    never trip before the kill switch does -- these tests want to isolate
    the kill switch's cap, not paper_trader.py's slot/capital gates."""
    return PaperTrader(initial_capital=capital, max_positions=max_positions,
                       db_path=str(Path(tmp) / name), use_trailing_stop=False)


def test_kill_switch_blocks_after_cap(tmp):
    """Simulates cap+1 opens on a temp book: exactly `cap` succeed, and the
    (cap+1)th is refused cleanly -- no exception, no position opened."""
    ep = _pipeline(tmp)
    trader = _trader(tmp)
    cap = trading_config.max_entries_per_day_main
    opened = 0
    for i in range(cap):
        sig = _Signal(f'SYM{i}', 'BUY', 100.0 + i, 1)
        pos = ep.try_enter(trader, sig, 'MAIN', 'main', alert=False)
        assert pos is not None, f'entry {i} should have succeeded (under cap {cap})'
        opened += 1
    assert opened == cap, (opened, cap)

    try:
        blocked = ep.try_enter(trader, _Signal('OVERCAP', 'BUY', 999.0, 1), 'MAIN', 'main', alert=False)
    except Exception as e:
        raise AssertionError(f'kill switch must never raise, got {type(e).__name__}: {e}')
    assert blocked is None, 'entry past the daily cap must be refused'
    assert len(trader.positions) == cap, 'the refused attempt must not have opened a position'
    return f'{opened}/{cap} opens allowed, entry #{cap + 1} refused without raising'


def test_kill_switch_never_blocks_exits(tmp):
    """Exits never pass through EntryPipeline (see its module docstring), so
    a fully tripped kill switch must not stop already-open positions from
    closing via PaperTrader.close_position -- the same call monitor.py's
    check_exits/close_eod_positions make, bypassing the pipeline entirely."""
    ep = _pipeline(tmp)
    trader = _trader(tmp)
    cap = trading_config.max_entries_per_day_main
    symbols = []
    for i in range(cap):
        pos = ep.try_enter(trader, _Signal(f'EX{i}', 'BUY', 100.0, 1), 'MAIN', 'main', alert=False)
        assert pos is not None
        symbols.append(pos.symbol)

    blocked = ep.try_enter(trader, _Signal('EXBLOCK', 'BUY', 100.0, 1), 'MAIN', 'main', alert=False)
    assert blocked is None, 'switch should be tripped by now'

    for sym in symbols:
        closed = trader.close_position(sym, 101.0, ExitReason.MANUAL)
        assert closed is not None, f'{sym} exit must succeed with the kill switch tripped'
    assert len(trader.positions) == 0, 'all positions should have closed'
    return f'kill switch tripped after {cap} opens; all {cap} exits still succeeded'


def test_kill_switch_persists_across_restart(tmp):
    """A brand-new EntryPipeline pointed at the same counter file must reload
    today's count -- a monitor restart mid-day must not reopen the door on a
    kill switch that was already tripped."""
    kf = Path(tmp) / 'entry_kill_switch.json'
    ep1 = _pipeline(tmp, kill_switch_file=kf)
    trader = _trader(tmp)
    cap = trading_config.max_entries_per_day_main
    for i in range(cap):
        pos = ep1.try_enter(trader, _Signal(f'R{i}', 'BUY', 100.0, 1), 'MAIN', 'main', alert=False)
        assert pos is not None
    assert kf.exists(), 'counter file should have been written on the first successful open'

    ep2 = _pipeline(tmp, kill_switch_file=kf)  # simulates process restart, same file
    blocked = ep2.try_enter(trader, _Signal('RESTART', 'BUY', 100.0, 1), 'MAIN', 'main', alert=False)
    assert blocked is None, 'restarted pipeline must reload the persisted count and keep blocking'
    return f'counter file persisted {cap} entries; reloaded instance still enforces the cap'


def main():
    tests = [test_kill_switch_blocks_after_cap, test_kill_switch_never_blocks_exits,
             test_kill_switch_persists_across_restart]
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
