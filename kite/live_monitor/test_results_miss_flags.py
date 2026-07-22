"""
Offline smoke test for the results-miss gate extension to AnnouncementFilter
(docs/superpowers/specs/2026-07-22-results-miss-gate-design.md).

Plain assert + a main() runner -- no pytest dependency, no network. This file
never calls refresh()'s NSE fetch; it exercises flag_results_miss() /
is_flagged() / note_results_reaction() / pruning directly, with synthetic
as_of dates for the aging/expiry checks. Matches the house style of
test_parity_monitor.py / test_position_sizing.py.

Each scenario points AnnouncementFilter at an isolated temp JSON file (via
monkeypatching the module-level RESULTS_MISS_FLAGS_FILE constant) so this
test never reads or writes the real data/results_miss_flags.json.

Run standalone:
    python kite/live_monitor/test_results_miss_flags.py
"""
import sys
import tempfile
from datetime import datetime, timedelta
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from kite.live_monitor import announcement_filter as af

_ORIG_FLAGS_FILE = af.RESULTS_MISS_FLAGS_FILE


def fresh_filter(tmp_dir: Path) -> af.AnnouncementFilter:
    """AnnouncementFilter pointed at an isolated flags file for this scenario."""
    af.RESULTS_MISS_FLAGS_FILE = tmp_dir / 'results_miss_flags.json'
    return af.AnnouncementFilter()


def fail(msg):
    raise AssertionError(msg)


def require(cond, msg):
    if not cond:
        fail(msg)


# ---------------------------------------------------------------------------
# Scenario 1 -- flag_results_miss -> is_flagged, including while feed active
# ---------------------------------------------------------------------------
def scenario_flag_then_is_flagged():
    with tempfile.TemporaryDirectory() as td:
        f = fresh_filter(Path(td))
        f.active = True  # NSE feed "reachable" this cycle -- results-miss must still work
        require(f.is_flagged('RELIANCE') is None, "unflagged symbol must return None")
        f.flag_results_miss('RELIANCE')
        reason = f.is_flagged('RELIANCE')
        require(reason is not None and 'results-miss' in reason,
                f"expected a results-miss reason, got {reason!r}")
        return True, f"unflagged -> None; flagged -> {reason!r}"


# ---------------------------------------------------------------------------
# Scenario 2 -- results-miss flag blocks even when the NSE feed is inactive
# (unlike red flags, which are fail-open / gated on self.active)
# ---------------------------------------------------------------------------
def scenario_is_flagged_independent_of_active():
    with tempfile.TemporaryDirectory() as td:
        f = fresh_filter(Path(td))
        f.active = False
        f.flag_results_miss('TCS')
        reason = f.is_flagged('TCS')
        require(reason is not None, "results-miss flag must block even with active=False")
        return True, f"active=False, results-miss flag still returns: {reason!r}"


# ---------------------------------------------------------------------------
# Scenario 3 -- note_results_reaction only flags below the -2% threshold
# ---------------------------------------------------------------------------
def scenario_note_results_reaction_threshold():
    with tempfile.TemporaryDirectory() as td:
        f = fresh_filter(Path(td))
        f.note_results_reaction('INFY', -0.01)  # -1%, above threshold -> no flag
        require(f.is_flagged('INFY') is None, "reaction above -2% must not flag")
        f.note_results_reaction('INFY', -0.03)  # -3%, breaches -2% -> flag
        require(f.is_flagged('INFY') is not None, "reaction below -2% must flag")
        return True, "-1% no-op, -3% flags"


# ---------------------------------------------------------------------------
# Scenario 4 -- synthetic-date aging: a 10-day-old flag still blocks, a
# 29-day-old flag (past the 28-day TTL) has aged out via is_flagged, and an
# explicit prune removes it from the in-memory dict / JSON file.
# ---------------------------------------------------------------------------
def scenario_age_gating_and_prune():
    with tempfile.TemporaryDirectory() as td:
        f = fresh_filter(Path(td))
        now = datetime.now()
        recent = now - timedelta(days=10)  # inside the 28-day TTL
        stale = now - timedelta(days=29)   # just past the 28-day TTL

        f.flag_results_miss('SYMA', as_of=recent)
        f.flag_results_miss('SYMB', as_of=stale)

        require(f.is_flagged('SYMA') is not None, "10-day-old flag should still block")
        require(f.is_flagged('SYMB') is None, "29-day-old flag should have aged out")

        # is_flagged ages SYMB off logically but does not remove it from the
        # dict -- that is _prune_expired_results_miss_flags()'s job, called
        # for real at the top of every refresh().
        require('SYMB' in f.results_miss_flags, "stale flag should still be in-memory pre-prune")
        f._prune_expired_results_miss_flags()
        require('SYMB' not in f.results_miss_flags, "prune must remove the expired SYMB flag")
        require('SYMA' in f.results_miss_flags, "prune must keep the still-valid SYMA flag")

        persisted = af.json.loads(af.RESULTS_MISS_FLAGS_FILE.read_text())
        require('SYMB' not in persisted, "prune must also rewrite the JSON file without SYMB")
        return True, "10d flag survives is_flagged; 29d flag ages out and prune removes it (dict + JSON)"


