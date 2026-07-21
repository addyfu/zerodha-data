"""Red-flag announcement filter — the one deployable finding of the July 2026
news/event study (docs/superpowers/specs/2026-07-21-news-event-alpha-design.md).

Four NSE announcement categories showed era-consistent negative 5-day drift
(FDR-surviving, cost-adjusted). This filter blocks NEW entries in stocks with a
red-flag announcement in the last 5 trading days and raises alerts for held
positions. It never auto-exits (exit-on-flag was not measured historically).

Fail-open by design: if the NSE feed is unreachable (bot protection may block
datacenter IPs), the filter deactivates for the day and says so — an unfiltered
trade is acceptable, a crashed monitor is not.
"""
import logging
from datetime import datetime, timedelta
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

_HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; rv:109.0) Gecko/20100101 Firefox/118.0",
    "Accept": "*/*",
    "Accept-Language": "en-US,en;q=0.5",
    "Accept-Encoding": "gzip, deflate",
    "Referer": "https://www.nseindia.com/companies-listing/corporate-filings-announcements",
}


class AnnouncementFilter:
    def __init__(self):
        self.flags: Dict[str, List[Tuple[str, str]]] = {}  # symbol -> [(date, category)]
        self.active = False
        self.last_refresh: Optional[datetime] = None
        self.match_count_today = 0

    def refresh(self) -> bool:
        """Fetch last ~7 days of announcements, keep red-flag ones. True on success."""
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
            for rec in records:
                desc = rec.get('desc', '')
                if desc in RED_FLAGS:
                    sym = rec.get('symbol', '')
                    if sym:
                        flags.setdefault(sym, []).append(
                            (str(rec.get('an_dt', ''))[:11], desc))
            self.flags = flags
            self.active = True
            self.last_refresh = datetime.now()
            self.match_count_today = 0
            logger.info(f"AnnouncementFilter: {len(records)} announcements scanned, "
                        f"{len(flags)} symbols red-flagged")
            return True
        except Exception as e:
            self.active = False
            logger.warning(f"AnnouncementFilter refresh failed (fail-open, filter inactive): {e}")
            return False

    def is_flagged(self, symbol: str) -> Optional[str]:
        """Reason string if symbol has a recent red flag, else None. None when inactive."""
        if not self.active:
            return None
        hits = self.flags.get(symbol)
        if not hits:
            return None
        self.match_count_today += 1
        date, cat = hits[-1]
        return f"{cat} ({date.strip()})"

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
        if not self.active:
            return "ann-filter: INACTIVE (feed unreachable, fail-open)"
        return (f"ann-filter: active, {len(self.flags)} symbols flagged, "
                f"refreshed {self.last_refresh:%H:%M}")
