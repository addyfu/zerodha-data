"""Ticker-mention extraction over the r/IndianStreetBets archive -- PHASE 0.

WHAT THIS IS
------------
Pure data engineering + corpus statistics for a future pre-registered study.
This script reads the Reddit archive (submissions + comments) and the NSE
symbol universe (names only, from a bhavcopy file listing), and produces a
per-symbol-per-IST-day MENTION PANEL: how many posts/comments touched each
stock, on each day. It is NOT a signal, NOT a backtest, and emits no
buy/sell/edge verdict of any kind.

HARD RULE ENFORCED IN CODE
---------------------------
No price or return data is ever loaded. The only thing read from
data/bhavcopy_full/ is the SYMBOL column of ONE recent file (see
find_latest_bhavcopy() below) -- a name list, not a price series. No OHLCV
column is ever parsed out of that file. Grep this file for 'CLOSE_PRICE' /
'OPEN_PRICE' / etc. and you will not find them used anywhere.

INPUTS
------
- data/reddit/indianstreetbets_submissions.ndjson (title, selftext,
  created_utc, score, id, author)
- data/reddit/indianstreetbets_comments.ndjson (body, created_utc, score,
  id, author)
- data/bhavcopy_full/*.csv -- the single most-recent file by filename date
  is used to build the "core universe" (SERIES == 'EQ' symbols).
- kite/research/reddit_ticker_aliases.csv -- reviewed alias -> symbol table.
- kite/research/reddit_ticker_stoplist.csv -- reviewed symbols excluded from
  bare-token matching.

EXTRACTION RULES (deterministic -- read this before changing anything)
------------------------------------------------------------------------
A "document" is one submission (title + selftext, joined) or one comment
(body). At most ONE mention is counted per symbol per document, regardless
of how many times or via how many mechanisms that symbol's name appears in
it -- a mention means "this document touched this stock", not a token count.

Five independent matching mechanisms feed the same per-document symbol set:

1. BARE TOKEN, case-sensitive ALL-CAPS (all symbols in the core universe
   minus the stoplist, any length):
   The document is tokenized on non-alphanumeric boundaries (a token must
   contain at least one letter; pure numbers are skipped). A token matches
   if it is written ENTIRELY IN UPPERCASE and is exactly equal to a
   non-stoplisted core-universe symbol. "bought TATAMOTORS today" matches;
   "bought Tatamotors today" does not (fails the all-caps test).

2. BARE TOKEN, case-insensitive, LONG SYMBOLS ONLY (core universe minus
   stoplist, len(symbol) >= 6):
   Same tokenizer. A token matches if token.upper() equals a non-stoplisted
   symbol that is 6 characters or longer. This lets "tatamotors" (lowercase)
   match, because at 10 characters the odds of an accidental English-word
   collision are judged negligible. Symbols shorter than 6 characters (SBIN,
   ITC, TCS, ...) do NOT get this treatment -- lowercase "sbin" or "itc"
   never bare-token-matches; those rely on the alias table if they need
   lowercase recall (see reddit_ticker_aliases.csv's [SHORT] rows).

3. STOPLISTED SYMBOLS get NEITHER of the above. A symbol on
   reddit_ticker_stoplist.csv can ONLY be counted via mechanism 4 or 5
   below (alias phrase, or an explicit cashtag / NSE: form). This is by
   design -- see the stoplist file's header for why (IDEA, SAIL, BSE, ...
   are common English words / generic abbreviations that would otherwise
   flood the panel with false positives).

4. CASHTAG and NSE: PREFIX forms, checked against EVERY known symbol
   (core universe UNION every symbol value appearing in the alias table,
   i.e. including stoplisted and "legacy" symbols) -- these prefixes are
   treated as fully self-disambiguating regardless of collision risk
   elsewhere, since nobody writes "$idea" or "NSE:SAIL" to mean the common
   word. Case-insensitive on the symbol part. Patterns: `$SYMBOL` (e.g.
   "$TATAMOTORS") and `NSE:SYMBOL` (e.g. "NSE:TATAMOTORS", "NSE: SAIL").
   Symbols containing '&' or '-' (M&M, BAJAJ-AUTO, NAM-INDIA, ARE&M) are
   NOT reachable through this path (the capture pattern is alphanumeric
   only) -- a known, documented gap; those four ride entirely on aliases.

5. ALIAS PHRASES (kite/research/reddit_ticker_aliases.csv): whole-phrase,
   case-insensitive matches, using a lookaround boundary (not a bare \\b)
   so multi-word phrases and phrases containing '&' or '-' both work
   correctly. This is the ONLY path for stoplisted symbols, for the three
   "[LEGACY]" tickers not in the current bhavcopy snapshot (TATAMOTORS,
   LTIM, SPICEJET -- see that file's header), and for the four special-
   character symbols. Every row in that file is a human-reviewed judgment
   call with a documented rationale/risk note; there is no fuzzy matching
   anywhere else in this pipeline.

DATE: created_utc (unix seconds, UTC) is converted to an IST (UTC+5:30)
calendar date via a fixed offset -- IST has no DST, so this is exact for
every timestamp in the archive with no timezone-database dependency.

OUTPUT SCHEMA (data/reddit/mentions_panel.csv)
------------------------------------------------
symbol, date, n_post_mentions, n_comment_mentions, n_total, n_unique_authors
One row per (symbol, date) with n_total >= 1 (sparse; no zero-filled rows).
n_unique_authors counts distinct non-null, non-"[deleted]" author strings
seen mentioning that symbol on that date, across posts and comments combined.

USAGE
-----
Self-check (per the task's own instruction -- run this FIRST and eyeball the
precision sample before trusting a full run):
    python kite/research/build_reddit_mentions.py --sample 50000 \\
        --out-panel data/reddit/mentions_panel_smoke.csv \\
        --out-stats kite/research/reddit_mentions_stats_smoke.txt

Full corpus:
    python kite/research/build_reddit_mentions.py

No network access, no price data, no signal evaluation. Safe to re-run.
"""
from __future__ import annotations

