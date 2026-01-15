"""
Quick test script to verify all new strategies work correctly.
"""
import sys
import io
from pathlib import Path

# Fix encoding for Windows
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8')

# Add parent to path
sys.path.insert(0, str(Path(__file__).parent.parent))

import pandas as pd
from datetime import datetime

print("=" * 70)
print("TESTING NEW UNDERRATED STRATEGIES")
print("=" * 70)

# Test imports
print("\n[1] Testing Imports...")
try:
    from kite.indicators.trend import (
        parabolic_sar, add_parabolic_sar,
        alligator, add_alligator,
        ichimoku_cloud, add_ichimoku,
        central_pivot_range
    )
    print("    [OK] Trend indicators imported successfully")
except Exception as e:
    print(f"    [FAIL] Trend indicators: {e}")

try:
    from kite.strategies import (
        CPRStrategy,
        ChandelierExitStrategy,
        DonchianTurtleStrategy,
        VWMASMAStrategy,
        HullSlopeStrategy,
        PSARIchimokuStrategy,
        ROCMAStrategy,
        CMFIchimokuStrategy,
        AlligatorStrategy,
        FibPivotStrategy,
    )
    print("    [OK] All 10 new strategies imported successfully")
except Exception as e:
    print(f"    [FAIL] Strategy imports: {e}")

# Test with sample data
print("\n[2] Loading Sample Data...")
try:
    from kite.utils.data_loader import DataLoader
    loader = DataLoader()
    df = loader.load_stock('RELIANCE', 'daily')
    print(f"    [OK] Loaded {len(df)} rows of RELIANCE daily data")
except Exception as e:
    print(f"    [FAIL] Data loading: {e}")
    df = None

if df is not None:
    # Test each strategy
    print("\n[3] Testing Signal Generation...")
    
    strategies_to_test = [
        ('CPR', CPRStrategy),
        ('Chandelier_Exit', ChandelierExitStrategy),
        ('Donchian_Turtle', DonchianTurtleStrategy),
        ('VWMA_SMA', VWMASMAStrategy),
        ('Hull_Slope', HullSlopeStrategy),
        ('PSAR_Ichimoku', PSARIchimokuStrategy),
        ('ROC_MA', ROCMAStrategy),
        ('CMF_Ichimoku', CMFIchimokuStrategy),
        ('Alligator', AlligatorStrategy),
        ('Fib_Pivot', FibPivotStrategy),
    ]
    
    for name, strategy_class in strategies_to_test:
        try:
            strategy = strategy_class()
            result_df = strategy.generate_signals(df.copy())
            
            buy_signals = (result_df['signal'] == 1).sum()
            sell_signals = (result_df['signal'] == -1).sum()
            
            print(f"    [OK] {name:20s} - Buy: {buy_signals:4d}, Sell: {sell_signals:4d}")
        except Exception as e:
            print(f"    [FAIL] {name}: {e}")

    # Test backtesting
    print("\n[4] Testing Backtest Engine...")
    try:
        from kite.backtesting.engine import BacktestEngine
        from kite.config import trading_config
        
        engine = BacktestEngine(
            initial_capital=trading_config.initial_capital,
            risk_per_trade=trading_config.risk_per_trade,
            allow_short=True
        )
        
        # Test with Hull Slope strategy
        strategy = HullSlopeStrategy()
        result = engine.run(strategy, df, 'RELIANCE')
        
        print(f"    [OK] Backtest completed")
        print(f"         Total Trades: {result.total_trades}")
        print(f"         Win Rate: {result.win_rate:.1f}%")
        print(f"         Total Return: {result.total_return_pct:.2f}%")
        print(f"         Sharpe Ratio: {result.sharpe_ratio:.2f}")
    except Exception as e:
        print(f"    [FAIL] Backtest: {e}")
        import traceback
        traceback.print_exc()

print("\n" + "=" * 70)
print("TEST COMPLETE")
print("=" * 70)