# ---------------------------------------------------------------------------
# Scenario 5 -- persistence across a simulated monitor restart: a fresh
# AnnouncementFilter instance pointed at the same JSON file picks up the flag.
# ---------------------------------------------------------------------------
def scenario_persistence_across_restart():
    with tempfile.TemporaryDirectory() as td:
        tmp_dir = Path(td)
        f1 = fresh_filter(tmp_dir)
        f1.flag_results_miss('WIPRO')
        require((tmp_dir / 'results_miss_flags.json').exists(), "flags file should be written")

        f2 = fresh_filter(tmp_dir)  # brand-new instance, same file path -- simulates process restart
        reason = f2.is_flagged('WIPRO')
        require(reason is not None, "a fresh instance must load the persisted flag from disk")
        return True, f"fresh instance loaded persisted flag: {reason!r}"


# ---------------------------------------------------------------------------
# Scenario 6 -- re-flagging the same symbol on the same day is idempotent
# ---------------------------------------------------------------------------
def scenario_idempotent_same_day_reflag():
    with tempfile.TemporaryDirectory() as td:
        f = fresh_filter(Path(td))
        f.flag_results_miss('HDFCBANK')
        f.flag_results_miss('HDFCBANK')  # same symbol, same day -> no-op
        require(len(f.results_miss_flags) == 1, "re-flagging same symbol/day should not duplicate")
        return True, "second same-day flag_results_miss call is a no-op"


# ---------------------------------------------------------------------------
# Scenario 7 -- results-family desc substring match (the taxonomy-drift
# approximation documented in the spec's risk section): must catch the
# frozen category and plausible successor labels, must NOT catch the broad
# 'Outcome of Board Meeting' category or unrelated red-flag categories.
# ---------------------------------------------------------------------------
def scenario_results_family_substring_match():
    def matches(desc):
        d = desc.lower()
        return any(sub in d for sub in af.RESULTS_FAMILY_SUBSTRINGS)

    require(matches('Financial Result Updates'),
            "'Financial Result Updates' (frozen category, singular Result) must match")
    require(matches('Clarification - Financial Results'),
            "plausible successor label ('...Financial Results') must match")
    require(matches('Quarterly Results announcement'),
            "generic 'Results' must match")
    require(not matches('Outcome of Board Meeting'),
            "'Outcome of Board Meeting' alone must NOT match (too broad per spec)")
    require(not matches('Change in Director(s)'),
            "unrelated red-flag category must not match results-family")
    return True, "matches Financial Result/Results variants; excludes Board Meeting/Director categories"


# ---------------------------------------------------------------------------
# main
# ---------------------------------------------------------------------------
SCENARIOS = [
    ('1 FLAG -> IS_FLAGGED', scenario_flag_then_is_flagged),
    ('2 INDEPENDENT OF ACTIVE', scenario_is_flagged_independent_of_active),
    ('3 NOTE_REACTION THRESHOLD', scenario_note_results_reaction_threshold),
    ('4 AGE GATING + PRUNE', scenario_age_gating_and_prune),
    ('5 PERSIST ACROSS RESTART', scenario_persistence_across_restart),
    ('6 IDEMPOTENT SAME-DAY', scenario_idempotent_same_day_reflag),
    ('7 DESC SUBSTRING MATCH', scenario_results_family_substring_match),
]


def main():
    rows = []
    for name, fn in SCENARIOS:
        try:
            passed, detail = fn()
            rows.append((name, 'PASS', detail))
        except AssertionError as e:
            rows.append((name, 'FAIL', str(e)))
        except Exception as e:
            rows.append((name, 'ERROR', f"{type(e).__name__}: {e}"))
        finally:
            af.RESULTS_MISS_FLAGS_FILE = _ORIG_FLAGS_FILE  # never leave the real path monkeypatched

    print()
    print("=" * 100)
    print(f"{'SCENARIO':<28} {'RESULT':<8} DETAIL")
    print("-" * 100)
    for name, status, detail in rows:
        detail_1line = detail.replace('\n', ' | ')
        if len(detail_1line) > 140:
            detail_1line = detail_1line[:137] + '...'
        print(f"{name:<28} {status:<8} {detail_1line}")
    print("=" * 100)

    n_fail = sum(1 for _, s, _ in rows if s != 'PASS')
    print(f"\n{len(rows) - n_fail}/{len(rows)} scenarios passed.")
    return 1 if n_fail else 0


if __name__ == '__main__':
    sys.exit(main())
