"""
Loss pattern autopsy — EXPLORATORY analysis of 144 closed intraday paper trades.

Purpose: generate CANDIDATE HYPOTHESES about what separates losing trades from
winning ones. This is NOT a conclusion-generating script. Every reported pattern
carries an honesty label (STABLE / UNSTABLE / THIN) from a mandatory chronological
split-half stability rail. Only STABLE patterns are promoted to the final
candidate-hypotheses section, and even those are labeled with the caveat that
in-sample filter impact is optimistic by construction.

Inputs (READ-ONLY, no writes, no network):
  - trades:  incubator_trades_snapshot.db :: positions where status='closed'
  - minute bars: D:\\study\\kite\\data\\zerodha_data.db :: ohlcv (interval='minute')
             NOTE: minute-bar coverage is 2026-07-28 12:25 -> 2026-08-03 13:22.
             Trades entered outside that window (or before 09:15-10:15 is fully
             covered on a given day) get NaN for minute-bar-derived context
             features (entry-day gap, morning range). These are counted and
             reported, never silently dropped.
  - NIFTY daily closes: D:\\study\\kite\\kite\\research\\regime_exit_cache.csv
             (date, close only — no daily open). Used for day-direction (slice 6).
             For slice 7 (entry-day gap vs prior close) there is no daily "index
             open" column in the CSV, so index-open is approximated from the
             NIFTY 50 minute bar's first bar of the day where available. This
             inherits the same minute-bar coverage gap noted above, and is
             flagged as a judgment call in the results file.

Outputs:
  - kite/research/loss_pattern_autopsy_results.txt

Run: python loss_pattern_autopsy.py
"""

import sqlite3
import sys
from pathlib import Path

import numpy as np
import pandas as pd

TRADES_DB = r"C:\Users\pc\AppData\Local\Temp\claude\D--study-kite\94cfc2ac-0e8d-4aed-ba7c-1811916cc32d\scratchpad\incubator_trades_snapshot.db"
BARS_DB = r"D:\study\kite\data\zerodha_data.db"
NIFTY_CSV = r"D:\study\kite\kite\research\regime_exit_cache.csv"
OUT_PATH = Path(__file__).with_name("loss_pattern_autopsy_results.txt")

MINUTE_COVERAGE_START = pd.Timestamp("2026-07-28 12:25:00")
MINUTE_COVERAGE_END = pd.Timestamp("2026-08-03 13:22:00")

MIN_HALF_N = 8  # stability rail: each half's cell must have n >= this

OUT_LINES = []


def emit(line=""):
    """Print + buffer for the results file."""
    print(line)
    OUT_LINES.append(str(line))


# ---------------------------------------------------------------------------
# Generic helpers (these are what the self-check exercises)
# ---------------------------------------------------------------------------

def wr_pnl(d, pnl_col="pnl"):
    """n, win_rate, avg_pnl, total_pnl for a slice of trades. win = pnl>0."""
    n = len(d)
    if n == 0:
        return 0, float("nan"), float("nan"), float("nan")
    wins = int((d[pnl_col] > 0).sum())
    win_rate = wins / n
    avg_pnl = d[pnl_col].mean()
    total_pnl = d[pnl_col].sum()
    return n, win_rate, avg_pnl, total_pnl


def half_split(df):
    """Chronological first-half / second-half split by entry_time."""
    d = df.sort_values("entry_time").reset_index(drop=True)
    mid = len(d) // 2
    return d.iloc[:mid].copy(), d.iloc[mid:].copy()


def cell_effect(d, mask, pnl_col="pnl"):
    """
    Effect of a cell = cell win_rate - complement (rest of same df) win_rate.
    Returns (n_cell, win_rate_cell, effect) where effect sign is what the
    stability rail compares across halves.
    """
    cell = d[mask]
    rest = d[~mask]
    n_cell = len(cell)
    if n_cell == 0 or len(rest) == 0:
        return n_cell, float("nan"), float("nan")
    wr_cell = (cell[pnl_col] > 0).mean()
    wr_rest = (rest[pnl_col] > 0).mean()
    return n_cell, wr_cell, wr_cell - wr_rest


def stability_verdict(n1, eff1, n2, eff2, min_n=MIN_HALF_N):
    """
    STABLE only if: effect direction matches in both halves (same sign, both
    non-zero) AND each half's cell n >= min_n. Otherwise THIN (insufficient n)
    or UNSTABLE (direction flips or effect is ~0 in one half).
    """
    if n1 < min_n or n2 < min_n:
        return "THIN"
    if pd.isna(eff1) or pd.isna(eff2):
        return "THIN"
    if eff1 > 0 and eff2 > 0:
        return "STABLE (both +)"
    if eff1 < 0 and eff2 < 0:
        return "STABLE (both -)"
    return "UNSTABLE"


def tercile_rank(series):
    """
    Assign T1 (lowest third) / T2 / T3 (highest third) by rank, ties broken
    by first occurrence (deterministic, avoids pd.qcut duplicate-edge issues).
    NaNs stay NaN (not assigned a tercile).
    """
    s = series.copy()
    valid = s.dropna()
    if len(valid) < 3:
        return pd.Series([np.nan] * len(s), index=s.index)
    ranks = valid.rank(method="first")
    n = len(valid)
    bins = pd.cut(ranks, bins=3, labels=["T1", "T2", "T3"])
    out = pd.Series([np.nan] * len(s), index=s.index, dtype=object)
    out.loc[valid.index] = bins.astype(object)
    return out


def fmt_pct(x):
    return "NaN" if pd.isna(x) else f"{x*100:.1f}%"


def fmt_money(x):
    return "NaN" if pd.isna(x) else f"{x:,.1f}"


# ---------------------------------------------------------------------------
# SELF-CHECK: synthetic 10-trade frame, hand-computed expected answers
# ---------------------------------------------------------------------------