import argparse
import csv
import random
import re
import sys
import time
from collections import Counter, defaultdict
from datetime import datetime, timedelta, timezone
from pathlib import Path

try:
    import orjson as _json_backend

    def _loads(line: bytes):
        return _json_backend.loads(line)

    _READ_MODE = "rb"
except ImportError:  # pragma: no cover - fallback path
    import json as _json_backend

    def _loads(line):
        return _json_backend.loads(line)

    _READ_MODE = "r"

REPO_ROOT = Path(__file__).resolve().parents[2]
IST = timezone(timedelta(hours=5, minutes=30))

DEFAULT_SUBMISSIONS = REPO_ROOT / "data" / "reddit" / "indianstreetbets_submissions.ndjson"
DEFAULT_COMMENTS = REPO_ROOT / "data" / "reddit" / "indianstreetbets_comments.ndjson"
DEFAULT_BHAVCOPY_DIR = REPO_ROOT / "data" / "bhavcopy_full"
DEFAULT_ALIASES = Path(__file__).resolve().parent / "reddit_ticker_aliases.csv"
DEFAULT_STOPLIST = Path(__file__).resolve().parent / "reddit_ticker_stoplist.csv"
DEFAULT_PANEL_OUT = REPO_ROOT / "data" / "reddit" / "mentions_panel.csv"
DEFAULT_STATS_OUT = Path(__file__).resolve().parent / "reddit_mentions_stats.txt"

BHAVCOPY_NAME_RE = re.compile(r"sec_bhavdata_full_(\d{2})(\d{2})(\d{4})\.csv$")
TOKEN_RE = re.compile(r"\b(?=\w*[A-Za-z])[A-Za-z0-9]+\b")
CASHTAG_RE = re.compile(r"\$([A-Za-z][A-Za-z0-9]{0,19})\b")
NSE_PREFIX_RE = re.compile(r"\bNSE\s*:\s*([A-Za-z][A-Za-z0-9]{0,19})\b", re.IGNORECASE)
DELETED_AUTHORS = {None, "", "[deleted]", "[removed]", "AutoModerator"}


# --------------------------------------------------------------------------
# Universe / alias / stoplist loading
# --------------------------------------------------------------------------
def find_latest_bhavcopy(bhavcopy_dir: Path) -> Path:
    """Pick the single most-recent sec_bhavdata_full_DDMMYYYY.csv on disk.

    This is the ONLY bhavcopy file read anywhere in this script, and only
    its SYMBOL/SERIES columns are used -- never any price/volume column.
    """
    best_path = None
    best_date = None
    for path in bhavcopy_dir.glob("sec_bhavdata_full_*.csv"):
        m = BHAVCOPY_NAME_RE.search(path.name)
        if not m:
            continue
        dd, mm, yyyy = m.groups()
        try:
            d = datetime(int(yyyy), int(mm), int(dd))
        except ValueError:
            continue
        if best_date is None or d > best_date:
            best_date = d
            best_path = path
    if best_path is None:
        raise FileNotFoundError(f"No sec_bhavdata_full_*.csv found under {bhavcopy_dir}")
    return best_path


