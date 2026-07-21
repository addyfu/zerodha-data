"""Generate the frozen Expectation Book cards for every live strategy.

Implements section 3.1 of docs/superpowers/specs/2026-07-21-parity-monitor-design.md
("Expectation Book"). One JSON card per live strategy is written to
kite/live_monitor/expectations/<strategy>.json. Cards are tracked files —
regenerating one requires a git commit, so expectation drift can never be
silent (see spec section 3.1 and premortem item 3).

Stat sources (frozen per the pre-registered spec, do not improvise new ones):
  - momo_rotation_63            <- kite/research/lab_results.csv
  - rsi_trend_confirmation,
    cci_divergence              <- kite/research/retest_results.csv
  - choppiness_filter, bb_mean_reversion, adx_filter,
    cci_divergence_intraday     <- kite/reports/walkforward_audit.csv

Fields NOT included on any card, deliberately: avg_win_pct / avg_loss_pct
(no per-trade win/loss magnitude column exists in any of the three source
CSVs — only aggregate win% counts) and trades_per_month.hard_min_window_days
(a monitor-policy constant, not a backtest statistic; the spec gives no
formula for it and part 1 of the build plan is cards-only). Both are left
out rather than fabricated, per the spec's "fail loud, never fabricate" rule
in the task brief. parity_monitor.py (build step 2) can add a policy default
for hard_min_window_days when it is written; it is not a stat this script
owns.

Usage:
    python kite/live_monitor/gen_expectations.py
"""
from __future__ import annotations

import csv
import datetime
import json
import subprocess
import sys
from math import floor, log10
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
RESEARCH_DIR = REPO_ROOT / "kite" / "research"
REPORTS_DIR = REPO_ROOT / "kite" / "reports"
STRATEGIES_DIR = REPO_ROOT / "kite" / "strategies"
LIVE_MONITOR_DIR = REPO_ROOT / "kite" / "live_monitor"
OUT_DIR = LIVE_MONITOR_DIR / "expectations"

LAB_RESULTS_CSV = RESEARCH_DIR / "lab_results.csv"
RETEST_RESULTS_CSV = RESEARCH_DIR / "retest_results.csv"
WALKFORWARD_AUDIT_CSV = REPORTS_DIR / "walkforward_audit.csv"

MOMO_FILE = LIVE_MONITOR_DIR / "momentum_rotation.py"

SLIPPAGE_ASSUMED_PCT = 0.05
POOL_MONTHS = 66  # train (2020-07..2024-06) + val (2024-07..2026-01), ~66mo
GENERATED = datetime.date.today().isoformat()

# Intraday walkforward audit sample -> live universe extrapolation factors.
# Audit sample: 5 trading days over 5 stocks. Live universe: 47 stocks.
WF_STOCK_SCALE = 47 / 5
WF_DAY_SCALE = 21 / 5


class MissingStatsRow(RuntimeError):
    """Raised when a required strategy row is absent from its source CSV."""


def round_sig(x: float, sig: int = 4) -> float:
    """Round x to `sig` significant figures. 0 and non-finite pass through."""
    if x == 0 or not isinstance(x, (int, float)):
        return 0.0
    d = sig - int(floor(log10(abs(x)))) - 1
    return round(x, d)


def git_hash(path: Path) -> str:
    """Short git commit hash of the last commit touching `path`. Fails loud."""
    rel = path.resolve().relative_to(REPO_ROOT).as_posix()
    result = subprocess.run(
        ["git", "log", "-1", "--format=%h", "--", rel],
        cwd=REPO_ROOT,
        capture_output=True,
        text=True,
        check=True,
    )
    out = result.stdout.strip()
    if not out:
        raise MissingStatsRow(
            f"git has no commit history for {rel!r} — cannot stamp code_hash. "
            "Commit the strategy file before generating its expectation card."
        )
    return out


# ---------------------------------------------------------------------------
# CSV loaders
# ---------------------------------------------------------------------------