def build_synthetic_frame():
    rows = [
        # idx, symbol, direction, strategy, entry_time,          exit_reason,    pnl,  gross_pnl
        (1, "A", "BUY",  "s1", "2026-01-01 09:20:00", "take_profit",   100,  110),
        (2, "B", "SELL", "s1", "2026-01-01 09:40:00", "stop_loss",     -50,  -45),
        (3, "A", "BUY",  "s2", "2026-01-01 11:00:00", "take_profit",    80,   88),
        (4, "B", "SELL", "s2", "2026-01-02 09:25:00", "stop_loss",     -60,  -55),
        (5, "C", "BUY",  "s1", "2026-01-02 13:10:00", "trailing_stop",  30,   35),
        (6, "B", "SELL", "s3", "2026-01-02 14:00:00", "end_of_day",    -20,  -15),
        (7, "C", "BUY",  "s1", "2026-01-03 10:00:00", "take_profit",   120,  130),
        (8, "D", "SELL", "s2", "2026-01-03 12:00:00", "stop_loss",    -100,  -95),
        (9, "C", "BUY",  "s3", "2026-01-03 09:16:00", "manual",         10,   15),
        (10, "D", "SELL", "s1", "2026-01-03 14:50:00", "stop_loss",    -40,  -35),
    ]
    df = pd.DataFrame(rows, columns=["idx", "symbol", "direction", "strategy",
                                      "entry_time", "exit_reason", "pnl", "gross_pnl"])
    df["entry_time"] = pd.to_datetime(df["entry_time"])
    df["entry_date"] = df["entry_time"].dt.date
    # synthetic day-level nifty return, matched to entry_date
    day_ret = {pd.Timestamp("2026-01-01").date(): 0.005,
               pd.Timestamp("2026-01-02").date(): -0.003,
               pd.Timestamp("2026-01-03").date(): 0.002}
    df["nifty_day_return"] = df["entry_date"].map(day_ret)
    # synthetic day-level gap, matched to entry_date
    day_gap = {pd.Timestamp("2026-01-01").date(): 0.0010,
               pd.Timestamp("2026-01-02").date(): 0.0050,
               pd.Timestamp("2026-01-03").date(): 0.0120}
    df["entry_gap"] = df["entry_date"].map(day_gap)
    return df


