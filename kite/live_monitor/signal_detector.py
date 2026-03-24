"""
Signal Detector
===============
Detects trading patterns in real-time using the Fib 3-Wave strategy.
"""
import sys
from pathlib import Path
sys.path.append(str(Path(__file__).parent.parent.parent))

import pandas as pd
import numpy as np
from datetime import datetime, timedelta
from typing import Dict, List, Optional, Tuple
from dataclasses import dataclass
from enum import Enum
import logging

from kite.strategies import STRATEGY_REGISTRY
from kite.strategies.base_strategy import Signal

logger = logging.getLogger(__name__)


@dataclass
class TradeSignal:
    """Represents a detected trading signal."""
    symbol: str
    direction: str  # 'BUY' or 'SELL'
    strategy: str
    entry_price: float
    stop_loss: float
    take_profit: float
    risk_pct: float
    reward_pct: float
    rr_ratio: float
    quantity: int
    position_value: float
    timestamp: datetime
    confidence: float = 0.0
    notes: str = ""
    
    def to_dict(self) -> Dict:
        return {
            'symbol': self.symbol,
            'direction': self.direction,
            'strategy': self.strategy,
            'entry_price': self.entry_price,
            'stop_loss': self.stop_loss,
            'take_profit': self.take_profit,
            'risk_pct': self.risk_pct,
            'reward_pct': self.reward_pct,
            'rr_ratio': self.rr_ratio,
            'quantity': self.quantity,
            'position_value': self.position_value,
            'timestamp': self.timestamp.isoformat(),
            'confidence': self.confidence,
            'notes': self.notes
        }


class SignalDetector:
    """
    Detects trading signals using configured strategies.
    """
    
    def __init__(self, 
                 strategy_name: str = 'fib_3wave',
                 capital: float = 100000,
                 risk_per_trade: float = 0.02,
                 min_rr_ratio: float = 1.5):
        """
        Initialize signal detector.
        
        Args:
            strategy_name: Strategy to use from registry
            capital: Trading capital for position sizing
            risk_per_trade: Risk per trade as decimal (0.02 = 2%)
            min_rr_ratio: Minimum risk:reward ratio to accept
        """
        self.strategy_name = strategy_name
        self.capital = capital
        self.risk_per_trade = risk_per_trade
        self.min_rr_ratio = min_rr_ratio
        
        # Initialize strategy
        if strategy_name in STRATEGY_REGISTRY:
            self.strategy = STRATEGY_REGISTRY[strategy_name]({})
        else:
            raise ValueError(f"Strategy '{strategy_name}' not found in registry")
        
        # Track last signals to avoid duplicates
        self.last_signals: Dict[str, Tuple[str, datetime]] = {}
        self.signal_cooldown = timedelta(hours=4)  # Don't repeat same signal within 4 hours
    
    def detect_signal(self, symbol: str, df: pd.DataFrame) -> Optional[TradeSignal]:
        """
        Detect trading signal for a symbol.
        
        Args:
            symbol: Stock symbol
            df: DataFrame with OHLCV data (needs enough history for indicators)
            
        Returns:
            TradeSignal if detected, None otherwise
        """
        if df is None or len(df) < 50:
            return None
        
        try:
            # Generate signals
            signals_df = self.strategy.generate_signals(df)
            
            if signals_df is None or len(signals_df) == 0:
                return None
            
            # Get latest signal
            latest = signals_df.iloc[-1]
            raw_signal = latest.get('signal', 0)

            # Convert int to Signal enum (strategies return 1/-1/0 as ints)
            try:
                signal = Signal(int(raw_signal))
            except (ValueError, TypeError):
                signal = Signal.HOLD

            # Check if it's a tradeable signal
            if signal not in [Signal.BUY, Signal.SELL]:
                return None
            
            # Check cooldown
            direction = 'BUY' if signal == Signal.BUY else 'SELL'
            last_signal = self.last_signals.get(symbol)
            
            if last_signal:
                last_direction, last_time = last_signal
                if last_direction == direction and datetime.now() - last_time < self.signal_cooldown:
                    logger.debug(f"{symbol}: Signal in cooldown period")
                    return None
            
            # Calculate entry, SL, TP
            entry_price = latest['close']
            idx = signals_df.index[-1]  # Use actual index label, not position (strategies use df.loc)

            stop_loss = self.strategy.calculate_stop_loss(signals_df, idx, signal)
            take_profit = self.strategy.calculate_take_profit(
                signals_df, idx, signal, entry_price, stop_loss
            )
            
            # Calculate risk/reward
            risk_pct = abs(entry_price - stop_loss) / entry_price * 100
            reward_pct = abs(take_profit - entry_price) / entry_price * 100
            rr_ratio = reward_pct / risk_pct if risk_pct > 0 else 0
            
            # Check minimum R:R
            if rr_ratio < self.min_rr_ratio:
                logger.debug(f"{symbol}: R:R {rr_ratio:.2f} below minimum {self.min_rr_ratio}")
                return None
            
            # Calculate position size
            risk_amount = self.capital * self.risk_per_trade
            risk_per_share = abs(entry_price - stop_loss)
            quantity = int(risk_amount / risk_per_share) if risk_per_share > 0 else 0
            
            if quantity <= 0:
                return None
            
            position_value = quantity * entry_price
            
            # Update last signal
            self.last_signals[symbol] = (direction, datetime.now())
            
            # Create signal object
            trade_signal = TradeSignal(
                symbol=symbol,
                direction=direction,
                strategy=self.strategy_name,
                entry_price=entry_price,
                stop_loss=stop_loss,
                take_profit=take_profit,
                risk_pct=risk_pct,
                reward_pct=reward_pct,
                rr_ratio=rr_ratio,
                quantity=quantity,
                position_value=position_value,
                timestamp=datetime.now(),
                confidence=self._calculate_confidence(signals_df, idx),
                notes=self._generate_notes(signals_df, idx, signal)
            )
            
            logger.info(f"Signal detected: {symbol} {direction} @ {entry_price:.2f}")
            return trade_signal
            
        except Exception as e:
            logger.error(f"Signal detection error for {symbol}: {e}")
            return None
    
    def _calculate_confidence(self, df: pd.DataFrame, idx) -> float:
        """
        Calculate signal confidence based on various factors.

        Returns:
            Confidence score 0-100
        """
        confidence = 50.0  # Base confidence

        try:
            latest = df.loc[idx]

            # Volume confirmation
            if 'volume' in df.columns:
                avg_volume = df['volume'].rolling(20).mean().loc[idx]
                if latest['volume'] > avg_volume * 1.5:
                    confidence += 15  # High volume
                elif latest['volume'] > avg_volume:
                    confidence += 5

            # Trend alignment (using simple MA)
            if len(df) > 50:
                ma50 = df['close'].rolling(50).mean().loc[idx]
                if latest['close'] > ma50:
                    confidence += 10  # Above MA50

            # Volatility check
            if 'atr' in df.columns:
                atr = df['atr'].loc[idx]
                avg_atr = df['atr'].rolling(20).mean().loc[idx]
                if atr < avg_atr * 1.5:
                    confidence += 10  # Normal volatility

            # Cap at 100
            confidence = min(confidence, 100)

        except:
            pass

        return confidence

    def _generate_notes(self, df: pd.DataFrame, idx, signal: Signal) -> str:
        """Generate notes about the signal."""
        notes = []

        try:
            latest = df.loc[idx]

            # Pattern type
            notes.append(f"Strategy: {self.strategy_name}")

            # Price action
            if len(df) > 1:
                pos = df.index.get_loc(idx)
                prev = df.iloc[pos - 1]
                change = (latest['close'] - prev['close']) / prev['close'] * 100
                notes.append(f"Day change: {change:+.2f}%")
            
            # Volume
            if 'volume' in df.columns:
                avg_vol = df['volume'].rolling(20).mean().loc[idx]
                vol_ratio = latest['volume'] / avg_vol if avg_vol > 0 else 1
                notes.append(f"Volume: {vol_ratio:.1f}x avg")
            
        except:
            pass
        
        return " | ".join(notes)
    
    def scan_multiple(self, data: Dict[str, pd.DataFrame]) -> List[TradeSignal]:
        """
        Scan multiple symbols for signals.
        
        Args:
            data: Dictionary of symbol -> DataFrame
            
        Returns:
            List of detected signals
        """
        signals = []
        
        for symbol, df in data.items():
            signal = self.detect_signal(symbol, df)
            if signal:
                signals.append(signal)
        
        # Sort by confidence
        signals.sort(key=lambda x: x.confidence, reverse=True)
        
        return signals


