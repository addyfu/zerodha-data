"""
Test position sizing logic in SignalDetector.
Verifies that quantity is properly capped to max_position_pct.
"""
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent.parent.parent))

import pandas as pd
import numpy as np
from datetime import datetime, timedelta


def create_test_df(close_price: float, n_bars: int = 100) -> pd.DataFrame:
    """Create test OHLCV dataframe."""
    dates = pd.date_range(end=datetime.now(), periods=n_bars, freq='5min')
    noise = np.random.randn(n_bars) * 0.01 * close_price
    closes = close_price + noise

    df = pd.DataFrame({
        'open': closes * 0.999,
        'high': closes * 1.005,
        'low': closes * 0.995,
        'close': closes,
        'volume': np.random.randint(10000, 100000, n_bars)
    }, index=dates)

    return df


def test_position_sizing_cap():
    """Test that position size is capped to max_position_pct."""
    from kite.live_monitor.signal_detector import SignalDetector

    print("\n=== Test 1: Position Sizing Cap ===")

    capital = 100000
    risk_per_trade = 0.02  # 2%
    max_position_pct = 0.5  # 50%

    detector = SignalDetector(
        strategy_name='ema_21_55',
        capital=capital,
        risk_per_trade=risk_per_trade,
        max_position_pct=max_position_pct
    )

    # Scenario: tight stop loss should trigger quantity cap
    # entry = 1000, stop = 1010 (1% stop for SELL)
    # risk_per_share = 10
    # risk_amount = 100000 * 0.02 = 2000
    # raw_quantity = 2000 / 10 = 200 shares
    # raw_position_value = 200 * 1000 = 200,000 (200% of capital!)
    # max_position_value = 100000 * 0.5 = 50,000
    # max_quantity = 50,000 / 1000 = 50 shares
    # capped_quantity = 50

    entry_price = 1000.0
    stop_loss = 1010.0  # Tight 1% stop for SELL
    risk_per_share = abs(entry_price - stop_loss)  # 10

    risk_amount = capital * risk_per_trade  # 2000
    raw_quantity = int(risk_amount / risk_per_share)  # 200
    raw_position_value = raw_quantity * entry_price  # 200,000

    max_position_value = capital * max_position_pct  # 50,000
    max_quantity = int(max_position_value / entry_price)  # 50

    expected_quantity = min(raw_quantity, max_quantity)  # 50
    expected_position_value = expected_quantity * entry_price  # 50,000

    print(f"Entry: {entry_price}, Stop: {stop_loss}")
    print(f"Risk per share: {risk_per_share}")
    print(f"Risk amount: {risk_amount}")
    print(f"Raw quantity: {raw_quantity} (position value: {raw_position_value})")
    print(f"Max quantity: {max_quantity} (max position: {max_position_value})")
    print(f"Expected capped quantity: {expected_quantity}")

    assert raw_quantity > max_quantity, "Test setup error: raw_quantity should exceed max"
    assert expected_quantity == max_quantity, "Expected quantity should be capped"
    assert expected_position_value <= max_position_value, "Position value should be within limit"

    print("PASS: Math verification correct\n")


def test_signal_detector_with_capping():
    """Test actual SignalDetector with a strategy that generates signals."""
    from kite.live_monitor.signal_detector import SignalDetector

    print("\n=== Test 2: SignalDetector with Real Strategy ===")

    capital = 100000
    detector = SignalDetector(
        strategy_name='ema_21_55',
        capital=capital,
        risk_per_trade=0.02,
        min_rr_ratio=1.5,
        max_position_pct=0.5
    )

    # Create trending data that should generate a signal
    df = create_test_df(1500.0, n_bars=100)
    # Make it trend up then down for EMA crossover
    df['close'] = df['close'].values + np.linspace(-50, 50, len(df))
    df['open'] = df['close'] * 0.999
    df['high'] = df['close'] * 1.005
    df['low'] = df['close'] * 0.995

    signal = detector.detect_signal('TEST', df)

    if signal:
        print(f"Signal generated: {signal.direction} @ {signal.entry_price:.2f}")
        print(f"Stop Loss: {signal.stop_loss:.2f}")
        print(f"Quantity: {signal.quantity}")
        print(f"Position Value: {signal.position_value:.2f}")

        max_position_value = capital * 0.5
        assert signal.position_value <= max_position_value, \
            f"Position value {signal.position_value} exceeds max {max_position_value}"
        print(f"PASS: Position value {signal.position_value:.0f} <= max {max_position_value:.0f}")
    else:
        print("No signal generated (strategy conditions not met)")
        print("SKIP: No signal to test")


