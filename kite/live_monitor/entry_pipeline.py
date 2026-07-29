"""EntryPipeline — the single gate every new position passes through.

Born from the thermo-nuclear review (2026-07-21): entry policy had scattered
across four scan flows in monitor.py, each guarding a different subset of
gates. All entry policy now lives here, in gate order:

    1. kill switch           (per-book daily entry cap — circuit breaker)
    2. late-entry cutoff     (no fresh INTRADAY entries after 15:05)
    3. parity pause file     (data/strategies_paused.json — entries only)
    4. red-flag filter       (announcement categories with proven negative drift)
    5. book capacity etc.    (delegated to PaperTrader.open_position's own gates)

Adding a future gate = one edit here, covering every strategy automatically.
Exits NEVER pass through this class — pausing/blocking exits is forbidden.

Kill switch (2026-07-29, r/algotrading corpus lesson / Knight-Capital class):
a runaway-loop bug that keeps re-entering is a much worse failure mode than a
day capped early, so each book (main/incubator — see kite/config.py
TradingConfig.max_entries_per_day_*) gets a generous daily cap on SUCCESSFUL
opens. Counts persist to a small JSON file so a monitor restart mid-day
doesn't quietly reset the counter and re-open the door. Never raises — a bug
in the kill switch itself must fail into refusing entries, not into crashing
the scan cycle.
"""
import json
import logging
from datetime import datetime, time as dtime
from pathlib import Path
from typing import Dict, Optional

from kite.config import trading_config
from kite.live_monitor.paper_trader import PaperTrader, TradeMode

logger = logging.getLogger(__name__)

PAUSED_FILE = Path(__file__).resolve().parents[2] / 'data' / 'strategies_paused.json'
INTRADAY_ENTRY_CUTOFF = dtime(15, 5)
KILL_SWITCH_FILE = Path(__file__).resolve().parents[2] / 'data' / 'entry_kill_switch.json'


class EntryPipeline:
    def __init__(self, ann_filter, telegram, offline: bool = False,
                 kill_switch_file: Optional[Path] = None):
        self.ann_filter = ann_filter
        self.telegram = telegram
        self.offline = offline
        self._paused: dict = {}
        # kill_switch_file override mirrors PaperTrader's own db_path override —
        # lets tests point at an isolated temp file instead of the real one.
        self._kill_switch_file = kill_switch_file or KILL_SWITCH_FILE
        self._entry_counts: Dict[str, dict] = self._load_kill_switch()  # book -> {'date', 'count'}
        self._kill_switch_alerted: set = set()  # books already CRITICAL-logged/alerted today

    def reload_paused(self):
        """Once per scan cycle — cheap, and mid-cycle consistency beats freshness."""
        try:
            self._paused = json.loads(PAUSED_FILE.read_text()) if PAUSED_FILE.exists() else {}
        except (OSError, ValueError) as e:
            logger.warning(f"Could not read {PAUSED_FILE.name}: {e} — treating none paused")
            self._paused = {}

    # -- Kill switch --------------------------------------------------------

    def _load_kill_switch(self) -> Dict[str, dict]:
        """Fail-soft load of persisted per-book entry counts; missing/corrupt
        file -> {} (counts start at zero, same as a fresh day)."""
        try:
            if self._kill_switch_file.exists():
                data = json.loads(self._kill_switch_file.read_text())
                if isinstance(data, dict):
                    return data
        except (OSError, ValueError) as e:
            logger.warning(f"Could not read {self._kill_switch_file.name}: {e} — "
                            f"starting entry counts at zero")
        return {}

    def _save_kill_switch(self) -> None:
        """Fail-soft persist; a write failure loses durability, not the in-memory count."""
        try:
            self._kill_switch_file.parent.mkdir(parents=True, exist_ok=True)
            self._kill_switch_file.write_text(json.dumps(self._entry_counts, indent=2, sort_keys=True))
        except OSError as e:
            logger.warning(f"Could not persist {self._kill_switch_file.name}: {e}")

    def _entries_today(self, book: str) -> int:
        today = datetime.now().strftime('%Y-%m-%d')
        rec = self._entry_counts.get(book)
        if not rec or rec.get('date') != today:
            return 0
        return rec.get('count', 0)

    def _bump_entry_count(self, book: str) -> int:
        """Record one more successful open for `book` today (IST calendar day —
        this process assumes a local clock set to IST, same as
        INTRADAY_ENTRY_CUTOFF above). Rolls the counter over on a new day.
        Returns the count after incrementing.
        """
        today = datetime.now().strftime('%Y-%m-%d')
        rec = self._entry_counts.get(book)
        if not rec or rec.get('date') != today:
            rec = {'date': today, 'count': 0}
            self._kill_switch_alerted.discard(book)  # new day -> re-arm the alert
        rec['count'] = rec.get('count', 0) + 1
        self._entry_counts[book] = rec
        self._save_kill_switch()
        return rec['count']

    def _kill_switch_blocks(self, book: str) -> bool:
        """True if `book` has hit (or is past) its daily entry cap.

        Fail-soft in the opposite direction from every other gate here: any
        unexpected error is treated as a reason to REFUSE the entry, not to
        let it through — a broken circuit breaker must fail closed.
        """
        try:
            cap = getattr(trading_config, f'max_entries_per_day_{book}', None)
            if cap is None:
                return False  # no cap configured for this book -> nothing to enforce
            count = self._entries_today(book)
            if count < cap:
                return False
            if book not in self._kill_switch_alerted:
                self._kill_switch_alerted.add(book)
                logger.critical(f"KILL SWITCH: {book} hit {count} entries today (cap {cap}) — "
                                 f"new entries halted until tomorrow; exits unaffected")
                self.telegram.send_message(
                    f"KILL SWITCH: {book} hit {count} entries today — new entries halted "
                    f"until tomorrow; exits unaffected")
            return True
        except Exception as e:
            logger.error(f"Kill switch check failed for book={book}: {e} — refusing entry as a fail-safe")
            return True

    def try_enter(self, trader: PaperTrader, signal, source: str, book: str,
                  alert: bool = True) -> Optional[object]:
        """Run all entry gates; open the position if every gate passes.

        Returns the opened Position or None. `source` labels log/alert lines
        (e.g. 'INCUBATOR', 'CANDIDATE', 'ROTATION'). `book` is the kill
        switch's accounting bucket ('main' or 'incubator' — must match a
        kite/config.py TradingConfig.max_entries_per_day_<book> field).
        """
        if self._kill_switch_blocks(book):
            logger.info(f"{source} gate: {signal.symbol} blocked — kill switch ({book} book at daily cap)")
            return None

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
            self._bump_entry_count(book)
            logger.info(f"{source} [{signal.strategy}]: {signal.direction} {signal.symbol} "
                        f"@ Rs {signal.entry_price:.2f}")
            if alert:
                self.telegram.send_message(
                    f"[{source}] {signal.strategy}: {signal.direction} {signal.symbol} "
                    f"@ Rs {signal.entry_price:.2f} (paper)")
        return position