def load_core_universe(bhavcopy_path: Path) -> set[str]:
    """SYMBOL names only (SERIES == 'EQ'), from the file's SYMBOL column.

    No price/volume/turnover field is read or stored here.
    """
    universe: set[str] = set()
    with open(bhavcopy_path, "r", encoding="utf-8", newline="") as f:
        reader = csv.reader(f)
        header = next(reader)
        header = [h.strip() for h in header]
        sym_idx = header.index("SYMBOL")
        series_idx = header.index("SERIES")
        for row in reader:
            if len(row) <= max(sym_idx, series_idx):
                continue
            symbol = row[sym_idx].strip()
            series = row[series_idx].strip()
            if series == "EQ" and symbol:
                universe.add(symbol)
    return universe


def load_stoplist(path: Path) -> set[str]:
    stop: set[str] = set()
    with open(path, "r", encoding="utf-8", newline="") as f:
        for line in f:
            if not line.strip() or line.lstrip().startswith("#"):
                continue
            if line.strip() == "symbol,why" or line.startswith("symbol,"):
                continue
            row = next(csv.reader([line]))
            if row and row[0].strip():
                stop.add(row[0].strip())
    return stop


def load_aliases(path: Path) -> dict[str, str]:
    """alias (lowercased) -> symbol. Every alias must be unique."""
    aliases: dict[str, str] = {}
    with open(path, "r", encoding="utf-8", newline="") as f:
        for line in f:
            if not line.strip() or line.lstrip().startswith("#"):
                continue
            if line.startswith("alias,symbol,"):
                continue
            row = next(csv.reader([line]))
            if len(row) < 2 or not row[0].strip():
                continue
            alias = row[0].strip().lower()
            symbol = row[1].strip()
            if alias in aliases and aliases[alias] != symbol:
                raise ValueError(
                    f"Alias '{alias}' maps to two different symbols: "
                    f"{aliases[alias]} vs {symbol}"
                )
            aliases[alias] = symbol
    return aliases


def compile_alias_regex(aliases: dict[str, str]) -> re.Pattern:
    # Longest-first so multi-word phrases don't get shadowed by a shorter
    # alias that happens to be a prefix of them.
    ordered = sorted(aliases.keys(), key=len, reverse=True)
    body = "|".join(re.escape(a) for a in ordered)
    # Lookaround boundary (not \b) so this behaves correctly for aliases
    # containing '&' or '-', where \b's word/non-word transition logic is
    # unreliable.
    pattern = r"(?<![A-Za-z0-9])(?:" + body + r")(?![A-Za-z0-9])"
    return re.compile(pattern, re.IGNORECASE)


# --------------------------------------------------------------------------
# Matching
# --------------------------------------------------------------------------
class Matcher:
    def __init__(
        self,
        core_universe: set[str],
        stoplist: set[str],
        aliases: dict[str, str],
    ):
        self.bare_eligible = core_universe - stoplist
        self.bare_eligible_long = {s for s in self.bare_eligible if len(s) >= 6}
        self.aliases = aliases
        self.alias_re = compile_alias_regex(aliases)
        self.all_known_symbols = set(core_universe) | set(aliases.values())

    def match(self, text: str) -> dict[str, tuple[str, int, int]]:
        """Return {symbol: (mechanism, match_start, match_end)}.

        One entry per symbol per document (first mechanism/position that
        found it wins -- good enough for the precision-sample snippet).
        """
        found: dict[str, tuple[str, int, int]] = {}

        for m in TOKEN_RE.finditer(text):
            tok = m.group(0)
            if tok in self.bare_eligible and tok.isupper():
                sym = tok
                mech = "bare_caps_short" if len(sym) < 6 else "bare_caps_long"
                found.setdefault(sym, (mech, m.start(), m.end()))
            else:
                up = tok.upper()
                if up in self.bare_eligible_long:
                    found.setdefault(up, ("bare_lower_long", m.start(), m.end()))

        for m in CASHTAG_RE.finditer(text):
            sym = m.group(1).upper()
            if sym in self.all_known_symbols:
                found.setdefault(sym, ("cashtag", m.start(), m.end()))

        for m in NSE_PREFIX_RE.finditer(text):
            sym = m.group(1).upper()
            if sym in self.all_known_symbols:
                found.setdefault(sym, ("nse_prefix", m.start(), m.end()))

        for m in self.alias_re.finditer(text):
            alias_text = m.group(0).lower()
            sym = self.aliases.get(alias_text)
            if sym is None:
                continue
            found.setdefault(sym, ("alias", m.start(), m.end()))

        return found