def _read_csv_rows(path: Path) -> list[dict]:
    if not path.exists():
        raise MissingStatsRow(f"stats source file not found: {path}")
    with open(path, newline="", encoding="utf-8") as f:
        return list(csv.DictReader(f))


def load_lab_row(name_contains: str) -> dict:
    rows = _read_csv_rows(LAB_RESULTS_CSV)
    for row in rows:
        if name_contains in row.get("name", ""):
            return row
    raise MissingStatsRow(
        f"no row containing {name_contains!r} in {LAB_RESULTS_CSV}"
    )


def load_retest_row(strategy: str) -> dict:
    rows = _read_csv_rows(RETEST_RESULTS_CSV)
    for row in rows:
        if row.get("strategy") == strategy:
            if row.get("leak") not in ("clean",):
                raise MissingStatsRow(
                    f"{strategy!r} row in {RETEST_RESULTS_CSV} is not clean "
                    f"(leak={row.get('leak')!r}) — refusing to build a card "
                    "on tainted stats."
                )
            return row
    raise MissingStatsRow(f"no row for {strategy!r} in {RETEST_RESULTS_CSV}")


def load_wf_row(strategy: str) -> dict:
    rows = _read_csv_rows(WALKFORWARD_AUDIT_CSV)
    for row in rows:
        if row.get("strategy") == strategy:
            return row
    raise MissingStatsRow(f"no row for {strategy!r} in {WALKFORWARD_AUDIT_CSV}")


def _f(row: dict, key: str) -> float:
    val = row.get(key)
    if val is None or val == "":
        raise MissingStatsRow(f"missing/blank field {key!r} in row {row!r}")
    return float(val)


# ---------------------------------------------------------------------------
# Card builders
# ---------------------------------------------------------------------------

def gen_card_momo() -> dict:
    """momo_rotation_63 — book main, cadence monthly, kite/research/lab_results.csv."""
    row = load_lab_row("momo lb=63 n=3 regime=True")
    t_trades, v_trades = _f(row, "t_trades"), _f(row, "v_trades")
    t_win, v_win = _f(row, "t_win%"), _f(row, "v_win%")
    t_maxdd, v_maxdd = _f(row, "t_maxdd%"), _f(row, "v_maxdd%")

    trades = t_trades + v_trades
    lam = trades / POOL_MONTHS
    pooled_win_pct = (t_trades * t_win + v_trades * v_win) / trades
    worse_dd = min(t_maxdd, v_maxdd)  # more negative = worse

    return {
        "strategy": "momo_rotation_63",
        "book": "main",
        "cadence": "monthly",
        "trades_per_month": {"lambda": round_sig(lam)},
        "win_rate": {"p": round_sig(pooled_win_pct / 100), "n_backtest": int(trades)},
        "max_drawdown_pct": round_sig(worse_dd),
        "hold_days": {"p50": 31, "p95": 92},
        "slippage_assumed_pct": SLIPPAGE_ASSUMED_PCT,
        "generated": GENERATED,
        "source": (
            "kite/research/lab_results.csv row 'momo lb=63 n=3 regime=True' "
            f"(train+val pooled, {POOL_MONTHS}mo)"
        ),
        "code_hash": git_hash(MOMO_FILE),
    }


def gen_card_swing(strategy: str) -> dict:
    """rsi_trend_confirmation / cci_divergence — book incubator, cadence
    daily-swing, kite/research/retest_results.csv."""
    row = load_retest_row(strategy)
    t_trades, v_trades = _f(row, "t_trades"), _f(row, "v_trades")
    t_win, v_win = _f(row, "t_win"), _f(row, "v_win")
    t_maxdd, v_maxdd = _f(row, "t_maxdd"), _f(row, "v_maxdd")

    trades = t_trades + v_trades
    lam = trades / POOL_MONTHS
    pooled_win_pct = (t_trades * t_win + v_trades * v_win) / trades
    worse_dd = min(t_maxdd, v_maxdd)

    return {
        "strategy": strategy,
        "book": "incubator",
        "cadence": "daily-swing",
        "trades_per_month": {"lambda": round_sig(lam)},
        "win_rate": {"p": round_sig(pooled_win_pct / 100), "n_backtest": int(trades)},
        "max_drawdown_pct": round_sig(worse_dd),
        "hold_days": {"p50": 8, "p95": 30},
        "slippage_assumed_pct": SLIPPAGE_ASSUMED_PCT,
        "generated": GENERATED,
        "source": (
            f"kite/research/retest_results.csv row '{strategy}' "
            f"(train+val pooled, {POOL_MONTHS}mo)"
        ),
        "code_hash": git_hash(STRATEGIES_DIR / f"{strategy}.py"),
    }


