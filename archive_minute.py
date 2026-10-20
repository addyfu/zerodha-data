"""Archive minute bars from the collector SQLite DB into one Parquet file per
trading day, then (optionally) prune the DB down to the newest N dates.

One pass over the table, no matter how many dates are exported: the ohlcv
table has no index on datetime alone, so a query per date would rescan the
whole file each time. Rows are streamed in chunks and routed to one open
Parquet writer per date, so memory stays flat.
"""
import argparse
import os
import sqlite3
import sys
from pathlib import Path

import pyarrow as pa
import pyarrow.parquet as pq

COLS = ["symbol", "datetime", "open", "high", "low", "close", "volume", "oi"]
SCHEMA = pa.schema([
    ("symbol", pa.string()), ("datetime", pa.string()),
    ("open", pa.float64()), ("high", pa.float64()),
    ("low", pa.float64()), ("close", pa.float64()),
    ("volume", pa.int64()), ("oi", pa.int64()),
])
CHUNK = 200_000


def parquet_name(d):
    return f"minute_{d}.parquet"


def export_dates(conn, targets, out, min_symbols):
    """Write one parquet per date in `targets`. Returns (stats, thin)."""
    out.mkdir(parents=True, exist_ok=True)
    state = {}  # date -> [writer, tmp_path, rows, symbols]
    cur = conn.execute(
        f"SELECT {','.join(COLS)} FROM ohlcv "
        "WHERE interval='minute' AND datetime >= ?", (min(targets),))
    try:
        while True:
            rows = cur.fetchmany(CHUNK)
            if not rows:
                break
            by_date = {}
            for r in rows:
                d = r[1][:10]
                if d in targets:
                    by_date.setdefault(d, []).append(r)
            for d, rs in by_date.items():
                if d not in state:
                    tmp = out / (parquet_name(d) + ".part")
                    state[d] = [pq.ParquetWriter(tmp, SCHEMA, compression="zstd"),
                                tmp, 0, set()]
                st = state[d]
                cols = list(zip(*rs))
                st[0].write_table(pa.Table.from_arrays(
                    [pa.array(c, type=f.type) for c, f in zip(cols, SCHEMA)],
                    schema=SCHEMA))
                st[2] += len(rs)
                st[3].update(cols[0])
    finally:
        for st in state.values():
            st[0].close()

    stats, thin = {}, []
    for d in sorted(targets):
        final = out / parquet_name(d)
        if d in state:
            _, tmp, n, syms = state[d]
            os.replace(tmp, final)
        else:  # date has no minute rows: write an empty file so prune can proceed
            n, syms = 0, set()
            pq.write_table(SCHEMA.empty_table(), final, compression="zstd")
        if len(syms) < min_symbols:
            thin.append((d, len(syms)))
        stats[d] = (n, len(syms), final.stat().st_size / 1e6)
    return stats, thin


def main(argv=None):
    ap = argparse.ArgumentParser()
    ap.add_argument("--db", required=True)
    ap.add_argument("--out", required=True)
    ap.add_argument("--recent", type=int, default=5)
    ap.add_argument("--keep", type=int, default=5)
    ap.add_argument("--min-symbols", type=int, default=1000)
    ap.add_argument("--all-dates", action="store_true")
    ap.add_argument("--no-prune", action="store_true")
    a = ap.parse_args(argv)

    out = Path(a.out)
    size_before = os.path.getsize(a.db)
    if a.no_prune:  # read-only: DB must stay untouched
        conn = sqlite3.connect(f"file:{Path(a.db).resolve().as_posix()}?mode=ro", uri=True)
    else:
        conn = sqlite3.connect(a.db)

    dates = sorted(r[0] for r in conn.execute(
        "SELECT DISTINCT substr(datetime,1,10) FROM ohlcv"))
    if not dates:
        print("no data in DB")
        return 1

    doomed = dates[:-a.keep] if a.keep > 0 else list(dates)
    targets = set(dates) if a.all_dates else set(dates[-a.recent:])
    if not a.no_prune:
        # every date we may delete must be exported first
        targets |= set(doomed)

    stats, thin = export_dates(conn, targets, out, a.min_symbols)

    print(f"{'date':<12}{'rows':>12}{'symbols':>9}{'parquet MB':>12}")
    for d, (n, s, mb) in stats.items():
        print(f"{d:<12}{n:>12,}{s:>9}{mb:>12.1f}")
    for d, s in thin:
        print(f"THIN: {d} symbols={s} < {a.min_symbols}")

    pruned = []
    if not a.no_prune:
        # only dates with a parquet file (written now or already in --out)
        safe = [d for d in doomed if (out / parquet_name(d)).exists()]
        skipped = [d for d in doomed if d not in safe]
        if skipped:
            print(f"NOT pruned (no parquet): {', '.join(skipped)}")
        if safe:
            marks = ",".join("?" * len(safe))
            conn.execute(
                f"DELETE FROM ohlcv WHERE substr(datetime,1,10) IN ({marks})", safe)
            conn.commit()
            conn.execute("VACUUM")
            pruned = safe
    conn.close()

    print(f"pruned dates: {pruned or 'none'}")
    print(f"DB size: {size_before/1e6:.1f} MB -> {os.path.getsize(a.db)/1e6:.1f} MB")
    return 3 if thin else 0


if __name__ == "__main__":
    sys.exit(main())