# --------------------------------------------------------------------------
# Streaming corpus scan
# --------------------------------------------------------------------------
def ist_date_str(created_utc) -> str | None:
    try:
        ts = float(created_utc)
    except (TypeError, ValueError):
        return None
    dt = datetime.fromtimestamp(ts, tz=IST)
    return dt.date().isoformat()


def clean_author(author) -> str | None:
    if author in DELETED_AUTHORS:
        return None
    return author


def snippet(text: str, start: int, end: int, pad: int = 60) -> str:
    lo = max(0, start - pad)
    hi = min(len(text), end + pad)
    s = text[lo:hi].replace("\n", " ").replace("\r", " ")
    s = re.sub(r"\s+", " ", s).strip()
    prefix = "..." if lo > 0 else ""
    suffix = "..." if hi < len(text) else ""
    return f"{prefix}{s}{suffix}"


class ReservoirSampler:
    """Fixed-capacity uniform reservoir sample, streaming-friendly."""

    def __init__(self, capacity: int, rng: random.Random):
        self.capacity = capacity
        self.rng = rng
        self.items: list = []
        self.seen = 0

    def offer(self, item):
        self.seen += 1
        if len(self.items) < self.capacity:
            self.items.append(item)
        else:
            j = self.rng.randint(0, self.seen - 1)
            if j < self.capacity:
                self.items[j] = item


def scan_corpus(
    submissions_path: Path,
    comments_path: Path,
    matcher: Matcher,
    sample_size: int | None,
    seed: int,
):
    rng = random.Random(seed)

    panel: dict[tuple[str, str], dict] = defaultdict(
        lambda: {"post": 0, "comment": 0, "authors": set()}
    )
    symbol_total_mentions: Counter = Counter()
    year_total_mentions: Counter = Counter()
    year_docs_scanned: Counter = Counter()

    docs_scanned = {"submissions": 0, "comments": 0}
    docs_with_match = {"submissions": 0, "comments": 0}

    sample_short_bare = ReservoirSampler(400, rng)
    sample_other = ReservoirSampler(400, rng)

    keep_prob = None
    if sample_size is not None:
        total_docs = 110_827 + 1_330_221  # known archive sizes (MANIFEST.md)
        keep_prob = min(1.0, sample_size / total_docs)

    def process_file(path: Path, kind: str, build_text, get_created, get_author):
        with open(path, _READ_MODE, encoding=None if _READ_MODE == "rb" else "utf-8") as f:
            for line in f:
                if not line or not line.strip():
                    continue
                if keep_prob is not None and rng.random() > keep_prob:
                    continue
                try:
                    obj = _loads(line)
                except Exception:
                    continue

                text = build_text(obj)
                created_utc = get_created(obj)
                date_str = ist_date_str(created_utc)
                if date_str is None:
                    continue
                year = date_str[:4]
                author = clean_author(get_author(obj))

                docs_scanned[kind] += 1
                year_docs_scanned[year] += 1

                matches = matcher.match(text)
                if matches:
                    docs_with_match[kind] += 1

                for sym, (mech, start, end) in matches.items():
                    key = (sym, date_str)
                    row = panel[key]
                    if kind == "submissions":
                        row["post"] += 1
                    else:
                        row["comment"] += 1
                    if author is not None:
                        row["authors"].add(author)
                    symbol_total_mentions[sym] += 1
                    year_total_mentions[year] += 1

                    snip = snippet(text, start, end)
                    item = (sym, mech, date_str, kind, snip)
                    if mech == "bare_caps_short":
                        sample_short_bare.offer(item)
                    else:
                        sample_other.offer(item)

    def submission_text(obj):
        title = obj.get("title") or ""
        selftext = obj.get("selftext") or ""
        return f"{title}\n\n{selftext}"

    def comment_text(obj):
        return obj.get("body") or ""

    t0 = time.time()
    process_file(
        submissions_path,
        "submissions",
        submission_text,
        lambda o: o.get("created_utc"),
        lambda o: o.get("author"),
    )
    t1 = time.time()
    process_file(
        comments_path,
        "comments",
        comment_text,
        lambda o: o.get("created_utc"),
        lambda o: o.get("author"),
    )
    t2 = time.time()

    timing = {
        "submissions_sec": t1 - t0,
        "comments_sec": t2 - t1,
        "total_sec": t2 - t0,
    }

    return {
        "panel": panel,
        "symbol_total_mentions": symbol_total_mentions,
        "year_total_mentions": year_total_mentions,
        "year_docs_scanned": year_docs_scanned,
        "docs_scanned": docs_scanned,
        "docs_with_match": docs_with_match,
        "sample_short_bare": sample_short_bare,
        "sample_other": sample_other,
        "timing": timing,
        "sample_size_requested": sample_size,
        "keep_prob": keep_prob,
    }