def self_check():
    emit("=" * 70)
    emit("SELF-CHECK: synthetic 10-trade frame, hand-computed answers")
    emit("=" * 70)
    df = build_synthetic_frame()

    # --- entry time bucket (slice 1) ---
    def bucket(t):
        tt = t.time()
        if tt < pd.Timestamp("10:30:00").time():
            return "09:15-10:30"
        elif tt < pd.Timestamp("13:00:00").time():
            return "10:30-13:00"
        else:
            return "13:00-15:05"
    df["bucket"] = df["entry_time"].apply(bucket)
    b1 = df[df["bucket"] == "09:15-10:30"]
    b2 = df[df["bucket"] == "10:30-13:00"]
    b3 = df[df["bucket"] == "13:00-15:05"]
    assert set(b1["idx"]) == {1, 2, 4, 7, 9}, b1["idx"].tolist()
    assert set(b2["idx"]) == {3, 8}, b2["idx"].tolist()
    assert set(b3["idx"]) == {5, 6, 10}, b3["idx"].tolist()
    n, wr, avg, tot = wr_pnl(b1)
    assert n == 5 and abs(wr - 0.6) < 1e-9 and abs(avg - 24.0) < 1e-9, (n, wr, avg)
    n, wr, avg, tot = wr_pnl(b2)
    assert n == 2 and abs(wr - 0.5) < 1e-9 and abs(avg - (-10.0)) < 1e-9, (n, wr, avg)
    n, wr, avg, tot = wr_pnl(b3)
    assert n == 3 and abs(wr - 1/3) < 1e-9 and abs(avg - (-10.0)) < 1e-9, (n, wr, avg)
    emit("[OK] entry-time bucket grouping + win_rate/avg_pnl arithmetic")

    # --- direction (slice 3) ---
    n, wr, avg, tot = wr_pnl(df[df["direction"] == "BUY"])
    assert n == 5 and abs(wr - 1.0) < 1e-9 and abs(avg - 68.0) < 1e-9, (n, wr, avg)
    n, wr, avg, tot = wr_pnl(df[df["direction"] == "SELL"])
    assert n == 5 and abs(wr - 0.0) < 1e-9 and abs(avg - (-54.0)) < 1e-9, (n, wr, avg)
    emit("[OK] direction grouping (BUY 100% win / SELL 0% win by construction)")

    # --- strategy (used in slice 3 & 5) ---
    n, wr, avg, tot = wr_pnl(df[df["strategy"] == "s1"])
    assert n == 5 and abs(wr - 0.6) < 1e-9 and abs(avg - 32.0) < 1e-9, (n, wr, avg)
    n, wr, avg, tot = wr_pnl(df[df["strategy"] == "s2"])
    assert n == 3 and abs(wr - 1/3) < 1e-9 and abs(avg - (-80/3)) < 1e-6, (n, wr, avg)
    emit("[OK] strategy grouping")

    # --- symbol net P&L + repeat-loser flag (slice 4) ---
    sym = df.groupby("symbol")["pnl"].agg(["count", "sum"])
    assert sym.loc["A", "sum"] == 180 and sym.loc["A", "count"] == 2
    assert sym.loc["B", "sum"] == -130 and sym.loc["B", "count"] == 3
    assert sym.loc["C", "sum"] == 160 and sym.loc["C", "count"] == 3
    assert sym.loc["D", "sum"] == -140 and sym.loc["D", "count"] == 2
    losing_counts = df[df["pnl"] < 0].groupby("symbol").size()
    repeat_losers = set(losing_counts[losing_counts >= 3].index)
    assert repeat_losers == {"B"}, repeat_losers
    total_losses = -df.loc[df["pnl"] < 0, "pnl"].sum()
    assert total_losses == 270
    contrib = (-sym.loc[sym["sum"] < 0, "sum"] / total_losses)
    assert abs(contrib["B"] - 130/270) < 1e-9
    assert abs(contrib["D"] - 140/270) < 1e-9
    assert (contrib > 0.15).all()  # both B and D flagged >15% by construction
    emit("[OK] symbol net P&L, repeat-loser flag (B, >=3 losses), >15%-of-loss flag (B & D)")

    # --- strategy x exit_reason matrix (slice 5) ---
    mat = df.groupby(["strategy", "exit_reason"]).agg(n=("pnl", "size"), wins=("pnl", lambda s: (s > 0).sum()))
    assert mat.loc[("s1", "take_profit"), "n"] == 2
    assert mat.loc[("s1", "take_profit"), "wins"] == 2
    assert mat.loc[("s1", "stop_loss"), "n"] == 2
    assert mat.loc[("s1", "stop_loss"), "wins"] == 0
    assert mat.loc[("s2", "stop_loss"), "n"] == 2
    assert mat.loc[("s2", "stop_loss"), "wins"] == 0
    emit("[OK] strategy x exit_reason matrix cell counts")

    # --- NIFTY day direction x trade direction / with-tape (slice 6) ---
    df["nifty_up"] = df["nifty_day_return"] > 0
    df["with_tape"] = ((df["direction"] == "BUY") & df["nifty_up"]) | \
                       ((df["direction"] == "SELL") & ~df["nifty_up"])
    wt = df[df["with_tape"]]
    at = df[~df["with_tape"]]
    assert set(wt["idx"]) == {1, 3, 4, 6, 7, 9}, wt["idx"].tolist()
    assert set(at["idx"]) == {2, 5, 8, 10}, at["idx"].tolist()
    n, wr, avg, tot = wr_pnl(wt)
    assert n == 6 and abs(wr - 4/6) < 1e-9 and abs(avg - 230/6) < 1e-6, (n, wr, avg)
    n, wr, avg, tot = wr_pnl(at)
    assert n == 4 and abs(wr - 0.25) < 1e-9 and abs(avg - (-40.0)) < 1e-9, (n, wr, avg)
    emit("[OK] with-tape/against-tape tagging + win_rate/avg_pnl")

    # --- signal-cluster density (slice 9) ---
    day_counts = df.groupby("entry_date")["idx"].transform("count")
    df["day_bucket"] = np.where(day_counts <= 3, "1-3", "4+")
    lo = df[df["day_bucket"] == "1-3"]
    hi = df[df["day_bucket"] == "4+"]
    assert len(lo) == 6 and len(hi) == 4, (len(lo), len(hi))
    n, wr, avg, tot = wr_pnl(lo)
    assert n == 6 and abs(wr - 0.5) < 1e-9 and abs(avg - 80/6) < 1e-6, (n, wr, avg)
    n, wr, avg, tot = wr_pnl(hi)
    assert n == 4 and abs(wr - 0.5) < 1e-9 and abs(avg - (-2.5)) < 1e-9, (n, wr, avg)
    emit("[OK] signal-cluster density bucketing (1-3 vs 4+ trades/day)")

    # --- loss clustering (slice 10) ---
    day_loss = df[df["gross_pnl"] < 0].groupby("entry_date")["gross_pnl"].sum()
    assert abs(day_loss[pd.Timestamp("2026-01-01").date()] - (-45)) < 1e-9
    assert abs(day_loss[pd.Timestamp("2026-01-02").date()] - (-70)) < 1e-9
    assert abs(day_loss[pd.Timestamp("2026-01-03").date()] - (-130)) < 1e-9
    total_gross_loss = -day_loss.sum()
    assert abs(total_gross_loss - 245) < 1e-9
    worst3 = day_loss.sort_values().head(3)
    share = -worst3.sum() / total_gross_loss
    assert abs(share - 1.0) < 1e-9  # only 3 days exist in this toy set -> trivially 100%
    emit("[OK] day-level gross-loss aggregation + top-N share (degenerate 3-day case, share=100%)")

    # --- tercile helper, tested on a clean 9-element array (unambiguous thirds) ---
    clean = pd.Series([9, 1, 5, 3, 7, 2, 8, 4, 6], dtype=float)  # unordered on purpose
    t = tercile_rank(clean)
    lowmask = clean.isin([1, 2, 3])
    midmask = clean.isin([4, 5, 6])
    himask = clean.isin([7, 8, 9])
    assert (t[lowmask] == "T1").all()
    assert (t[midmask] == "T2").all()
    assert (t[himask] == "T3").all()
    # with a NaN present, it must stay NaN and not perturb the rest of the split
    with_nan = pd.concat([clean, pd.Series([np.nan])], ignore_index=True)
    t2 = tercile_rank(with_nan)
    assert pd.isna(t2.iloc[-1])
    emit("[OK] tercile_rank helper on clean 9-element array + NaN passthrough")

    # --- stability_verdict helper, hand-picked cases ---
    assert stability_verdict(10, 0.10, 10, 0.05) == "STABLE (both +)"
    assert stability_verdict(10, -0.10, 10, -0.05) == "STABLE (both -)"
    assert stability_verdict(10, 0.10, 10, -0.05) == "UNSTABLE"
    assert stability_verdict(5, 0.10, 10, 0.05) == "THIN"   # n1 < 8
    assert stability_verdict(10, 0.10, 5, 0.05) == "THIN"   # n2 < 8
    assert stability_verdict(8, 0.10, 8, 0.05) == "STABLE (both +)"  # boundary n=8 passes
    emit("[OK] stability_verdict helper (STABLE/UNSTABLE/THIN incl. n=8 boundary)")

    emit("SELF-CHECK: ALL ASSERTS PASSED")
    emit("")


# ---------------------------------------------------------------------------
# Data loading
# ---------------------------------------------------------------------------

