"""Fetch 2015->today daily bars for the top-800 liquid NSE universe
(kite/research/universe_symbols.csv) into data/daily_universe/.
Chunked like fetch_extended_daily; symbols listed after 2015 keep partial history.
"""
import sys
import time
from pathlib import Path

import pandas as pd

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / 'kite' / 'live_monitor'))

from kite.live_monitor.monitor import LiveMonitor
from kite.live_monitor.data_fetcher import ZerodhaDataFetcher
from fetch_extended_daily import fetch_range, CHUNKS

OUT = ROOT / 'data' / 'daily_universe'
SYMS = pd.read_csv(ROOT / 'kite' / 'research' / 'universe_symbols.csv').symbol.tolist()


def main():
    tok = LiveMonitor._auto_login()
    if not tok:
        sys.exit('auto-login failed')
    fetcher = ZerodhaDataFetcher(tok)
    OUT.mkdir(exist_ok=True)
    done = skipped = 0
    for i, sym in enumerate(SYMS, 1):
        out = OUT / f'{sym}_day.csv'
        if out.exists():
            done += 1
            continue
        parts = []
        for frm, to in CHUNKS:
            for attempt in (1, 2):
                try:
                    p = fetch_range(fetcher, sym, frm, to)
                    if p is not None:
                        parts.append(p)
                    break
                except Exception as e:
                    print(f'  {sym} attempt {attempt}: {type(e).__name__}', flush=True)
                    time.sleep(3)
            time.sleep(0.35)
        if not parts:
            skipped += 1
            print(f'[{i}/{len(SYMS)}] {sym}: NO DATA', flush=True)
            continue
        df = pd.concat(parts)
        df['d'] = df.datetime.dt.tz_localize(None).dt.normalize()
        df = df.drop_duplicates(subset='d', keep='last').drop(columns='d').sort_values('datetime')
        df.to_csv(out, index=False)
        done += 1
        if i % 50 == 0:
            print(f'[{i}/{len(SYMS)}] ... {done} fetched, {skipped} no-data', flush=True)
    print(f'DONE: {done} fetched, {skipped} no-data', flush=True)


if __name__ == '__main__':
    main()
