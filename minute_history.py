"""Research loader for the per-day minute Parquet files on GitHub releases."""
from datetime import date, timedelta
from pathlib import Path

import pandas as pd
import pyarrow.parquet as pq
import requests

URL = "https://github.com/addyfu/zerodha-data/releases/download/minute-{ym}/minute_{d}.parquet"


def _weekdays(start, end):
    d, e = date.fromisoformat(start), date.fromisoformat(end)
    while d <= e:
        if d.weekday() < 5:
            yield d.isoformat()
        d += timedelta(days=1)


def missing_dates(start, end, cache_dir="data/minute_parquet"):
    """Weekdays in [start, end] with no cached parquet file."""
    return [d for d in _weekdays(start, end)
            if not (Path(cache_dir) / f"minute_{d}.parquet").exists()]


def load_minute(start, end, symbols=None, cache_dir="data/minute_parquet"):
    cache = Path(cache_dir)
    cache.mkdir(parents=True, exist_ok=True)
    filters = [("symbol", "in", list(symbols))] if symbols else None
    frames = []
    for d in _weekdays(start, end):
        path = cache / f"minute_{d}.parquet"
        if not path.exists():
            r = requests.get(URL.format(ym=d[:7], d=d), timeout=120)
            if r.status_code == 404:  # holiday / not archived: skip
                continue
            r.raise_for_status()
            path.write_bytes(r.content)
        frames.append(pq.read_table(path, filters=filters).to_pandas())
    if not frames:
        return pd.DataFrame(columns=["symbol", "datetime", "open", "high",
                                     "low", "close", "volume", "oi"])
    return pd.concat(frames, ignore_index=True)
