"""Fetch extended daily history (2015 -> today) for the NIFTY-50 universe.

Writes data/daily_ext/<SYM>_day_ext.csv — does NOT touch data/daily/ (the
current backtest inputs). Chunked requests (Kite historical API caps ~2000
days per call), 0.4s spacing to respect rate limits, per-symbol validation
(monotonic dates, no duplicates), and a summary of actual coverage since
some symbols listed after 2015.
"""
import sys
import time
from pathlib import Path

import pandas as pd
import requests

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / 'kite' / 'live_monitor'))

from kite.live_monitor.monitor import LiveMonitor, NIFTY_50
from kite.live_monitor.data_fetcher import ZerodhaDataFetcher

OUT_DIR = ROOT / 'data' / 'daily_ext'
CHUNKS = [('2015-01-01', '2019-12-31'),
          ('2020-01-01', '2023-12-31'),
          ('2024-01-01', pd.Timestamp.now().strftime('%Y-%m-%d'))]


def fetch_range(fetcher, symbol, frm, to):
    token = fetcher.instruments.get(symbol)
    if token is None:
        return None
    url = f"{fetcher.BASE_URL}/instruments/historical/{token}/day"
    r = requests.get(url, headers=fetcher._get_headers(),
                     params={'from': frm, 'to': to, 'oi': 1}, timeout=30)
    if r.status_code != 200:
        print(f"  {symbol} {frm}->{to}: HTTP {r.status_code}")
        return None
    candles = r.json().get('data', {}).get('candles') or []
    if not candles:
        return None
    df = pd.DataFrame(candles, columns=['datetime', 'open', 'high', 'low',
                                        'close', 'volume', 'oi'])
    df['datetime'] = pd.to_datetime(df['datetime'])
    return df


def main():
    tok = LiveMonitor._auto_login()
    if not tok:
        sys.exit('auto-login failed')
    fetcher = ZerodhaDataFetcher(tok)
    OUT_DIR.mkdir(exist_ok=True)

    summary = []
    for i, sym in enumerate(NIFTY_50, 1):
        parts = []
        for frm, to in CHUNKS:
            part = fetch_range(fetcher, sym, frm, to)
            if part is not None:
                parts.append(part)
            time.sleep(0.4)
        if not parts:
            summary.append((sym, 'NO DATA', 0))
            print(f"[{i}/{len(NIFTY_50)}] {sym}: NO DATA")
            continue
        df = pd.concat(parts).drop_duplicates(subset='datetime').sort_values('datetime')
        assert df.datetime.is_monotonic_increasing, f"{sym}: non-monotonic dates"
        df.to_csv(OUT_DIR / f'{sym}_day_ext.csv', index=False)
        start = df.datetime.iloc[0].date()
        summary.append((sym, str(start), len(df)))
        print(f"[{i}/{len(NIFTY_50)}] {sym}: {start} -> {df.datetime.iloc[-1].date()} "
              f"({len(df)} bars)", flush=True)

    full = [s for s, start, _ in summary if start <= '2015-01-10']
    print(f"\n{len(full)}/{len(NIFTY_50)} symbols have full 2015 history")
    short = [(s, st) for s, st, _ in summary if st > '2015-01-10']
    if short:
        print("late starters:", ", ".join(f"{s}({st[:7]})" for s, st in short))


if __name__ == '__main__':
    main()