# --------------------------------------------------------------------------
# Output writers
# --------------------------------------------------------------------------
def write_panel_csv(panel: dict, out_path: Path) -> int:
    rows = []
    for (symbol, date_str), agg in panel.items():
        n_post = agg["post"]
        n_comment = agg["comment"]
        rows.append(
            (
                symbol,
                date_str,
                n_post,
                n_comment,
                n_post + n_comment,
                len(agg["authors"]),
            )
        )
    rows.sort(key=lambda r: (r[0], r[1]))

    out_path.parent.mkdir(parents=True, exist_ok=True)
    with open(out_path, "w", encoding="utf-8", newline="") as f:
        w = csv.writer(f)
        w.writerow(
            ["symbol", "date", "n_post_mentions", "n_comment_mentions", "n_total", "n_unique_authors"]
        )
        w.writerows(rows)
    return len(rows)


def pick_diverse_sample(reservoirs: list[tuple[ReservoirSampler, int]], rng: random.Random) -> list:
    """From a list of (reservoir, target_count), pick target_count items each,
    preferring distinct symbols first, falling back to repeats if the
    reservoir doesn't have enough distinct symbols."""
    chosen = []
    used_symbols = set()
    for reservoir, target in reservoirs:
        items = list(reservoir.items)
        rng.shuffle(items)
        picked = []
        leftovers = []
        for item in items:
            sym = item[0]
            if len(picked) >= target:
                break
            if sym not in used_symbols:
                picked.append(item)
                used_symbols.add(sym)
            else:
                leftovers.append(item)
        i = 0
        while len(picked) < target and i < len(leftovers):
            picked.append(leftovers[i])
            i += 1
        chosen.extend(picked)
    return chosen


