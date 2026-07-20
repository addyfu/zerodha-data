"""Cross-sectional momentum rotation — the one strategy validated by honest walk-forward
(kite/research/honest_lab.py, July 2026 audit).

Rules (must match the backtest exactly):
- On the first trading day of each month: rank universe by 63-day return.
- Regime filter: equal-weight universe index above its 200-day SMA, else hold cash.
- Hold top 3, equal slots. Exit anything that dropped out of the top 3.
- No profit target, no trailing stop — only a 15% disaster stop.
"""
import json
import logging
from datetime import datetime
from pathlib import Path
from typing import Dict, List, Tuple

import pandas as pd

from kite.live_monitor.signal_detector import TradeSignal

logger = logging.getLogger(__name__)

STATE_FILE = Path(__file__).resolve().parents[2] / 'data' / 'momo_rotation_state.json'


class MomentumRotation:
    LOOKBACK = 63
    TOP_N = 3
    REGIME_SMA = 200
    DISASTER_SL = 0.85  # 15% below entry; the only stop this strategy uses

    def __init__(self, capital: float = 100_000, max_positions: int = 5):
        self.strategy_name = 'momo_rotation_63'
        self.slot_size = capital / max_positions  # sized to PaperTrader's slot gate
        self.state = self._load_state()

    @staticmethod
    def _load_state() -> dict:
        try:
            return json.loads(STATE_FILE.read_text())
        except (OSError, ValueError):
            return {'last_rebalance': None}

    def _save_state(self):
        STATE_FILE.write_text(json.dumps(self.state))

    def is_rebalance_due(self) -> bool:
        return self.state.get('last_rebalance') != datetime.now().strftime('%Y-%m')

    def scan(self, daily_data: Dict[str, pd.DataFrame],
             held: List[str]) -> Tuple[List[TradeSignal], List[str]]:
        """Monthly rebalance. Returns (entry_signals, symbols_to_exit).

        `held` = symbols currently held BY THIS STRATEGY. No-op unless a new
        month has started. Marks the rebalance done only after producing orders.
        """
        if not self.is_rebalance_due() or not daily_data:
            return [], []

        closes = {s: df['close'] for s, df in daily_data.items()
                  if df is not None and len(df) >= self.REGIME_SMA}
        if len(closes) < 10:
            logger.warning(f"[{self.strategy_name}] only {len(closes)} symbols with "
                           f"{self.REGIME_SMA}+ daily bars — skipping rebalance, not marking done")
            return [], []

        idx = pd.DataFrame(closes)
        proxy = (idx / idx.iloc[0]).mean(axis=1, skipna=True)
        regime_ok = proxy.iloc[-1] > proxy.rolling(self.REGIME_SMA).mean().iloc[-1]

        self.state['last_rebalance'] = datetime.now().strftime('%Y-%m')
        self._save_state()

        if not regime_ok:
            logger.info(f"[{self.strategy_name}] regime OFF (index < 200SMA) — exiting all, holding cash")
            return [], list(held)

        mom = {s: c.iloc[-1] / c.iloc[-1 - self.LOOKBACK] - 1
               for s, c in closes.items() if len(c) > self.LOOKBACK}
        top = sorted(mom, key=mom.get, reverse=True)[:self.TOP_N]
        logger.info(f"[{self.strategy_name}] rebalance: regime ON, top{self.TOP_N} = "
                    + ", ".join(f"{s} ({mom[s]:+.1%})" for s in top))

        exits = [s for s in held if s not in top]
        signals = []
        for sym in top:
            if sym in held:
                continue
            price = float(closes[sym].iloc[-1])
            qty = int(self.slot_size / price)
            if qty <= 0:
                continue
            sl = price * self.DISASTER_SL
            tp = price * 2.0  # far away; exits happen via rotation, not targets
            signals.append(TradeSignal(
                symbol=sym, direction='BUY', strategy=self.strategy_name,
                entry_price=price, stop_loss=sl, take_profit=tp,
                risk_pct=(1 - self.DISASTER_SL) * 100,
                reward_pct=100.0, rr_ratio=(tp - price) / (price - sl),
                quantity=qty, position_value=qty * price,
                timestamp=datetime.now(), confidence=mom[sym],
                notes=f"63d momentum {mom[sym]:+.1%}", trade_mode='ROTATION'))
        return signals, exits
