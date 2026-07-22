"""Red-flag announcement filter — the one deployable finding of the July 2026
news/event study (docs/superpowers/specs/2026-07-21-news-event-alpha-design.md).

Four NSE announcement categories showed era-consistent negative 5-day drift
(FDR-surviving, cost-adjusted). This filter blocks NEW entries in stocks with a
red-flag announcement in the last 5 trading days and raises alerts for held
positions. It never auto-exits (exit-on-flag was not measured historically).

Fail-open by design: if the NSE feed is unreachable (bot protection may block
datacenter IPs), the filter deactivates for the day and says so — an unfiltered
trade is acceptable, a crashed monitor is not.

Results-miss extension (docs/superpowers/specs/2026-07-22-results-miss-gate-design.md):
in-sample study (kite/research/results_miss_filter_study.txt) found that stocks
whose results-day reaction was < -2% vs the NIFTY EW same-day move kept
drifting down for ~20 more trading days, 77% additive to the four red-flag
categories above. This filter now also collects candidate results-family
announcements during refresh() (`results_announcements`); the live monitor
(monitor.py:check_results_reactions, which HAS price data) computes the actual
reaction and calls flag_results_miss()/note_results_reaction() here to persist
the flag. Flags live in data/results_miss_flags.json so they survive restarts
and are independent of whether today's NSE feed fetch succeeds.
"""
import json
import logging
from datetime import datetime, timedelta
from pathlib import Path
from typing import Dict, List, Optional, Set, Tuple

import requests

logger = logging.getLogger(__name__)

RED_FLAGS = {
    'Change in Director(s)',
    'Disclosure under SEBI Takeover Regulations',
    'Spurt in Volume',
    'Statement of deviation(s) or variation(s) under Reg. 32',
}
LOOKBACK_CALENDAR_DAYS = 7  # ~5 trading days

# --- Results-miss gate constants (see spec doc in module docstring) --------
# Approximation, frozen: 'Financial Result Updates' (the exact category the
# in-sample study measured) vanished from NSE's desc taxonomy after 2025-Q1
# (per kite/research/pead_conditioned.py). Matching only the literal string
# would silently stop firing on current data. 'Outcome of Board Meeting' is
# too broad (mixed-content category) to use as a blanket substitute. Instead:
# match desc containing 'financial result' OR 'results', case-insensitive.
RESULTS_FAMILY_SUBSTRINGS = ('financial result', 'results')
RESULTS_RECENT_CALENDAR_DAYS = 4  # ~2 trading days (same 1.4x convention as LOOKBACK_CALENDAR_DAYS)
RESULTS_MISS_THRESHOLD = -0.02  # R < -2% vs NIFTY EW same-day return
RESULTS_MISS_FLAG_TTL_DAYS = 28  # ~20 trading days, approximated as calendar days (documented)
RESULTS_MISS_FLAGS_FILE = Path(__file__).resolve().parents[2] / 'data' / 'results_miss_flags.json'

_HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; rv:109.0) Gecko/20100101 Firefox/118.0",
    "Accept": "*/*",
    "Accept-Language": "en-US,en;q=0.5",
    "Accept-Encoding": "gzip, deflate",
    "Referer": "https://www.nseindia.com/companies-listing/corporate-filings-announcements",
}


def _parse_an_dt(date_str: str) -> Optional[datetime]:
    """Best-effort parse of the NSE 'dd-Mon-yyyy' an_dt prefix; None on any
    failure (caller treats None as "keep it", fail-soft)."""
    try:
        return datetime.strptime(date_str.strip(), '%d-%b-%Y')
    except (ValueError, AttributeError):
        return None