def load_trades():
    conn = sqlite3.connect(f"file:{TRADES_DB}?mode=ro", uri=True)
    df = pd.read_sql("SELECT * FROM positions WHERE status='closed'", conn)
    conn.close()
    df["entry_time"] = pd.to_datetime(df["entry_time"])
    df["exit_time"] = pd.to_datetime(df["exit_time"])
    df["entry_date"] = df["entry_time"].dt.date
    df["win"] = df["pnl"] > 0
    df = df.sort_values("entry_time").reset_index(drop=True)
    df["trade_seq"] = np.arange(len(df))
    assert len(df) == 144, f"expected 144 closed trades, got {len(df)}"
    return df


def load_nifty_daily():
    df = pd.read_csv(NIFTY_CSV)
    df["date"] = pd.to_datetime(df["date"]).dt.date
    df = df.sort_values("date").reset_index(drop=True)
    df["prior_close"] = df["close"].shift(1)
    df["day_return"] = (df["close"] - df["prior_close"]) / df["prior_close"]
    return df


def load_minute_bars(symbols):
    conn = sqlite3.connect(f"file:{BARS_DB}?mode=ro", uri=True)
    placeholders = ",".join(["?"] * len(symbols))
    q = f"""SELECT symbol, datetime, open, high, low, close
            FROM ohlcv WHERE interval='minute' AND symbol IN ({placeholders})"""
    df = pd.read_sql(q, conn, params=list(symbols))
    conn.close()
    # datetime has mixed tz-aware/naive strings in this table; normalize by
    # stripping the +05:30 offset (all IST, all local trading-day timestamps).
    df["datetime"] = df["datetime"].str.replace(r"\+05:30$", "", regex=True)
    df["datetime"] = pd.to_datetime(df["datetime"])
    df["date"] = df["datetime"].dt.date
    return df


# ---------------------------------------------------------------------------
# Context feature construction
# ---------------------------------------------------------------------------

def build_context_features(trades, nifty_daily, bars):
    df = trades.copy()

    # slice 1: entry time bucket
    def bucket(t):
        tt = t.time()
        if tt < pd.Timestamp("10:30:00").time():
            return "09:15-10:30"
        elif tt < pd.Timestamp("13:00:00").time():
            return "10:30-13:00"
        else:
            return "13:00-15:05"
    df["time_bucket"] = df["entry_time"].apply(bucket)

    # slice 2: day of week
    df["day_of_week"] = df["entry_time"].dt.day_name()

    # slice 6: NIFTY day direction + with-tape
    ret_map = nifty_daily.set_index("date")["day_return"]
    df["nifty_day_return"] = df["entry_date"].map(ret_map)
    df["nifty_up"] = df["nifty_day_return"] > 0
    df["with_tape"] = np.where(
        df["nifty_day_return"].isna(), np.nan,
        np.where(((df["direction"] == "BUY") & df["nifty_up"]) |
                 ((df["direction"] == "SELL") & ~df["nifty_up"]), True, False))

    # slice 7: entry-day gap = |nifty_open - prior_close| / prior_close
    # nifty_open approximated from NIFTY 50 minute bar's first bar of day
    # (JUDGMENT CALL: daily CSV has no "open" column; only available where
    # minute-bar coverage includes 09:15 that day).
    nifty_bars = bars[bars["symbol"] == "NIFTY 50"]
    day_open = nifty_bars.sort_values("datetime").groupby("date")["open"].first()
    # only trust it as a true 09:15 open if the first bar of that day is <=09:16
    first_bar_time = nifty_bars.sort_values("datetime").groupby("date")["datetime"].first()
    valid_open_days = set(first_bar_time[first_bar_time.dt.time <= pd.Timestamp("09:16:00").time()].index)
    day_open = day_open[day_open.index.isin(valid_open_days)]
    prior_close_map = nifty_daily.set_index("date")["prior_close"]
    gap_by_day = {}
    for d in day_open.index:
        pc = prior_close_map.get(d, np.nan)
        if pd.notna(pc) and pc != 0:
            gap_by_day[d] = abs(day_open[d] - pc) / pc
    df["entry_gap"] = df["entry_date"].map(gap_by_day)
    df["gap_tercile"] = tercile_rank(df["entry_gap"])

    # slice 8: stock's own morning range (09:15-10:15) as % of open, at entry
    morning = bars[(bars["datetime"].dt.time >= pd.Timestamp("09:15:00").time()) &
                   (bars["datetime"].dt.time <= pd.Timestamp("10:15:00").time())]
    # require the window is actually fully populated for that symbol/day: the
    # first bar must be <=09:16 (so 09:15 present) - else treat as not covered.
    first_am = bars.sort_values("datetime").groupby(["symbol", "date"])["datetime"].first()
    covered = set(first_am[first_am.dt.time <= pd.Timestamp("09:16:00").time()].index)
    mrange = morning.groupby(["symbol", "date"]).agg(
        hi=("high", "max"), lo=("low", "min"), openp=("open", "first"))
    mrange = mrange[mrange.index.isin(covered)]
    mrange["range_pct"] = (mrange["hi"] - mrange["lo"]) / mrange["openp"]
    range_map = mrange["range_pct"].to_dict()
    df["morning_range_pct"] = df.apply(
        lambda r: range_map.get((r["symbol"], r["entry_date"]), np.nan), axis=1)
    df["morning_range_tercile"] = tercile_rank(df["morning_range_pct"])

    # slice 9: signal-cluster density
    day_counts = df.groupby("entry_date")["id"].transform("count")
    df["trades_same_day"] = day_counts
    df["other_trades_same_day"] = day_counts - 1
    df["day_density_bucket"] = np.where(day_counts <= 3, "1-3", "4+")

    return df


# ---------------------------------------------------------------------------
# NaN-context accounting
# ---------------------------------------------------------------------------

