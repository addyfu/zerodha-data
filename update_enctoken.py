"""
Update Enctoken
===============
Quick script to update your enctoken for local testing.

Usage:
    1. Login to kite.zerodha.com in your browser
    2. Open Developer Tools (F12)
    3. Go to Application > Cookies > kite.zerodha.com
    4. Find the 'enctoken' cookie and copy its value
    5. Run this script and paste the token
"""
import os
from pathlib import Path

def main():
    print("=" * 60)
    print("UPDATE ENCTOKEN")
    print("=" * 60)
    print()
    print("To get your enctoken:")
    print("1. Login to https://kite.zerodha.com")
    print("2. Open Developer Tools (F12)")
    print("3. Go to: Application > Cookies > kite.zerodha.com")
    print("4. Find 'enctoken' and copy its value")
    print()
    
    enctoken = input("Paste your enctoken here: ").strip()
    
    if not enctoken:
        print("No token provided. Exiting.")
        return
    
    if len(enctoken) < 50:
        print(f"Warning: Token seems too short ({len(enctoken)} chars). Expected ~120 chars.")
        confirm = input("Continue anyway? (y/n): ")
        if confirm.lower() != 'y':
            return
    
    # Save to file
    token_file = Path(__file__).parent / "enctoken.txt"
    token_file.write_text(enctoken)
    
    print()
    print(f"✅ Enctoken saved to {token_file}")
    print(f"   Length: {len(enctoken)} characters")
    
    # Test the token
    print()
    print("Testing token...")
    
    import requests
    headers = {
        'Authorization': f'enctoken {enctoken}',
        'User-Agent': 'Mozilla/5.0'
    }
    
    # Test historical API
    url = 'https://kite.zerodha.com/orca/instruments/historical/738561/day?from=2026-01-01&to=2026-01-22'
    try:
        resp = requests.get(url, headers=headers, timeout=10)
        if resp.status_code == 200:
            data = resp.json()
            candles = data.get('data', {}).get('candles', [])
            print(f"✅ Token is working! Got {len(candles)} candles for RELIANCE")
            if candles:
                print(f"   Latest: {candles[-1]}")
        else:
            print(f"❌ Token test failed: HTTP {resp.status_code}")
            print(f"   Response: {resp.text[:200]}")
    except Exception as e:
        print(f"❌ Error testing token: {e}")


if __name__ == "__main__":
    main()