class AnnouncementFilter:
    def __init__(self):
        self.flags: Dict[str, List[Tuple[str, str]]] = {}  # symbol -> [(date, category)]
        self.results_announcements: Dict[str, List[Tuple[str, str]]] = {}  # symbol -> [(date, desc)]
        self.results_miss_flags: Dict[str, str] = self._load_results_miss_flags()  # symbol -> ISO flag date
        self.active = False
        self.last_refresh: Optional[datetime] = None
        self.match_count_today = 0

    def refresh(self) -> bool:
        """Fetch last ~7 days of announcements, keep red-flag ones. True on success.

        Also collects results-family announcements (see module docstring) into
        `results_announcements` for the live monitor's check_results_reactions()
        to consume. Expired results-miss flags are pruned on every call,
        regardless of whether the network fetch below succeeds.
        """
        self._prune_expired_results_miss_flags()
        try:
            s = requests.Session()
            s.headers.update(_HEADERS)
            r = s.get("https://www.nseindia.com/option-chain", timeout=15)
            r.raise_for_status()
            to_d = datetime.now()
            from_d = to_d - timedelta(days=LOOKBACK_CALENDAR_DAYS)
            r = s.get("https://www.nseindia.com/api/corporate-announcements",
                      params={"index": "equities",
                              "from_date": from_d.strftime("%d-%m-%Y"),
                              "to_date": to_d.strftime("%d-%m-%Y")},
                      timeout=30)
            r.raise_for_status()
            records = r.json()
            flags: Dict[str, List[Tuple[str, str]]] = {}
            results_announcements: Dict[str, List[Tuple[str, str]]] = {}
            results_cutoff = to_d - timedelta(days=RESULTS_RECENT_CALENDAR_DAYS)
            for rec in records:
                desc = rec.get('desc', '')
                sym = rec.get('symbol', '')
                an_dt_str = str(rec.get('an_dt', ''))[:11].strip()
                if desc in RED_FLAGS and sym:
                    flags.setdefault(sym, []).append((an_dt_str, desc))
                desc_lower = desc.lower()
                if sym and any(sub in desc_lower for sub in RESULTS_FAMILY_SUBSTRINGS):
                    an_dt = _parse_an_dt(an_dt_str)
                    # Fail-soft: an unparseable date is kept rather than dropped
                    # (better to over-include a candidate than silently miss it).
                    if an_dt is None or an_dt >= results_cutoff:
                        results_announcements.setdefault(sym, []).append((an_dt_str, desc))
            self.flags = flags
            self.results_announcements = results_announcements
            self.active = True
            self.last_refresh = datetime.now()
            self.match_count_today = 0
            logger.info(f"AnnouncementFilter: {len(records)} announcements scanned, "
                        f"{len(flags)} symbols red-flagged, "
                        f"{len(results_announcements)} symbols with recent results-family announcements")
            return True
        except Exception as e:
            self.active = False
            logger.warning(f"AnnouncementFilter refresh failed (fail-open, filter inactive): {e}")
            return False

    def is_flagged(self, symbol: str) -> Optional[str]:
        """Reason string if symbol has a recent red flag or results-miss flag,
        else None. Red flag requires the live NSE feed to be active this cycle
        (fail-open, existing behavior); the results-miss flag is independent of
        that feed — it was derived from price data and persisted to disk, so it
        still blocks even on a day the announcement feed can't be reached.
        """
        if self.active:
            hits = self.flags.get(symbol)
            if hits:
                self.match_count_today += 1
                date, cat = hits[-1]
                return f"{cat} ({date.strip()})"
        reason = self._check_results_miss(symbol)
        if reason:
            self.match_count_today += 1
            return reason
        return None

    # -- Results-miss gate -----------------------------------------------

    def note_results_reaction(self, symbol: str, reaction: float) -> None:
        """Convenience entry point: given a computed results-day reaction
        (stock same-day return minus NIFTY EW same-day return), flags `symbol`
        via flag_results_miss() if reaction breaches RESULTS_MISS_THRESHOLD.
        monitor.py's check_results_reactions() currently applies the threshold
        itself (it needs the raw numbers for logging) and calls
        flag_results_miss() directly; this wrapper is for callers that only
        have the reaction number (tests, future call sites).
        """
        if reaction < RESULTS_MISS_THRESHOLD:
            self.flag_results_miss(symbol)

    def flag_results_miss(self, symbol: str, as_of: Optional[datetime] = None) -> None:
        """Persist a results-miss flag for `symbol`: blocks NEW entries for
        ~20 trading days (RESULTS_MISS_FLAG_TTL_DAYS; see is_flagged). Idempotent
        within a day — re-flagging the same symbol on the same day is a no-op.
        """
        date_str = (as_of or datetime.now()).strftime('%Y-%m-%d')
        if self.results_miss_flags.get(symbol) == date_str:
            return
        self.results_miss_flags[symbol] = date_str
        self._save_results_miss_flags()
        logger.info(f"AnnouncementFilter: results-miss flag set for {symbol} ({date_str}, "
                    f"expires in ~{RESULTS_MISS_FLAG_TTL_DAYS}d)")

    def _check_results_miss(self, symbol: str) -> Optional[str]:
        date_str = self.results_miss_flags.get(symbol)
        if not date_str:
            return None
        try:
            flagged_dt = datetime.strptime(date_str, '%Y-%m-%d')
        except ValueError:
            return None
        age_days = (datetime.now() - flagged_dt).days
        if age_days < 0 or age_days >= RESULTS_MISS_FLAG_TTL_DAYS:
            return None
        return f"results-miss ({date_str}, {age_days}d ago, ~20td gate)"

    def _prune_expired_results_miss_flags(self) -> None:
        """Drop results-miss flags older than RESULTS_MISS_FLAG_TTL_DAYS. Called
        at the top of every refresh() so stale JSON state never silently
        outlives its gate."""
        now = datetime.now()
        kept: Dict[str, str] = {}
        expired = []
        for sym, date_str in self.results_miss_flags.items():
            try:
                flagged_dt = datetime.strptime(date_str, '%Y-%m-%d')
            except ValueError:
                expired.append(sym)
                continue
            if 0 <= (now - flagged_dt).days < RESULTS_MISS_FLAG_TTL_DAYS:
                kept[sym] = date_str
            else:
                expired.append(sym)
        if expired:
            logger.info(f"AnnouncementFilter: pruned {len(expired)} expired results-miss "
                        f"flag(s): {sorted(expired)}")
            self.results_miss_flags = kept
            self._save_results_miss_flags()

    def _load_results_miss_flags(self) -> Dict[str, str]:
        """Fail-soft load of persisted results-miss flags; missing/corrupt file -> {}."""
        try:
            if RESULTS_MISS_FLAGS_FILE.exists():
                data = json.loads(RESULTS_MISS_FLAGS_FILE.read_text())
                if isinstance(data, dict):
                    return {str(k): str(v) for k, v in data.items()}
        except (OSError, ValueError) as e:
            logger.warning(f"Could not read {RESULTS_MISS_FLAGS_FILE.name}: {e} — "
                           f"starting with no results-miss flags")
        return {}

    def _save_results_miss_flags(self) -> None:
        """Fail-soft persist; a write failure loses durability, not the in-memory flag."""
        try:
            RESULTS_MISS_FLAGS_FILE.parent.mkdir(parents=True, exist_ok=True)
            RESULTS_MISS_FLAGS_FILE.write_text(
                json.dumps(self.results_miss_flags, indent=2, sort_keys=True))
        except OSError as e:
            logger.warning(f"Could not persist {RESULTS_MISS_FLAGS_FILE.name}: {e}")

    def check_holdings(self, symbols: List[str]) -> List[Tuple[str, str]]:
        """(symbol, reason) for held positions with fresh flags — alert, don't act."""
        out = []
        if not self.active:
            return out
        for sym in symbols:
            hits = self.flags.get(sym)
            if hits:
                date, cat = hits[-1]
                out.append((sym, f"{cat} ({date.strip()})"))
        return out

    def status_line(self) -> str:
        rm = f", {len(self.results_miss_flags)} results-miss flag(s)" if self.results_miss_flags else ""
        if not self.active:
            return f"ann-filter: INACTIVE (feed unreachable, fail-open){rm}"
        return (f"ann-filter: active, {len(self.flags)} symbols flagged, "
                f"refreshed {self.last_refresh:%H:%M}{rm}")