def report_nan_context(df, nifty_daily_dates):
    emit("-" * 70)
    emit("NaN-CONTEXT TRADE COUNTS (minute-bar / index-open derived features)")
    emit("-" * 70)
    after_cutoff = (df["entry_time"] > MINUTE_COVERAGE_END).sum()
    before_start = (df["entry_time"] < MINUTE_COVERAGE_START).sum()
    emit(f"Minute-bar coverage window: {MINUTE_COVERAGE_START} -> {MINUTE_COVERAGE_END}")
    emit(f"Trades entered AFTER minute-bar cutoff (2026-08-03 13:22): {after_cutoff}")
    emit(f"Trades entered BEFORE minute-bar coverage starts (2026-07-28 12:25): {before_start}")
    emit(f"Trades with NaN entry_gap (slice 7, no valid NIFTY 09:15 bar that day): "
         f"{df['entry_gap'].isna().sum()} / {len(df)}")
    emit(f"Trades with NaN morning_range_pct (slice 8, no full 09:15-10:15 bars for that symbol/day): "
         f"{df['morning_range_pct'].isna().sum()} / {len(df)}")
    emit(f"Trades with NaN nifty_day_return (slice 6, date missing from daily CSV): "
         f"{df['nifty_day_return'].isna().sum()} / {len(df)}")
    days_with_gap = sorted(set(df.loc[df['entry_gap'].notna(), 'entry_date']))
    days_with_morning = sorted(set(df.loc[df['morning_range_pct'].notna(), 'entry_date']))
    emit(f"Calendar days with usable entry_gap: {days_with_gap}")
    emit(f"Calendar days with usable morning_range_pct: {days_with_morning}")
    missing_csv_days = sorted(set(df["entry_date"]) - set(nifty_daily_dates))
    trading_day_gaps = [d for d in missing_csv_days if d.weekday() < 5]
    emit(f"DATA GAP: regime_exit_cache.csv has no row for these trade dates that are NOT "
         f"weekends: {trading_day_gaps} (out of all missing dates {missing_csv_days}). "
         f"2026-08-03 is a Monday with 11 trades and full minute-bar coverage, yet is absent "
         f"from the daily-close CSV — this is a genuine gap in that source file, not a "
         f"legitimate non-trading day. It removes those 11 trades from slice 6 and blocks "
         f"slice 7's gap feature for that day even though the NIFTY 50 minute bar has its open.")
    emit("")


# ---------------------------------------------------------------------------
# Per-slice report + stability rail application
# ---------------------------------------------------------------------------

def table_by_group(df, groupcol, pnl_col="pnl", label=None):
    emit(f"--- {label or groupcol} ---")
    g = df.groupby(groupcol, dropna=False)
    rows = []
    for name, d in g:
        n, wr, avg, tot = wr_pnl(d, pnl_col)
        rows.append((name, n, wr, avg, tot))
    rows.sort(key=lambda r: -r[1])
    emit(f"{'group':<20}{'n':>5}{'win%':>8}{'avg_pnl':>12}{'total_pnl':>14}")
    for name, n, wr, avg, tot in rows:
        emit(f"{str(name):<20}{n:>5}{fmt_pct(wr):>8}{fmt_money(avg):>12}{fmt_money(tot):>14}")
    emit("")
    return rows