def write_stats_report(
    result: dict,
    core_universe: set[str],
    stoplist: set[str],
    aliases: dict[str, str],
    out_path: Path,
    seed: int,
):
    panel = result["panel"]
    symbol_total_mentions = result["symbol_total_mentions"]
    year_total_mentions = result["year_total_mentions"]
    year_docs_scanned = result["year_docs_scanned"]
    docs_scanned = result["docs_scanned"]
    docs_with_match = result["docs_with_match"]
    timing = result["timing"]

    total_docs = docs_scanned["submissions"] + docs_scanned["comments"]
    total_with_match = docs_with_match["submissions"] + docs_with_match["comments"]

    # mention-days per symbol (distinct dates with n_total >= 1)
    mention_days_by_symbol: Counter = Counter()
    for (symbol, _date) in panel.keys():
        mention_days_by_symbol[symbol] += 1

    n_ge_100 = sum(1 for v in mention_days_by_symbol.values() if v >= 100)
    n_ge_500 = sum(1 for v in mention_days_by_symbol.values() if v >= 500)
    n_ge_2000 = sum(1 for v in mention_days_by_symbol.values() if v >= 2000)

    top30 = symbol_total_mentions.most_common(30)

    top10_spikes = sorted(
        ((sym, date, agg["post"] + agg["comment"]) for (sym, date), agg in panel.items()),
        key=lambda r: r[2],
        reverse=True,
    )[:10]

    rng = random.Random(seed + 1)
    precision_items = pick_diverse_sample(
        [
            (result["sample_short_bare"], 12),
            (result["sample_other"], 28),
        ],
        rng,
    )
    rng.shuffle(precision_items)

    lines = []
    lines.append("REDDIT TICKER-MENTION CORPUS STATS (PHASE 0 -- no price/signal content)")
    lines.append("=" * 78)
    lines.append(f"Generated: {datetime.now(tz=IST).isoformat()}")
    if result["sample_size_requested"] is not None:
        lines.append(
            f"SAMPLE RUN: requested ~{result['sample_size_requested']:,} docs "
            f"(keep_prob={result['keep_prob']:.5f}, applied independently to each "
            f"source file via random.random() < keep_prob -- NOT the first N lines, "
            f"to avoid biasing toward the earliest dates)."
        )
    else:
        lines.append("FULL CORPUS RUN.")
    lines.append("")

    lines.append("-- Universe / alias / stoplist sizes --")
    lines.append(f"Core universe (EQ symbols from latest bhavcopy file): {len(core_universe):,}")
    lines.append(f"Stoplist size: {len(stoplist)}")
    lines.append(f"Bare-token-eligible symbols (core - stoplist): {len(core_universe - stoplist):,}")
    lines.append(f"Alias table rows (unique aliases): {len(aliases)}")
    lines.append(f"Distinct target symbols covered by aliases: {len(set(aliases.values()))}")
    legacy = sorted(set(aliases.values()) - core_universe)
    lines.append(f"Alias-target symbols NOT in the core universe (legacy/renamed): {legacy}")
    lines.append("")

    lines.append("-- Corpus coverage --")
    lines.append(f"Submissions scanned: {docs_scanned['submissions']:,}")
    lines.append(f"Comments scanned:    {docs_scanned['comments']:,}")
    lines.append(f"Total docs scanned:  {total_docs:,}")
    lines.append(
        f"Submissions with >=1 ticker match: {docs_with_match['submissions']:,} "
        f"({100 * docs_with_match['submissions'] / max(1, docs_scanned['submissions']):.2f}%)"
    )
    lines.append(
        f"Comments with >=1 ticker match:    {docs_with_match['comments']:,} "
        f"({100 * docs_with_match['comments'] / max(1, docs_scanned['comments']):.2f}%)"
    )
    lines.append(
        f"TOTAL docs with >=1 ticker match:  {total_with_match:,} "
        f"({100 * total_with_match / max(1, total_docs):.2f}%)"
    )
    lines.append("")

    lines.append("-- Top 30 symbols by total mentions (posts + comments, 1 per doc) --")
    lines.append(f"{'rank':>4}  {'symbol':<12}  {'total_mentions':>15}  {'mention_days':>13}")
    for i, (sym, cnt) in enumerate(top30, 1):
        lines.append(f"{i:>4}  {sym:<12}  {cnt:>15,}  {mention_days_by_symbol.get(sym, 0):>13,}")
    lines.append("")

    lines.append("-- Per-year mention volumes (mention-events, not doc counts) --")
    for year in sorted(year_total_mentions.keys()):
        lines.append(
            f"{year}: {year_total_mentions[year]:>10,} mentions "
            f"across {year_docs_scanned[year]:>9,} docs scanned"
        )
    lines.append("")

    lines.append("-- Mention-day distribution across symbols --")
    lines.append(f"Symbols with >=1 mention at all:        {len(mention_days_by_symbol):,}")
    lines.append(f"Symbols with >=100 mention-days:         {n_ge_100:,}")
    lines.append(f"Symbols with >=500 mention-days:         {n_ge_500:,}")
    lines.append(f"Symbols with >=2000 mention-days:        {n_ge_2000:,}")
    lines.append(
        "(mention-day = a calendar day on which the symbol had >=1 mention; "
        "this is a corpus-coverage/breadth statistic, not a price statistic.)"
    )
    lines.append("")

    lines.append("-- Top 10 single-day mention spikes (symbol, date, count) -- NO PRICE CONTEXT --")
    for sym, date_str, cnt in top10_spikes:
        lines.append(f"{sym:<12}  {date_str}  {cnt:>8,} mentions")
    lines.append("")

    lines.append("-- Precision sample (40 random matched examples, reviewer audit) --")
    lines.append(
        f"Drawn via reservoir sampling (seed={seed}) from two pools: "
        f"'bare_caps_short' (symbol <6 chars, matched via the case-sensitive "
        f"ALL-CAPS bare-token rule -- the highest false-positive-risk "
        f"mechanism) and everything else (long lowercase bare-token, cashtag, "
        f"NSE: prefix, alias phrase). Target: >=10 from bare_caps_short."
    )
    n_short = sum(1 for it in precision_items if it[1] == "bare_caps_short")
    lines.append(f"Actual composition: {len(precision_items)} items, {n_short} from bare_caps_short.")
    lines.append("")
    lines.append(f"{'symbol':<12}  {'mechanism':<16}  {'date':<10}  {'kind':<11}  snippet")
    lines.append("-" * 78)
    for sym, mech, date_str, kind, snip in precision_items:
        lines.append(f"{sym:<12}  {mech:<16}  {date_str:<10}  {kind:<11}  {snip}")
    lines.append("")

    lines.append("-- Timing --")
    lines.append(f"Submissions pass: {timing['submissions_sec']:.1f}s")
    lines.append(f"Comments pass:    {timing['comments_sec']:.1f}s")
    lines.append(f"Total:            {timing['total_sec']:.1f}s")
    lines.append("")

    out_path.parent.mkdir(parents=True, exist_ok=True)
    with open(out_path, "w", encoding="utf-8") as f:
        f.write("\n".join(lines) + "\n")

    return {
        "total_docs": total_docs,
        "total_with_match": total_with_match,
        "top30": top30,
        "n_short_precision": n_short,
        "n_precision": len(precision_items),
    }