def gen_card_intraday(card_name: str, source_strategy: str) -> dict:
    """Intraday incubator strategies — book incubator, cadence intraday,
    kite/reports/walkforward_audit.csv wf_trades column.

    card_name: the live strategy name the card is filed under
    source_strategy: the row name to look up in walkforward_audit.csv
        (cci_divergence_intraday reuses the cci_divergence row/file, per spec).
    """
    row = load_wf_row(source_strategy)
    wf_trades = _f(row, "wf_trades")
    lam = wf_trades * WF_STOCK_SCALE * WF_DAY_SCALE

    card = {
        "strategy": card_name,
        "book": "incubator",
        "cadence": "intraday",
        "trades_per_month": {
            "lambda": round_sig(lam),
            "lambda_quality": "rough-extrapolation",
        },
        # win_rate intentionally omitted: walkforward_audit.csv carries no
        # win-rate column. Per spec, parity's P5 check skips itself when the
        # field is absent — this is not a missing-data failure, it's the
        # documented no-win-rate-yet contract for this cadence.
        "max_drawdown_pct": -15,
        "hold_days": {"p50": 0, "p95": 1},
        "slippage_assumed_pct": SLIPPAGE_ASSUMED_PCT,
        "generated": GENERATED,
        "source": (
            f"kite/reports/walkforward_audit.csv row '{source_strategy}' "
            f"wf_trades={wf_trades:g} (5-stock/5-day audit sample "
            f"extrapolated x{WF_STOCK_SCALE:g} stocks x{WF_DAY_SCALE:g} "
            "trading-days/month to the 47-stock live universe -- rough)"
        ),
        "code_hash": git_hash(STRATEGIES_DIR / f"{source_strategy}.py"),
    }
    return card


# ---------------------------------------------------------------------------
# main
# ---------------------------------------------------------------------------

CARD_BUILDERS = [
    ("momo_rotation_63", lambda: gen_card_momo()),
    ("rsi_trend_confirmation", lambda: gen_card_swing("rsi_trend_confirmation")),
    ("cci_divergence", lambda: gen_card_swing("cci_divergence")),
    ("choppiness_filter", lambda: gen_card_intraday("choppiness_filter", "choppiness_filter")),
    ("bb_mean_reversion", lambda: gen_card_intraday("bb_mean_reversion", "bb_mean_reversion")),
    ("adx_filter", lambda: gen_card_intraday("adx_filter", "adx_filter")),
    ("cci_divergence_intraday", lambda: gen_card_intraday("cci_divergence_intraday", "cci_divergence")),
]


def write_card(card: dict) -> Path:
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    path = OUT_DIR / f"{card['strategy']}.json"
    text = json.dumps(card, indent=2) + "\n"
    path.write_text(text, encoding="utf-8")
    return path


def main() -> int:
    generated = []
    for label, builder in CARD_BUILDERS:
        try:
            card = builder()
        except MissingStatsRow as e:
            print(f"FATAL: could not build card for {label!r}: {e}", file=sys.stderr)
            return 1
        path = write_card(card)
        print(f"--- {path.relative_to(REPO_ROOT)} ---")
        print(json.dumps(card, indent=2))
        generated.append(path)

    print(f"\n{len(generated)} expectation cards written to {OUT_DIR.relative_to(REPO_ROOT)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