def two_group_stability(df, mask_fn, cell_name, other_name, label, pnl_col="pnl"):
    """
    Apply the split-half stability rail to a binary cell-vs-rest (or cell-vs-
    named-other) comparison. mask_fn(d) -> boolean mask selecting the "cell".
    """
    h1, h2 = half_split(df)
    n1, wr1, eff1 = cell_effect(h1, mask_fn(h1), pnl_col)
    n2, wr2, eff2 = cell_effect(h2, mask_fn(h2), pnl_col)
    verdict = stability_verdict(n1, eff1, n2, eff2)
    full_n, full_wr, full_avg, full_tot = wr_pnl(df[mask_fn(df)], pnl_col)
    other_n, other_wr, other_avg, other_tot = wr_pnl(df[~mask_fn(df)], pnl_col)
    emit(f"[{label}] {cell_name} n={full_n} win%={fmt_pct(full_wr)} avg_pnl={fmt_money(full_avg)}  "
         f"vs {other_name} n={other_n} win%={fmt_pct(other_wr)} avg_pnl={fmt_money(other_avg)}")
    emit(f"    half1: n={n1} win%={fmt_pct(wr1)} effect(vs rest)={fmt_pct(eff1)}   "
         f"half2: n={n2} win%={fmt_pct(wr2)} effect(vs rest)={fmt_pct(eff2)}   => {verdict}")
    return {
        "label": label, "cell": cell_name, "n": full_n, "win_rate": full_wr,
        "avg_pnl": full_avg, "verdict": verdict, "n1": n1, "n2": n2,
        "eff1": eff1, "eff2": eff2,
    }


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main():
    self_check()

    trades = load_trades()
    nifty_daily = load_nifty_daily()
    symbols = sorted(trades["symbol"].unique().tolist()) + ["NIFTY 50"]
    bars = load_minute_bars(symbols)
    df = build_context_features(trades, nifty_daily, bars)

    emit("=" * 70)
    emit(f"LOSS PATTERN AUTOPSY — {len(df)} closed paper trades "
         f"({df['entry_date'].min()} -> {df['entry_date'].max()})")
    emit("EXPLORATORY. Candidate hypotheses only. See stability-rail verdicts.")
    emit("=" * 70)
    emit("")

    n, wr, avg, tot = wr_pnl(df)
    emit(f"OVERALL: n={n} win_rate={fmt_pct(wr)} avg_pnl={fmt_money(avg)} total_pnl={fmt_money(tot)}")
    emit("")

    report_nan_context(df, set(nifty_daily["date"]))

    findings = []  # collected stability results, for the candidate-hypotheses section

    # =====================================================================
    # SLICE 1: entry time bucket
    # =====================================================================
    emit("#" * 70)
    emit("SLICE 1: Entry time bucket")
    emit("#" * 70)
    table_by_group(df, "time_bucket", label="time_bucket")
    h1, h2 = half_split(df)
    for bucket_name in df["time_bucket"].unique():
        r = two_group_stability(df, lambda d, b=bucket_name: d["time_bucket"] == b,
                                 bucket_name, "other buckets", "slice1_time_bucket")
        findings.append(r)
    emit("")

    # =====================================================================
    # SLICE 2: day of week
    # =====================================================================
    emit("#" * 70)
    emit("SLICE 2: Day of week")
    emit("#" * 70)
    table_by_group(df, "day_of_week", label="day_of_week")
    for dow in df["day_of_week"].unique():
        r = two_group_stability(df, lambda d, x=dow: d["day_of_week"] == x,
                                 dow, "other days", "slice2_day_of_week")
        findings.append(r)
    emit("")

    # =====================================================================
    # SLICE 3: direction overall and per strategy
    # =====================================================================
    emit("#" * 70)
    emit("SLICE 3: Direction (BUY vs SELL), overall and per strategy")
    emit("#" * 70)
    table_by_group(df, "direction", label="direction (overall)")
    r = two_group_stability(df, lambda d: d["direction"] == "BUY", "BUY", "SELL", "slice3_direction_overall")
    findings.append(r)
    emit("NOTE: the stability effect above is a WIN-RATE difference (BUY win% higher than SELL's, "
         "consistently in both halves). BUY's avg_pnl and total_pnl are nonetheless WORSE than SELL's "
         "(bigger average loss per trade) — classic higher-hit-rate/worse-payoff pattern. Read the "
         "win-rate stability and the P&L direction as two separate claims, not one.")
    for strat in sorted(df["strategy"].unique()):
        sub = df[df["strategy"] == strat]
        emit(f"-- strategy={strat} (n={len(sub)}) --")
        table_by_group(sub, "direction", label=f"direction within {strat}")
        h1s, h2s = half_split(sub)
        n1, wr1, eff1 = cell_effect(h1s, h1s["direction"] == "BUY")
        n2, wr2, eff2 = cell_effect(h2s, h2s["direction"] == "BUY")
        verdict = stability_verdict(n1, eff1, n2, eff2)
        full_n_buy, full_wr_buy, full_avg_buy, _ = wr_pnl(sub[sub["direction"] == "BUY"])
        emit(f"    BUY vs SELL within {strat}: half1 n={n1} eff={fmt_pct(eff1)}  "
             f"half2 n={n2} eff={fmt_pct(eff2)} => {verdict}")
        findings.append({"label": f"slice3_direction_x_{strat}", "cell": f"BUY in {strat}",
                          "n": full_n_buy, "win_rate": full_wr_buy, "avg_pnl": full_avg_buy,
                          "verdict": verdict, "n1": n1, "n2": n2, "eff1": eff1, "eff2": eff2})
    emit("")

    # =====================================================================
    # SLICE 4: per-symbol net P&L, >15%-of-total-losses flag, repeat losers
    # =====================================================================
    emit("#" * 70)
    emit("SLICE 4: Per-symbol net P&L, loss concentration, repeat losers")
    emit("#" * 70)
    sym_rows = table_by_group(df, "symbol", label="symbol net P&L")
    total_losses = -df.loc[df["pnl"] < 0, "pnl"].sum()
    emit(f"Total (net pnl) losses across all trades: {fmt_money(-total_losses)}  "
         f"(sum of pnl<0 trades, magnitude={fmt_money(total_losses)})")
    sym_loss = df[df["pnl"] < 0].groupby("symbol")["pnl"].sum()
    flagged = sym_loss[(-sym_loss / total_losses) > 0.15].sort_values()
    if len(flagged):
        emit("Symbols contributing >15% of total (net) losses:")
        for s, v in flagged.items():
            emit(f"    {s}: net_loss={fmt_money(v)}  ({-v/total_losses*100:.1f}% of total losses)")
    else:
        emit("No single symbol contributes >15% of total losses.")
    losing_counts = df[df["pnl"] < 0].groupby("symbol").size()
    repeat_losers = losing_counts[losing_counts >= 3].sort_values(ascending=False)
    emit("Repeat-loser symbols (>=3 losing trades):")
    if len(repeat_losers):
        for s, c in repeat_losers.items():
            net = df[df["symbol"] == s]["pnl"].sum()
            emit(f"    {s}: {c} losing trades, symbol net_pnl={fmt_money(net)}")
    else:
        emit("    (none)")
    # stability: repeat-loser symbols - do they keep losing net in both halves?
    for s in repeat_losers.index:
        sub = df[df["symbol"] == s]
        h1s, h2s = half_split(df)
        n1 = (h1s["symbol"] == s).sum()
        n2 = (h2s["symbol"] == s).sum()
        eff1 = h1s.loc[h1s["symbol"] == s, "pnl"].mean() if n1 else np.nan
        eff2 = h2s.loc[h2s["symbol"] == s, "pnl"].mean() if n2 else np.nan
        verdict = stability_verdict(n1, eff1, n2, eff2)
        emit(f"    [{s}] avg_pnl half1(n={n1})={fmt_money(eff1)}  half2(n={n2})={fmt_money(eff2)} => {verdict} "
             f"(note: n<8 in per-symbol halves is expected -> THIN by construction)")
        findings.append({"label": "slice4_repeat_loser", "cell": s, "n": len(sub),
                          "win_rate": (sub["pnl"] > 0).mean(), "avg_pnl": sub["pnl"].mean(),
                          "verdict": verdict, "n1": n1, "n2": n2, "eff1": eff1, "eff2": eff2})
    emit("")

    # =====================================================================
    # SLICE 5: strategy x exit_reason matrix
    # =====================================================================
    emit("#" * 70)
    emit("SLICE 5: Strategy x exit_reason matrix")
    emit("#" * 70)
    mat = df.groupby(["strategy", "exit_reason"]).agg(
        n=("pnl", "size"), win_rate=("pnl", lambda s: (s > 0).mean()),
        avg_pnl=("pnl", "mean"), total_pnl=("pnl", "sum")).reset_index()
    mat = mat.sort_values(["strategy", "n"], ascending=[True, False])
    emit(f"{'strategy':<20}{'exit_reason':<16}{'n':>5}{'win%':>8}{'avg_pnl':>12}{'total_pnl':>14}")
    for _, r in mat.iterrows():
        emit(f"{r['strategy']:<20}{r['exit_reason']:<16}{r['n']:>5}{fmt_pct(r['win_rate']):>8}"
             f"{fmt_money(r['avg_pnl']):>12}{fmt_money(r['total_pnl']):>14}")
    emit("")
    # stability for each strategy x exit_reason cell present with enough n
    for _, r in mat.iterrows():
        strat, reason = r["strategy"], r["exit_reason"]
        mask_fn = lambda d, s=strat, e=reason: (d["strategy"] == s) & (d["exit_reason"] == e)
        res = two_group_stability(df, mask_fn, f"{strat}/{reason}", "everything else", "slice5_strategy_x_exit")
        findings.append(res)
    emit("")

    # =====================================================================
    # SLICE 6: NIFTY day direction x trade direction (with-tape vs against)
    # =====================================================================
    emit("#" * 70)
    emit("SLICE 6: NIFTY day direction x trade direction (with-tape vs against-tape)")
    emit("#" * 70)
    valid6 = df[df["nifty_day_return"].notna()].copy()
    emit(f"(n={len(valid6)}/{len(df)} trades have a usable nifty_day_return; "
         f"{df['nifty_day_return'].isna().sum()} NaN)")
    valid6["tape_label"] = np.where(valid6["with_tape"] == True, "with-tape", "against-tape")
    table_by_group(valid6, "tape_label", label="with-tape (trade direction matches index day direction) vs against-tape")
    r = two_group_stability(valid6, lambda d: d["with_tape"] == True, "with-tape", "against-tape", "slice6_with_tape")
    findings.append(r)
    emit("")

    # =====================================================================
    # SLICE 7: entry-day gap terciles
    # =====================================================================
    emit("#" * 70)
    emit("SLICE 7: Entry-day gap |index_open - prior_close|/prior_close, terciles")
    emit("#" * 70)
    emit("JUDGMENT CALL: daily CSV has no index-open column; index open approximated")
    emit("from the NIFTY 50 minute bar's first 09:15 bar where minute-bar coverage")
    emit("includes that day's open. This severely limits usable n (see NaN counts above).")
    valid7 = df[df["gap_tercile"].notna()].copy()
    emit(f"(n={len(valid7)}/{len(df)} trades have a usable gap tercile)")
    if len(valid7) >= 3:
        table_by_group(valid7, "gap_tercile", label="gap_tercile")
        for t in ["T1", "T2", "T3"]:
            if (valid7["gap_tercile"] == t).sum() > 0:
                r = two_group_stability(valid7, lambda d, tt=t: d["gap_tercile"] == tt,
                                         t, "other terciles", "slice7_gap_tercile")
                findings.append(r)
    else:
        emit("Insufficient data to form terciles.")
    emit("")

    # =====================================================================
    # SLICE 8: stock's own morning range (09:15-10:15) terciles
    # =====================================================================
    emit("#" * 70)
    emit("SLICE 8: Stock's own morning range (09:15-10:15, % of open) terciles at entry")
    emit("#" * 70)
    valid8 = df[df["morning_range_tercile"].notna()].copy()
    emit(f"(n={len(valid8)}/{len(df)} trades have a usable morning-range tercile)")
    if len(valid8) >= 3:
        table_by_group(valid8, "morning_range_tercile", label="morning_range_tercile")
        for t in ["T1", "T2", "T3"]:
            if (valid8["morning_range_tercile"] == t).sum() > 0:
                r = two_group_stability(valid8, lambda d, tt=t: d["morning_range_tercile"] == tt,
                                         t, "other terciles", "slice8_morning_range_tercile")
                findings.append(r)
    else:
        emit("Insufficient data to form terciles.")
    emit("")

    # =====================================================================
    # SLICE 9: signal-cluster density
    # =====================================================================
    emit("#" * 70)
    emit("SLICE 9: Signal-cluster density (other trades entered same day)")
    emit("#" * 70)
    table_by_group(df, "day_density_bucket", label="day_density_bucket")
    if (df["day_density_bucket"] == "1-3").sum() == 0:
        emit("NOTE: every trading day in this dataset had >=4 trades entered (min observed was 4, "
             "on 2026-07-31). The '1-3 trades/day' bucket is empty by construction — this slice has "
             "no variation to test against this population. Not a code bug; a genuine property of "
             "this signal-generation cadence.")
    r = two_group_stability(df, lambda d: d["day_density_bucket"] == "1-3", "1-3 trades/day", "4+ trades/day",
                             "slice9_density")
    findings.append(r)
    emit("")

    # =====================================================================
    # SLICE 10: loss clustering in calendar time
    # =====================================================================
    emit("#" * 70)
    emit("SLICE 10: Loss clustering — top-3 worst days' share of total gross losses")
    emit("#" * 70)
    day_gross_loss = df[df["gross_pnl"] < 0].groupby("entry_date")["gross_pnl"].sum().sort_values()
    total_gross_loss_mag = -day_gross_loss.sum()
    emit(f"{'date':<14}{'gross_loss_sum':>16}")
    for d, v in day_gross_loss.items():
        emit(f"{str(d):<14}{fmt_money(v):>16}")
    worst3 = day_gross_loss.head(3)
    share = -worst3.sum() / total_gross_loss_mag if total_gross_loss_mag else float("nan")
    emit(f"Total gross loss magnitude (sum over trades with gross_pnl<0, aggregated by day): "
         f"{fmt_money(total_gross_loss_mag)}")
    emit(f"Top-3 worst days: {list(worst3.index)} -> combined loss {fmt_money(-worst3.sum())} "
         f"= {share*100:.1f}% of total gross losses")
    # stability rail adaptation for slice 10 (not a per-trade cell comparison):
    # compute the same top-3-of-days concentration share independently within
    # each chronological half of the trades, and check both halves show
    # concentration (share clearly above the "evenly spread" baseline of 3/ndays).
    h1, h2 = half_split(df)
    def top3_share(d):
        dl = d[d["gross_pnl"] < 0].groupby("entry_date")["gross_pnl"].sum().sort_values()
        if len(dl) == 0:
            return 0, float("nan"), 0
        tot = -dl.sum()
        w3 = dl.head(3)
        sh = -w3.sum() / tot if tot else float("nan")
        baseline = min(3, len(dl)) / len(dl)
        return len(d), sh, baseline
    n1, sh1, base1 = top3_share(h1)
    n2, sh2, base2 = top3_share(h2)
    eff1 = sh1 - base1
    eff2 = sh2 - base2
    verdict = stability_verdict(n1, eff1, n2, eff2)
    emit(f"Half1 (n={n1}): top-3-day share={fmt_pct(sh1)} vs even-spread baseline={fmt_pct(base1)} "
         f"(concentration effect={fmt_pct(eff1)})")
    emit(f"Half2 (n={n2}): top-3-day share={fmt_pct(sh2)} vs even-spread baseline={fmt_pct(base2)} "
         f"(concentration effect={fmt_pct(eff2)})")
    emit(f"=> {verdict}  (ADAPTED stability check: 'effect' = observed top-3-day share minus what an "
         f"evenly-spread distribution across that half's loss-days would give; n is the half's trade count, "
         f"not a per-cell count, since this slice describes calendar concentration, not a trade attribute)")
    findings.append({"label": "slice10_loss_clustering", "cell": "top-3 worst days",
                      "n": len(df), "win_rate": float("nan"), "avg_pnl": float("nan"),
                      "verdict": verdict, "n1": n1, "n2": n2, "eff1": eff1, "eff2": eff2,
                      "extra": f"full-sample share={share*100:.1f}%"})
    emit("")

    # =====================================================================
    # CANDIDATE HYPOTHESES (STABLE only)
    # =====================================================================
    emit("=" * 70)
    emit("CANDIDATE HYPOTHESES (STABLE patterns only)")
    emit("=" * 70)
    emit("Every filter's in-sample P&L impact is optimistic by construction (it is")
    emit("measured on the same 144 trades that produced the rule). None of this is")
    emit("validated out-of-sample. Do not act on this without forward testing.")
    emit("")
    stable = [f for f in findings if str(f["verdict"]).startswith("STABLE")]
    if not stable:
        emit("No pattern in any of the 10 pre-registered slices survived the split-half")
        emit("stability rail. This itself is a finding: nothing here should override the")
        emit("existing skepticism default (140+ backtests, nothing beating buy-and-hold).")
    else:
        base_n, base_wr, base_avg, base_tot = wr_pnl(df)
        for f in stable:
            emit(f"- [{f['label']}] cell='{f['cell']}'  n={f['n']} win_rate={fmt_pct(f['win_rate'])} "
                 f"avg_pnl={fmt_money(f['avg_pnl'])}  half1_eff={fmt_pct(f['eff1'])} half2_eff={fmt_pct(f['eff2'])}")
            skip_mask = None
            # only construct a concrete filter rule for trade-level cells (skip
            # the slice10 pseudo-cell, which isn't a per-trade filter)
            if f["label"] == "slice1_time_bucket":
                skip_mask = df["time_bucket"] == f["cell"]
            elif f["label"] == "slice2_day_of_week":
                skip_mask = df["day_of_week"] == f["cell"]
            elif f["label"] == "slice3_direction_overall":
                skip_mask = df["direction"] == f["cell"]
            elif f["label"].startswith("slice3_direction_x_"):
                strat = f["label"].replace("slice3_direction_x_", "")
                skip_mask = (df["strategy"] == strat) & (df["direction"] == "BUY")
            elif f["label"] == "slice4_repeat_loser":
                skip_mask = df["symbol"] == f["cell"]
            elif f["label"] == "slice5_strategy_x_exit":
                strat, reason = f["cell"].split("/")
                skip_mask = (df["strategy"] == strat) & (df["exit_reason"] == reason)
            elif f["label"] == "slice6_with_tape":
                skip_mask = valid6["with_tape"] == (f["cell"] == "with-tape")
                skip_mask = skip_mask.reindex(df.index, fill_value=False)
            elif f["label"] == "slice7_gap_tercile":
                skip_mask = df["gap_tercile"] == f["cell"]
            elif f["label"] == "slice8_morning_range_tercile":
                skip_mask = df["morning_range_tercile"] == f["cell"]
            elif f["label"] == "slice9_density":
                skip_mask = df["day_density_bucket"] == f["cell"]

            if skip_mask is not None and f["avg_pnl"] < 0 and skip_mask.sum() > 0:
                kept = df[~skip_mask.fillna(False)]
                kn, kwr, kavg, ktot = wr_pnl(kept)
                emit(f"    FILTER RULE: skip trades where [{f['label']}] cell='{f['cell']}' "
                     f"(removes {int(skip_mask.sum())} trades)")
                emit(f"    with filter:  n={kn} win_rate={fmt_pct(kwr)} total_pnl={fmt_money(ktot)}")
                emit(f"    without filter (baseline): n={base_n} win_rate={fmt_pct(base_wr)} total_pnl={fmt_money(base_tot)}")
                emit(f"    in-sample impact: total_pnl {fmt_money(base_tot)} -> {fmt_money(ktot)} "
                     f"({fmt_money(ktot - base_tot)} change) — OPTIMISTIC, in-sample only.")
            elif skip_mask is None:
                emit("    (not a per-trade cell — no 'skip' filter rule applies; this slice describes "
                     "a calendar/structural pattern, not a trade attribute to filter on)")
            else:
                emit("    (positive-avg_pnl cell — no 'skip' rule constructed; this is a "
                     "keep/lean-into candidate, not a loss-avoidance filter)")
            emit("")

    emit("=" * 70)
    emit("END OF REPORT")
    emit("=" * 70)

    OUT_PATH.write_text("\n".join(OUT_LINES), encoding="utf-8")
    print(f"\nWrote {OUT_PATH}")


if __name__ == "__main__":
    main()