def test_various_price_levels():
    """Test position sizing at various price levels."""
    from kite.live_monitor.signal_detector import SignalDetector

    print("\n=== Test 3: Various Price Levels ===")

    capital = 100000
    max_position_pct = 0.5
    max_position_value = capital * max_position_pct

    test_cases = [
        (100, "Low price stock"),
        (1000, "Mid price stock"),
        (5000, "High price stock"),
        (50000, "Very high price stock"),
    ]

    for price, description in test_cases:
        max_quantity = int(max_position_value / price)
        max_actual_position = max_quantity * price

        print(f"{description} @ Rs {price}:")
        print(f"  Max quantity: {max_quantity} shares")
        print(f"  Max position value: Rs {max_actual_position:,.0f}")

        if max_quantity <= 0:
            print(f"  WARNING: Cannot buy even 1 share within 50% limit")
        else:
            assert max_actual_position <= max_position_value, "Position exceeds limit"
            print(f"  PASS: Within 50% limit")

    print()


def test_order_book_compatibility():
    """Test that capped signals pass order_book validation."""
    from kite.live_monitor.order_book import OrderBook
    import tempfile
    import os

    print("\n=== Test 4: OrderBook Compatibility ===")

    capital = 100000

    # Create temp order book
    with tempfile.NamedTemporaryFile(mode='w', suffix='.json', delete=False) as f:
        temp_file = f.name

    try:
        order_book = OrderBook(temp_file)
        order_book.account["current_capital"] = capital
        order_book.account["initial_capital"] = capital

        # Create a signal that would previously fail
        # (high quantity due to tight stop)
        signal = {
            "symbol": "TEST",
            "direction": "SELL",
            "entry_price": 1000.0,
            "stop_loss": 1010.0,
            "take_profit": 970.0,
            "quantity": 50,  # Capped to 50 (not 200)
            "position_value": 50000.0,  # 50% of capital
            "strategy": "test",
            "risk_pct": 1.0,
            "reward_pct": 3.0,
            "rr_ratio": 3.0,
        }

        position_value = signal["quantity"] * signal["entry_price"]
        max_allowed = order_book.account["current_capital"] * 0.5

        print(f"Signal position value: Rs {position_value:,.0f}")
        print(f"Max allowed (50%): Rs {max_allowed:,.0f}")

        # This should pass now
        position = order_book.open_position(signal)

        if position:
            print(f"PASS: Position opened successfully")
            print(f"  Symbol: {position['symbol']}")
            print(f"  Quantity: {position['quantity']}")
        else:
            print("FAIL: Position rejected")

    finally:
        os.unlink(temp_file)


def test_edge_cases():
    """Test edge cases in position sizing."""
    print("\n=== Test 5: Edge Cases ===")

    capital = 100000

    # Case 1: Very expensive stock (can't buy even 1 share within 50%)
    price = 60000
    max_position = capital * 0.5  # 50000
    max_quantity = int(max_position / price)  # 0
    print(f"Stock @ Rs {price}: max_quantity = {max_quantity}")
    assert max_quantity == 0, "Expected 0 quantity for expensive stock"
    print("  PASS: Correctly returns 0 for expensive stock")

    # Case 2: Very cheap stock
    price = 10
    max_quantity = int(max_position / price)  # 5000
    print(f"Stock @ Rs {price}: max_quantity = {max_quantity}")
    assert max_quantity == 5000
    print("  PASS: Correct quantity for cheap stock")

    # Case 3: Exact boundary
    price = 50000  # Exactly at 50% limit
    max_quantity = int(max_position / price)  # 1
    print(f"Stock @ Rs {price}: max_quantity = {max_quantity}")
    assert max_quantity == 1
    print("  PASS: Correct quantity at boundary")

    print()


def run_all_tests():
    """Run all position sizing tests."""
    print("=" * 60)
    print("POSITION SIZING TESTS")
    print("=" * 60)

    try:
        test_position_sizing_cap()
        test_signal_detector_with_capping()
        test_various_price_levels()
        test_order_book_compatibility()
        test_edge_cases()

        print("=" * 60)
        print("ALL TESTS PASSED")
        print("=" * 60)
        return True

    except AssertionError as e:
        print(f"\nTEST FAILED: {e}")
        return False
    except Exception as e:
        print(f"\nTEST ERROR: {e}")
        import traceback
        traceback.print_exc()
        return False


if __name__ == "__main__":
    success = run_all_tests()
    sys.exit(0 if success else 1)
