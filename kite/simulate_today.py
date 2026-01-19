"""
Simulate Today's Trading - Using most recent data as "today"
Shows what trades would be taken if we ran the strategy today
"""
import sys
from pathlib import Path
sys.path.append(str(Path(__file__).parent.parent))

import pandas as pd
import numpy as np
from datetime import datetime, timedelta
import warnings
warnings.filterwarnings('ignore')

from kite.utils.data_loader import DataLoader
from kite.strategies import STRATEGY_REGISTRY
from kite.backtesting.engine import BacktestEngine
from kite.strategies.base_strategy import Signal


def analyze_stock(symbol: str, strategy, loader: DataLoader, timeframe: str = 'daily'):
    """Analyze a single stock and return today's signal."""
    try:
        df = loader.load_stock(symbol, timeframe)
        
        if len(df) < 50:
            return None
        
        # Generate signals
        signals_df = strategy.generate_signals(df)
        
        # Get the most recent day (simulating "today")
        latest_date = signals_df.index[-1]
        today_data = signals_df.loc[latest_date]
        
        # Get previous day for comparison
        prev_data = signals_df.iloc[-2] if len(signals_df) > 1 else today_data
        
        signal = today_data.get('signal', Signal.HOLD)
        
        result = {
            'symbol': symbol,
            'date': latest_date.strftime('%Y-%m-%d'),
            'open': today_data['open'],
            'high': today_data['high'],
            'low': today_data['low'],
            'close': today_data['close'],
            'volume': today_data.get('volume', 0),
            'change_pct': (today_data['close'] - prev_data['close']) / prev_data['close'] * 100,
            'signal': signal.name if hasattr(signal, 'name') else str(signal),
        }
        
        # If there's a signal, calculate SL/TP
        if signal in [Signal.BUY, Signal.SELL]:
            idx = len(signals_df) - 1
            sl = strategy.calculate_stop_loss(signals_df, idx, signal)
            tp = strategy.calculate_take_profit(signals_df, idx, signal, today_data['close'], sl)
            
            result['entry_price'] = today_data['close']
            result['stop_loss'] = sl
            result['take_profit'] = tp
            result['risk_pct'] = abs(today_data['close'] - sl) / today_data['close'] * 100
            result['reward_pct'] = abs(tp - today_data['close']) / today_data['close'] * 100
            result['rr_ratio'] = result['reward_pct'] / result['risk_pct'] if result['risk_pct'] > 0 else 0
        
        return result
        
    except Exception as e:
        return None


def run_recent_backtest(symbol: str, strategy, loader: DataLoader, days: int = 30):
    """Run backtest on recent data to show recent performance."""
    try:
        df = loader.load_stock(symbol, 'daily')
        
        if len(df) < days:
            return None
        
        # Use only recent data
        df_recent = df.tail(days)
        
        engine = BacktestEngine()
        result = engine.run(strategy, df_recent, symbol)
        
        if result:
            return {
                'symbol': symbol,
                'trades': result.total_trades,
                'win_rate': result.win_rate,
                'return_pct': result.total_return_pct,
                'sharpe': result.sharpe_ratio,
            }
    except:
        pass
    return None


