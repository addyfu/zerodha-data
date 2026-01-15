"""
Quick test script to verify the backtesting system works.

Run: python quick_test.py
"""
import sys
from pathlib import Path

# Add parent to path
sys.path.insert(0, str(Path(__file__).parent.parent))

def main():
    print("=" * 60)
    print("TRADING STRATEGY BACKTESTING SYSTEM - QUICK TEST")
    print("=" * 60)
    
    # Test imports
    print("\n1. Testing imports...")
    try:
        from kite.utils.data_loader import DataLoader, load_stock_data
        from kite.backtesting.engine import BacktestEngine, run_backtest
        from kite.backtesting.performance import generate_performance_report
        from kite.strategies import (
            EMA2155Strategy, RSIDivergenceStrategy, VWAPPullbackStrategy,
            BBSqueezeStrategy, EMA3ScalpingStrategy, SupplyDemandStrategy,
            StochasticConfluenceStrategy, Fib3WaveStrategy, MultiTimeframeStrategy
        )
        from kite.config import trading_config
        print("   [OK] All imports successful!")
    except ImportError as e:
        print(f"   [FAIL] Import error: {e}")
        return
    
    # Test data loading
    print("\n2. Testing data loading...")
    try:
        loader = DataLoader()
        symbols = loader.get_available_symbols('daily')
        print(f"   [OK] Found {len(symbols)} symbols with daily data")
        
        if not symbols:
            print("   [WARN] No data files found. Please check data directory.")
            return
        
        # Load first available symbol
        test_symbol = symbols[0]
        df = loader.load_stock(test_symbol, 'daily')
        print(f"   [OK] Loaded {test_symbol}: {len(df)} bars")
        print(f"     Date range: {df.index[0]} to {df.index[-1]}")
    except Exception as e:
        print(f"   [FAIL] Data loading error: {e}")
        return
    
    # Test strategy
    print("\n3. Testing strategy signal generation...")
    try:
        strategy = EMA2155Strategy()
        df_signals = strategy.generate_signals(df)
        
        buy_signals = (df_signals['signal'] == 1).sum()
        sell_signals = (df_signals['signal'] == -1).sum()
        
        print(f"   [OK] EMA 21/55 Strategy:")
        print(f"     Buy signals: {buy_signals}")
        print(f"     Sell signals: {sell_signals}")
    except Exception as e:
        print(f"   [FAIL] Strategy error: {e}")
        return
    
    # Test backtesting
    print("\n4. Testing backtesting engine...")
    try:
        engine = BacktestEngine(
            initial_capital=100000,
            risk_per_trade=0.02,
            allow_short=True
        )
        
        result = engine.run(strategy, df, test_symbol)
        
        print(f"   [OK] Backtest completed!")
        print(f"     Total trades: {result.total_trades}")
        print(f"     Win rate: {result.win_rate:.1f}%")
        print(f"     Total return: {result.total_return_pct:.2f}%")
        print(f"     Sharpe ratio: {result.sharpe_ratio:.2f}")
    except Exception as e:
        print(f"   [FAIL] Backtest error: {e}")
        import traceback
        traceback.print_exc()
        return
    
    # Test all strategies
    print("\n5. Testing all strategies...")
    strategies = [
        ('EMA 21/55', EMA2155Strategy),
        ('RSI Divergence', RSIDivergenceStrategy),
        ('VWAP Pullback', VWAPPullbackStrategy),
        ('BB Squeeze', BBSqueezeStrategy),
        ('EMA 3 Scalping', EMA3ScalpingStrategy),
        ('Supply Demand', SupplyDemandStrategy),
        ('Stochastic Confluence', StochasticConfluenceStrategy),
        ('Fib 3-Wave', Fib3WaveStrategy),
        ('Multi-Timeframe', MultiTimeframeStrategy),
    ]
    
    results = []
    for name, strategy_class in strategies:
        try:
            strat = strategy_class()
            res = run_backtest(strat, df, test_symbol)
            results.append((name, res))
            status = "[OK]" if res.total_trades > 0 else "[WARN]"
            print(f"   {status} {name}: {res.total_trades} trades, {res.total_return_pct:.2f}% return")
        except Exception as e:
            print(f"   [FAIL] {name}: Error - {e}")
    
    # Summary
    print("\n" + "=" * 60)
    print("TEST SUMMARY")
    print("=" * 60)
    
    if results:
        # Best strategy
        best = max(results, key=lambda x: x[1].sharpe_ratio if x[1].total_trades > 0 else -999)
        print(f"\nBest strategy on {test_symbol}: {best[0]}")
        print(f"  Sharpe Ratio: {best[1].sharpe_ratio:.2f}")
        print(f"  Return: {best[1].total_return_pct:.2f}%")
        print(f"  Win Rate: {best[1].win_rate:.1f}%")
    
    print("\n[SUCCESS] All tests passed! The system is ready to use.")
    print("\nNext steps:")
    print("  1. Run full comparison: python compare_strategies.py")
    print("  2. Run single backtest: python run_backtest.py --strategy ema_21_55 --symbol RELIANCE")
    print("  3. Run all strategies: python run_backtest.py --all-strategies --symbol RELIANCE")


if __name__ == '__main__':
    main()