# --------------------------------------------------------------------------
# CLI
# --------------------------------------------------------------------------
def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--submissions", type=Path, default=DEFAULT_SUBMISSIONS)
    ap.add_argument("--comments", type=Path, default=DEFAULT_COMMENTS)
    ap.add_argument("--bhavcopy-dir", type=Path, default=DEFAULT_BHAVCOPY_DIR)
    ap.add_argument("--aliases", type=Path, default=DEFAULT_ALIASES)
    ap.add_argument("--stoplist", type=Path, default=DEFAULT_STOPLIST)
    ap.add_argument("--out-panel", type=Path, default=DEFAULT_PANEL_OUT)
    ap.add_argument("--out-stats", type=Path, default=DEFAULT_STATS_OUT)
    ap.add_argument(
        "--sample",
        type=int,
        default=None,
        help="If set, randomly sample ~N total docs across both files instead of the full corpus.",
    )
    ap.add_argument("--seed", type=int, default=20260729)
    args = ap.parse_args(argv)

    bhavcopy_path = find_latest_bhavcopy(args.bhavcopy_dir)
    print(f"[universe] using bhavcopy file: {bhavcopy_path.name}", file=sys.stderr)
    core_universe = load_core_universe(bhavcopy_path)
    print(f"[universe] EQ symbols: {len(core_universe):,}", file=sys.stderr)

    stoplist = load_stoplist(args.stoplist)
    aliases = load_aliases(args.aliases)
    print(f"[universe] stoplist: {len(stoplist)}  aliases: {len(aliases)}", file=sys.stderr)

    unknown_stoplist = stoplist - core_universe
    if unknown_stoplist:
        print(
            f"[warn] stoplist symbols not found in core universe (harmless, "
            f"just means they never had a bare-token effect anyway): {sorted(unknown_stoplist)}",
            file=sys.stderr,
        )

    matcher = Matcher(core_universe, stoplist, aliases)

    result = scan_corpus(
        args.submissions,
        args.comments,
        matcher,
        sample_size=args.sample,
        seed=args.seed,
    )

    n_rows = write_panel_csv(result["panel"], args.out_panel)
    print(f"[panel] wrote {n_rows:,} rows -> {args.out_panel}", file=sys.stderr)

    summary = write_stats_report(result, core_universe, stoplist, aliases, args.out_stats, args.seed)
    print(f"[stats] wrote report -> {args.out_stats}", file=sys.stderr)
    print(
        f"[stats] {summary['total_with_match']:,} / {summary['total_docs']:,} docs matched "
        f"({100 * summary['total_with_match'] / max(1, summary['total_docs']):.2f}%)",
        file=sys.stderr,
    )
    print(
        f"[stats] precision sample: {summary['n_precision']} items "
        f"({summary['n_short_precision']} bare_caps_short)",
        file=sys.stderr,
    )


if __name__ == "__main__":
    main()
