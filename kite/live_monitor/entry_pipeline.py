"""EntryPipeline — the single gate every new position passes through.

Born from the thermo-nuclear review (2026-07-21): entry policy had scattered
across four scan flows in monitor.py, each guarding a different subset of
gates. All entry policy now lives here, in gate order:

    1. late-entry cutoff    (no fresh INTRADAY entries after 15:05)
    2. parity pause file    (data/strategies_paused.json — entries only)
    3. red-flag filter      (announcement categories with proven negative drift)
    4. book capacity etc.   (delegated to PaperTrader.open_position's own gates)

Adding a future gate = one edit here, covering every strategy automatically.
Exits NEVER pass through this class — pausing/blocking exits is forbidden.
"""
import json
import logging
from datetime import datetime, time as dtime
from pathlib import Path
from typing import Optional

from kite.live_monitor.paper_trader import PaperTrader, TradeMode

logger = logging.getLogger(__name__)

PAUSED_FILE = Path(__file__).resolve().parents[2] / 'data' / 'strategies_paused.json'
INTRADAY_ENTRY_CUTOFF = dtime(15, 5)


class EntryPipeline:
    def __init__(self, ann_filter, telegram, offline: bool = False):
        self.ann_filter = ann_filter
        self.telegram = telegram
        self.offline = offline
        self._paused: dict = {}

    def reload_paused(self):
        """Once per scan cycle — cheap, and mid-cycle consistency beats freshness."""
        try:
            self._paused = json.loads(PAUSED_FILE.read_text()) if PAUSED_FILE.exists() else {}
        except (OSError, ValueError) as e:
            logger.warning(f"Could not read {PAUSED_FILE.name}: {e} — treating none paused")
            self._paused = {}

    def try_enter(self, trader: PaperTrader, signal, source: str,
                  alert: bool = True) -> Optional[object]:
        """Run all entry gates; open the position if every gate passes.

        Returns the opened Position or None. `source` labels log/alert lines
        (e.g. 'INCUBATOR', 'CANDIDATE', 'ROTATION').
        """
        mode = TradeMode.of(signal.trade_mode)

        if mode.eod_squareoff and not self.offline \
                and datetime.now().time() >= INTRADAY_ENTRY_CUTOFF:
            logger.info(f"{source} gate: {signal.symbol} blocked — past intraday entry cutoff")
            return None

        if signal.strategy in self._paused:
            logger.info(f"{source} gate: {signal.symbol} [{signal.strategy}] blocked — "
                        f"strategy paused ({self._paused[signal.strategy].get('reason', '?')})")
            return None

        flag = self.ann_filter.is_flagged(signal.symbol)
        if flag:
            logger.info(f"{source} gate: {signal.symbol} [{signal.strategy}] blocked — red flag {flag}")
            return None

        position = trader.open_position(signal)
        if position:
            logger.info(f"{source} [{signal.strategy}]: {signal.direction} {signal.symbol} "
                        f"@ Rs {signal.entry_price:.2f}")
            if alert:
                self.telegram.send_message(
                    f"[{source}] {signal.strategy}: {signal.direction} {signal.symbol} "
                    f"@ Rs {signal.entry_price:.2f} (paper)")
        return position