def main():
    print("\n" + "="*80)
    print("TRADING SIMULATION - Fib 3-Wave Strategy")
    print(f"Analysis Date: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    print("="*80)
    
    loader = DataLoader()
    
    # Get available stocks
    symbols = loader.get_available_symbols('daily')
    print(f"\nAnalyzing {len(symbols)} stocks from NIFTY 50...")
    
    # Initialize strategy
    strategy = STRATEGY_REGISTRY['fib_3wave']({})
    
    print("-"*80)
    
    buy_signals = []
    sell_signals = []
    all_results = []
    
    for symbol in symbols:
        result = analyze_stock(symbol, strategy, loader)
        
        if result:
            all_results.append(result)
            
            if result['signal'] == 'BUY':
                buy_signals.append(result)
            elif result['signal'] == 'SELL':
                sell_signals.append(result)
    
    # Get the date from the data
    if all_results:
        data_date = all_results[0]['date']
    else:
        data_date = "Unknown"
    
    print(f"\nData as of: {data_date}")
    
    # Print Summary
    print("\n" + "="*80)
    print("TODAY'S TRADING SIGNALS")
    print("="*80)
    
    if buy_signals:
        print(f"\n{'='*35} BUY SIGNALS {'='*32}")
        print(f"{'Symbol':<15} {'Price':>10} {'Stop Loss':>12} {'Target':>12} {'Risk%':>8} {'R:R':>6}")
        print("-"*70)
        for s in buy_signals:
            print(f"{s['symbol']:<15} {s['close']:>10.2f} {s['stop_loss']:>12.2f} "
                  f"{s['take_profit']:>12.2f} {s['risk_pct']:>7.2f}% {s['rr_ratio']:>6.1f}")
    else:
        print("\n[!] No BUY signals today.")
    
    if sell_signals:
        print(f"\n{'='*34} SELL SIGNALS {'='*32}")
        print(f"{'Symbol':<15} {'Price':>10} {'Stop Loss':>12} {'Target':>12} {'Risk%':>8} {'R:R':>6}")
        print("-"*70)
        for s in sell_signals:
            print(f"{s['symbol']:<15} {s['close']:>10.2f} {s['stop_loss']:>12.2f} "
                  f"{s['take_profit']:>12.2f} {s['risk_pct']:>7.2f}% {s['rr_ratio']:>6.1f}")
    else:
        print("\n[!] No SELL signals today.")
    
    # Market Overview
    print(f"\n{'='*35} MARKET OVERVIEW {'='*28}")
    if all_results:
        gainers = sorted([r for r in all_results if r['change_pct'] > 0], 
                        key=lambda x: x['change_pct'], reverse=True)[:5]
        losers = sorted([r for r in all_results if r['change_pct'] < 0], 
                       key=lambda x: x['change_pct'])[:5]
        
        avg_change = np.mean([r['change_pct'] for r in all_results])
        
        print(f"\nMarket Sentiment: {'BULLISH' if avg_change > 0 else 'BEARISH'} (Avg: {avg_change:+.2f}%)")
        
        print("\nTop 5 Gainers:")
        for r in gainers:
            signal_marker = " [BUY]" if r['signal'] == 'BUY' else ""
            print(f"  {r['symbol']:<15} {r['change_pct']:>+6.2f}%  Rs {r['close']:>10.2f}{signal_marker}")
        
        print("\nTop 5 Losers:")
        for r in losers:
            signal_marker = " [SELL]" if r['signal'] == 'SELL' else ""
            print(f"  {r['symbol']:<15} {r['change_pct']:>+6.2f}%  Rs {r['close']:>10.2f}{signal_marker}")
    
    # Position Sizing Recommendation
    if buy_signals or sell_signals:
        print(f"\n{'='*32} POSITION SIZING {'='*31}")
        print("\nCapital: Rs 1,00,000 | Risk per trade: 2% (Rs 2,000)")
        print("-"*80)
        
        total_signals = buy_signals + sell_signals
        
        for s in total_signals:
            risk_amount = 100000 * 0.02  # 2% of capital
            risk_per_share = abs(s['close'] - s['stop_loss'])
            quantity = int(risk_amount / risk_per_share) if risk_per_share > 0 else 0
            position_value = quantity * s['close']
            potential_profit = quantity * abs(s['take_profit'] - s['close'])
            
            print(f"\n{s['symbol']} - {s['signal']}")
            print(f"  Entry:          Rs {s['close']:>10.2f}")
            print(f"  Stop Loss:      Rs {s['stop_loss']:>10.2f} ({s['risk_pct']:.1f}% risk)")
            print(f"  Target:         Rs {s['take_profit']:>10.2f} ({s['reward_pct']:.1f}% reward)")
            print(f"  Risk:Reward:    1:{s['rr_ratio']:.1f}")
            print(f"  Quantity:       {quantity} shares")
            print(f"  Position Size:  Rs {position_value:>10,.2f}")
            print(f"  Max Loss:       Rs {risk_amount:>10,.2f}")
            print(f"  Max Profit:     Rs {potential_profit:>10,.2f}")
    
    # Recent Performance
    print(f"\n{'='*30} STRATEGY PERFORMANCE (30 Days) {'='*19}")
    print("\nRecent backtest results:")
    print(f"{'Symbol':<15} {'Trades':>8} {'Win%':>8} {'Return%':>10} {'Sharpe':>8}")
    print("-"*55)
    
    perf_results = []
    for symbol in symbols[:10]:  # Top 10 stocks
        perf = run_recent_backtest(symbol, strategy, loader, days=60)
        if perf and perf['trades'] > 0:
            perf_results.append(perf)
            print(f"{perf['symbol']:<15} {perf['trades']:>8} {perf['win_rate']:>7.1f}% "
                  f"{perf['return_pct']:>+9.2f}% {perf['sharpe']:>8.2f}")
    
    if perf_results:
        avg_return = np.mean([p['return_pct'] for p in perf_results])
        avg_winrate = np.mean([p['win_rate'] for p in perf_results])
        avg_sharpe = np.mean([p['sharpe'] for p in perf_results])
        print("-"*55)
        print(f"{'AVERAGE':<15} {'-':>8} {avg_winrate:>7.1f}% {avg_return:>+9.2f}% {avg_sharpe:>8.2f}")
    
    print("\n" + "="*80)
    print("ANALYSIS COMPLETE!")
    print("="*80)
    
    # Save results
    if all_results:
        df_results = pd.DataFrame(all_results)
        filename = f"signals_{datetime.now().strftime('%Y%m%d_%H%M%S')}.csv"
        df_results.to_csv(filename, index=False)
        print(f"\nResults saved to {filename}")


if __name__ == '__main__':
    main()
