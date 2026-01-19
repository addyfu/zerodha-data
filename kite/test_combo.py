"""Quick test of combined strategies"""
import sys
from pathlib import Path
sys.path.append(str(Path(__file__).parent.parent))

from multiprocessing import Pool, cpu_count
from kite.utils.data_loader import DataLoader
from kite.backtesting.engine import BacktestEngine
from kite.strategies import STRATEGY_REGISTRY
from kite.strategies.combined_strategy import CombinedStrategy, CombinationMethod

def run_combo(args):
    combo_name, strat_keys, method, symbol = args
    try:
        loader = DataLoader()
        df = loader.load_stock(symbol, 'daily')
        if len(df) < 200:
            return None
        
        strategies = [STRATEGY_REGISTRY[k]({}) for k in strat_keys if k in STRATEGY_REGISTRY]
        if len(strategies) < 2:
            return None
        
        combo = CombinedStrategy(strategies, method=CombinationMethod(method))
        engine = BacktestEngine()
        result = engine.run(combo, df, symbol)
        
        if result and result.total_trades > 0:
            return {
                'strategy': combo_name,
                'symbol': symbol,
                'sharpe': result.sharpe_ratio,
                'return': result.total_return_pct,
                'trades': result.total_trades,
            }
    except Exception as e:
        print(f'Error: {e}')
    return None

if __name__ == '__main__':
    loader = DataLoader()
    symbols = loader.get_available_symbols('daily')[:5]

    configs = [
        ('TopPerformers', ['ascending_triangle', 'stochrsi_macd', 'gmma'], 'majority'),
        ('Trend_Volume', ['ema_21_55', 'hull_slope', 'fib_3wave'], 'majority'),
    ]

    tasks = [(n, s, m, sym) for n, s, m in configs for sym in symbols]
    print(f'Running {len(tasks)} tasks on {cpu_count()} cores...')

    with Pool(cpu_count()) as pool:
        results = pool.map(run_combo, tasks)

    valid = [r for r in results if r]
    print(f'Got {len(valid)} valid results')
    for r in valid:
        print(f"  {r['strategy']:20} {r['symbol']:15} Sharpe: {r['sharpe']:.2f} Return: {r['return']:.2f}%")