class MultiStrategyDetector:
    """
    Detects signals using multiple strategies for confirmation.
    """
    
    def __init__(self, 
                 strategies: List[str] = None,
                 capital: float = 100000,
                 min_agreement: int = 2):
        """
        Initialize multi-strategy detector.
        
        Args:
            strategies: List of strategy names to use
            capital: Trading capital
            min_agreement: Minimum strategies that must agree
        """
        self.strategies = strategies or ['fib_3wave', 'ema_21_55', 'stochrsi_macd']
        self.capital = capital
        self.min_agreement = min_agreement
        
        self.detectors = [
            SignalDetector(s, capital) for s in self.strategies 
            if s in STRATEGY_REGISTRY
        ]
    
    def detect_consensus_signal(self, symbol: str, df: pd.DataFrame) -> Optional[TradeSignal]:
        """
        Detect signal only if multiple strategies agree.
        
        Args:
            symbol: Stock symbol
            df: DataFrame with OHLCV data
            
        Returns:
            TradeSignal if consensus reached, None otherwise
        """
        signals = []
        
        for detector in self.detectors:
            signal = detector.detect_signal(symbol, df)
            if signal:
                signals.append(signal)
        
        if len(signals) < self.min_agreement:
            return None
        
        # Check if all agree on direction
        directions = [s.direction for s in signals]
        if len(set(directions)) > 1:
            return None  # Conflicting signals
        
        # Return the signal with highest confidence
        best_signal = max(signals, key=lambda x: x.confidence)
        best_signal.notes += f" | Confirmed by {len(signals)} strategies"
        best_signal.confidence = min(best_signal.confidence + 20, 100)
        
        return best_signal


if __name__ == '__main__':
    # Test signal detector
    print("Testing Signal Detector...")
    
    from kite.utils.data_loader import DataLoader
    
    loader = DataLoader()
    detector = SignalDetector('fib_3wave')
    
    # Test on a few stocks
    symbols = ['RELIANCE', 'TCS', 'HDFCBANK', 'INFY', 'ICICIBANK']
    
    for symbol in symbols:
        try:
            df = loader.load_stock(symbol, 'daily')
            signal = detector.detect_signal(symbol, df)
            
            if signal:
                print(f"\n{signal.symbol}: {signal.direction}")
                print(f"  Entry: ₹{signal.entry_price:.2f}")
                print(f"  SL: ₹{signal.stop_loss:.2f} ({signal.risk_pct:.1f}%)")
                print(f"  TP: ₹{signal.take_profit:.2f} ({signal.reward_pct:.1f}%)")
                print(f"  R:R: 1:{signal.rr_ratio:.1f}")
                print(f"  Qty: {signal.quantity} shares")
                print(f"  Confidence: {signal.confidence:.0f}%")
            else:
                print(f"{symbol}: No signal")
        except Exception as e:
            print(f"{symbol}: Error - {e}")
