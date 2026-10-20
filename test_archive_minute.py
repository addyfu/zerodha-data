import sqlite3
import subprocess
import sys
import tempfile
from pathlib import Path

import pyarrow.parquet as pq
import requests
import yaml

ROOT = Path(__file__).parent
DATES = [f"2026-10-{d:02d}" for d in (1, 2, 5, 6, 7, 8, 9, 12)]


def make_db(path, thin_date=None):
    c = sqlite3.connect(path)
    c.execute("""CREATE TABLE ohlcv (id INTEGER PRIMARY KEY AUTOINCREMENT,
        symbol TEXT NOT NULL, datetime TEXT NOT NULL, interval TEXT NOT NULL,
        open REAL, high REAL, low REAL, close REAL, volume INTEGER,
        oi INTEGER DEFAULT 0, UNIQUE(symbol, datetime, interval))""")
    c.execute("CREATE INDEX idx_symbol_datetime ON ohlcv(symbol, datetime)")
    ins = ("INSERT INTO ohlcv(symbol,datetime,interval,open,high,low,close,volume,oi)"
           " VALUES (?,?,?,1.0,2.0,0.5,1.5,10,0)")
    for d in DATES:
        for s in ["AAA", "BBB", "CCC"]:
            if d == thin_date and s != "AAA":
                continue
            for m in range(4):
                c.execute(ins, (s, f"{d} 09:{15 + m}:00+05:30", "minute"))
        c.execute(ins, ("AAA", f"{d} 00:00:00+05:30", "day"))
    c.commit()
    c.close()


def run(db, out, *args):
    return subprocess.run([sys.executable, str(ROOT / "archive_minute.py"), "--db", db,
                           "--out", out, "--min-symbols", "2", *args],
                          capture_output=True, text=True)


def db_dates(db):
    c = sqlite3.connect(db)
    r = sorted(x[0] for x in c.execute("SELECT DISTINCT substr(datetime,1,10) FROM ohlcv"))
    c.close()
    return r


def files(out):
    return sorted(p.name for p in Path(out).glob("*.parquet"))


with tempfile.TemporaryDirectory() as t:
    t = Path(t)

    # (a) default run
    db, out = str(t / "a.db"), str(t / "a_out")
    make_db(db)
    r = run(db, out)
    assert r.returncode == 0, r.stdout + r.stderr
    assert db_dates(db) == DATES[-5:], db_dates(db)
    for d in DATES[-5:]:
        tbl = pq.read_table(Path(out) / f"minute_{d}.parquet")
        assert tbl.num_rows == 12, tbl.num_rows  # 3 symbols x 4 bars, 'day' row excluded
        assert tbl.column_names == ["symbol", "datetime", "open", "high", "low",
                                    "close", "volume", "oi"]
    # older dates are exported too: pruning requires a parquet first
    assert files(out) == [f"minute_{d}.parquet" for d in DATES]
    print("a ok")

    # (b) thin date outside the keep window: written, pruned, exit 3
    db, out = str(t / "b.db"), str(t / "b_out")
    thin = DATES[2]
    make_db(db, thin_date=thin)
    r = run(db, out)
    assert r.returncode == 3 and f"THIN: {thin}" in r.stdout, r.stdout
    assert f"minute_{thin}.parquet" in files(out)
    assert pq.read_table(Path(out) / f"minute_{thin}.parquet").num_rows == 4
    assert db_dates(db) == DATES[-5:]
    # thin date inside the keep window: written, kept, exit 3
    db2, out2 = str(t / "b2.db"), str(t / "b2_out")
    make_db(db2, thin_date=DATES[-1])
    r = run(db2, out2, "--recent", "2")
    assert r.returncode == 3 and f"minute_{DATES[-1]}.parquet" in files(out2)
    assert DATES[-1] in db_dates(db2)
    print("b ok")

    # (c) all-dates, no-prune
    db, out = str(t / "c.db"), str(t / "c_out")
    make_db(db)
    before = Path(db).read_bytes()
    r = run(db, out, "--all-dates", "--no-prune")
    assert r.returncode == 0, r.stdout + r.stderr
    assert len(files(out)) == 8
    assert Path(db).read_bytes() == before and db_dates(db) == DATES
    print("c ok")

    # (d) loader from a pre-filled cache, zero HTTP
    sys.path.insert(0, str(ROOT))
    import minute_history

    def boom(*a, **k):
        raise AssertionError("HTTP call made")
    requests.get = boom
    df = minute_history.load_minute(DATES[0], DATES[1], cache_dir=out)
    assert len(df) == 24, len(df)
    df = minute_history.load_minute(DATES[0], DATES[1], symbols=["BBB"], cache_dir=out)
    assert len(df) == 8 and set(df.symbol) == {"BBB"}
    assert minute_history.missing_dates("2026-10-01", "2026-10-02", out) == []
    assert minute_history.missing_dates("2026-10-03", "2026-10-04", out) == []  # weekend
    assert minute_history.missing_dates("2026-10-13", "2026-10-13", out) == ["2026-10-13"]
    print("d ok")

    # (e) shell syntax + yaml
    subprocess.run(["bash", "-n", "upload_minute_parquet.sh"], check=True, cwd=ROOT)
    y = yaml.safe_load(open(ROOT / ".github/workflows/collect_data.yml", encoding="utf-8"))
    assert "collect" in y["jobs"]
    print("e ok")

print("ALL PASS")
