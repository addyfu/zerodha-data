# r/IndianStreetBets — Full Historical Archive

## Source
Pulled from the **Arctic Shift API** (`https://arctic-shift.photon-reddit.com/api`),
a Pushshift-lineage third-party Reddit archive maintained by ArthurHeitmann
(GitHub: `ArthurHeitmann/arctic_shift`). This is a community archive that
mirrors Reddit's own data (it is not scraped from reddit.com directly) and
is continuously updated from Reddit's firehose plus periodic backfills.

Route selection: verified three candidate routes at pull time (2026-07-29).
- **Arctic Shift API — used.** Live, documented, no auth required, returned
  data going back to the subreddit's creation and up through the current date.
- pullpush.io — not used. Public writeups as of 2026 describe it as
  volunteer-run with a much tighter rate limit (~1,000 req/hr) and recurring
  outages; Arctic Shift was strictly better for this pull (higher throughput,
  documented pagination, no auth).
- Academic Torrents (Watchful1 per-subreddit dumps / monthly Pushshift
  dumps) — not used. Arctic Shift's live API already gave complete,
  up-to-date, per-subreddit data via straightforward pagination, so the
  torrent route (bulkier, less current, requires a torrent client) wasn't
  needed.

Method: `GET /api/posts/search` and `GET /api/comments/search`, filtered to
`subreddit=IndianStreetBets`, paginated ascending by `created_utc` with
`limit=auto` (server picks ~600-900 items/request), field-limited via the
`fields` param to keep the archive well under the 2 GB size ceiling. Polite
pull: ~0.4s sleep between requests, honest `User-Agent` with contact email,
429 responses handled by waiting for `X-RateLimit-Reset`.

Date pulled: **2026-07-29**.

## Files

| File | Items | Size | Date range (created_utc, UTC) |
|---|---|---|---|
| `indianstreetbets_submissions.ndjson` | 110,827 posts | 75.2 MB (75,199,119 bytes) | 2020-02-13 → 2026-07-29 |
| `indianstreetbets_comments.ndjson` | 1,330,221 comments | 572.1 MB (572,147,543 bytes) | 2020-02-13 → 2026-07-29 |
| **Total** | **1,441,048 items** | **~647 MB** | |

Format: one JSON object per line (NDJSON), UTF-8. No wrapping array. Sorted
ascending by `created_utc` within each file.

Subreddit itself was created **2020-01-29** (`created_utc=1580298185`); first
post landed 2 weeks later on 2020-02-13. So this covers the subreddit's
entire lifetime through the pull date — there is no earlier data to miss.
As of the pull, the subreddit metadata (via `/api/subreddits/search`)
reported 457,891 subscribers.

## Fields available

Selected via the API's `fields` param (full field set on Arctic Shift is
much larger — this subset was chosen to keep size down while retaining
everything needed for text/sentiment/volume analysis; original Reddit ids,
timestamps, author, flair, text body, and score are all present).

**Submissions** (`indianstreetbets_submissions.ndjson`):
`id`, `author`, `author_flair_text`, `created_utc`, `retrieved_on`,
`subreddit`, `score`, `num_comments`, `over_18`, `spoiler`,
`link_flair_text`, `post_hint`, `selftext`, `title`, `url`, `distinguished`

**Comments** (`indianstreetbets_comments.ndjson`):
`id`, `author`, `author_flair_text`, `created_utc`, `retrieved_on`,
`subreddit`, `score`, `distinguished`, `body`, `link_id`, `parent_id`

Note: `permalink` is not a selectable field on this API; it can be
reconstructed as `https://reddit.com/r/IndianStreetBets/comments/<post_id>/`
for posts, and `.../<post_id>/_/<comment_id>/` for comments (via `link_id`
with the `t3_` prefix stripped).

## Verification performed

- **Counts**: 110,827 submissions, 1,330,221 comments — all `id` values
  unique within each file (no duplicates from pagination boundaries).
- **Date range**: both files span 2020-02-13 to 2026-07-29 (today), matching
  the subreddit's full lifetime.
- **Fields present**: 100% of records in both files have `score`; 100% of
  submissions have `selftext` (a key present, may be empty string for
  link/image posts); 100% of comments have `body`.
- **Content**: 67,901 / 110,827 posts (61%) have non-empty `selftext` (the
  rest are link/image/poll posts, or text posts later scrubbed). 1,291,856 /
  1,330,221 comments (97.1%) have a body that is not `[deleted]`/`[removed]`.
- **Yearly volume** (posts / comments), showing organic subreddit growth,
  no visible collection gaps:
  - 2020: 6,647 / 70,496
  - 2021: 16,845 / 155,259
  - 2022: 14,760 / 155,608
  - 2023: 14,377 / 168,711
  - 2024: 28,597 / 399,996
  - 2025: 18,228 / 228,971
  - 2026 (partial, through Jul 29): 11,373 / 151,180
- **Sample titles across years** (spot check):
  - 2020: "Traders ke laude lag gaye." (score 9)
  - 2022: "Stopping my SIPs worth 50k pm" (score 63, selftext 385 chars)
  - 2024: "Your thoughts on this guy." (score 0)
  - 2026: "VBL - avg price bought 533.. current price 384... checked after 6
    months, and I ..." (score 211 chars selftext)

## Caveats / known gaps

- **Deleted/removed content**: Reddit-side deletions/removals are preserved
  as-is by the archive — deleted comment/post text shows up as the literal
  string `[deleted]` (user-deleted) or `[removed]` (mod/AutoMod-removed) in
  `body`/`selftext`, same convention as original Pushshift dumps. ~2.9% of
  comments fall in this bucket; author field is similarly `[deleted]` for
  user-deleted content.
- **Score/num_comments freshness**: per Arctic Shift's own docs, `score` and
  `num_comments` reflect the value at time of archiving; items posted in the
  ~36 hours before the pull may show artificially low scores (archived near
  posting time, before votes accrued). This mainly affects the tail end of
  the 2026 data (last day or two).
- **No independent completeness guarantee**: Arctic Shift states "no uptime
  or performance guarantees" — it is a best-effort community mirror, not an
  official Reddit export. Coverage is generally excellent post-2020 (this is
  the same lineage as the original Pushshift project), but Reddit-side API
  hiccups on Arctic Shift's ingestion side could in principle cause silent
  micro-gaps. No such gaps were detected in the yearly counts above.
- One collection run was interrupted mid-pull by a background-process time
  limit on the collecting machine (not an API-side issue) after ~874k
  comments; the puller has resume logic (keyed off max `created_utc` already
  on disk) and picked up cleanly with zero duplicates or gaps — verified via
  the uniqueness check above.

---

# r/algotrading — Full Submissions + Top-2,000-Thread Comments

## Source
Same source and method as the r/IndianStreetBets pull above: **Arctic Shift
API** (`https://arctic-shift.photon-reddit.com/api`), no auth, honest
`User-Agent` with contact email, `X-RateLimit-Reset`-aware backoff.

Date pulled: **2026-07-29**.

Scope was deliberately narrower than a full firehose pull:
1. **All submissions**, subreddit creation → pull date (unbounded).
2. **Comments only for the top ~2,000 submissions by score**, fetched
   per-thread via `GET /api/comments/search?link_id=<post_id>` (verified at
   pull time: this endpoint accepts `link_id` with or without the `t3_`
   prefix and returns the full comment set for a thread in one page for
   every thread tested, including a 75-comment thread used as a control).

## Method detail

**Submissions**: `GET /api/posts/search`, `subreddit=algotrading`,
`sort=asc`, `limit=auto`, paginated ascending by `created_utc` with an
id-dedupe window at page boundaries (same logic as the ISB puller). Run as
**two parallel shards** by `created_utc` range to use the "at most 2
concurrent streams" allowance: shard A `2012-06-17 → 2021-01-01`, shard B
`2021-01-01 → present`. Shards were merged and deduped by `id` into the
single output file below (0 duplicate ids found across the shard boundary).

**Comments**: top ~2,000 submissions by `score` were selected *after* the
full submissions file was on disk (score-based sorting is not supported
server-side — confirmed via a 400 error probing `sort_type=score`, so
ranking was computed client-side from the downloaded data). Comments were
then fetched **per-thread** via the `link_id` filter, one request per thread
for the vast majority (comment count fit in a single `limit=auto` page);
a defensive pagination fallback (continue on `created_utc` if a response
looked capped) was included but not exercised by anything in this set — no
algotrading thread in the top-2,000 needed a second page.

Politeness: ~0.4-0.5s sleep between requests, up to 2 concurrent
request streams, shared backoff on 429/soft-throttle so both streams slow
down together. The API returned occasional soft-throttle responses
(HTTP 422, body `"Timeout. Maybe slow down a bit"`) rather than hard 429s —
handled identically to a 429 (short wait + shared slowdown signal). No hard
429s were seen during either the submissions or comments pull. Soft-throttle
count stayed low (roughly half a dozen total across the entire comments
pull, self-cleared each run); a single-stream drop-back was never triggered.

## Files

| File | Items | Size | Date range (created_utc, UTC) |
|---|---|---|---|
| `algotrading_submissions.ndjson` | 57,455 posts | 28.7 MB (28,702,978 bytes) | 2012-06-17 → 2026-07-29 |
| `algotrading_top_thread_comments.ndjson` | 133,347 comments | 58.2 MB (58,205,818 bytes) | 2016-10-28 → 2026-07-29 (comment timestamps; threads themselves span the full submissions range) |
| **Total** | **190,802 items** | **~87 MB** | |

Format: one JSON object per line (NDJSON), UTF-8. No wrapping array.
Submissions sorted ascending by `created_utc`. Comments are grouped by the
order threads were processed (not globally time-sorted) — filter/sort by
`created_utc` or `link_id` downstream as needed.

Subreddit itself was created **2012-06-17** (`created_utc=1339956808`) per
`/api/subreddits/search`; the submissions file covers its entire lifetime
through the pull date. As of the pull, `_meta.num_posts` reported by that
same endpoint was 56,975 (close to, and slightly below, the 57,455 actually
retrieved — archive metadata counters lag live pulls slightly, expected).

## Top-2,000 thread selection rule

1. Loaded all 57,455 rows from `algotrading_submissions.ndjson`.
2. Sorted descending by `score` (ties broken by original/insertion order —
   not by any secondary key).
3. Took the first 2,000 rows. Resulting score range in the selected set:
   **2,328 (highest) → 65 (2,000th)**.
4. Fetched comments for exactly those 2,000 `id` values via `link_id`.

One selected thread (`dccsxg`, score 111, "I've created a Python Tool to
download and validate historical OHLCV data from various Crypto Exchanges")
had `num_comments=0` in the archive and correctly yielded 0 comments — not a
fetch failure, verified by checking its stored `num_comments` field.
Otherwise 1,999 / 2,000 selected threads have ≥1 comment on disk.

## Fields available

**Submissions** (`algotrading_submissions.ndjson`) — narrower field set than
the ISB pull, per this pull's explicit scope:
`id`, `created_utc`, `title`, `selftext`, `score`, `num_comments`, `author`,
`link_flair_text`

**Comments** (`algotrading_top_thread_comments.ndjson`) — same field set as
the ISB comments pull, for consistency:
`id`, `author`, `author_flair_text`, `created_utc`, `retrieved_on`,
`subreddit`, `score`, `distinguished`, `body`, `link_id`, `parent_id`

## Verification performed

- **Counts**: 57,455 submissions (0 duplicate `id`s after merging the two
  date-range shards), 133,347 comments (0 duplicate `id`s).
- **Date range**: submissions span 2012-06-17 → 2026-07-29 (today), i.e. the
  subreddit's entire lifetime. Comments (necessarily a subset in time, since
  only high-score threads were targeted) span 2016-10-28 → 2026-07-29.
- **Thread coverage**: 1,999 / 2,000 top-scored threads have ≥1 comment
  fetched; the one exception genuinely has 0 comments per its own metadata.
- **Content**: 49,470 / 57,455 submissions (86.1%) have non-empty
  `selftext`. 116,193 / 133,347 comments (87.1%) have a `body` that is not
  empty/`[deleted]`/`[removed]`.
- **Yearly submission volume** (no visible collection gaps):
  2012: 156 · 2013: 182 · 2014: 226 · 2015: 545 · 2016: 733 · 2017: 1,604 ·
  2018: 2,541 · 2019: 3,649 · 2020: 7,131 · 2021: 11,037 · 2022: 7,221 ·
  2023: 6,593 · 2024: 6,831 · 2025: 4,949 · 2026 (partial, through Jul 29):
  4,057.
- **Sample titles across years** (highest-score post per year, spot check):
  - 2012: "Interesting papers for you guys." (score 33)
  - 2019: "I've reproduced 130+ research papers about 'predicting the stock
    market'..." (score 1,733)
  - 2021: "NEW RULE: Anyone found pumping stocks or bringing attention to
    individ[ual tickers]..." (score 2,328 — the all-time top score in this
    dataset)
  - 2025: "I found a statistical arbitrage with ~1% return / day" (score
    1,180)
  - 2026: "I pitted 5 AIs against France's Top Traders (Live on stage)."
    (score 586)
- **Yearly comment volume** (by comment `created_utc`, reflecting when top
  threads accumulated replies, not when they were posted): 2016: 41 ·
  2017: 127 · 2018: 2,218 · 2019: 8,352 · 2020: 23,461 · 2021: 35,786 ·
  2022: 17,220 · 2023: 7,622 · 2024: 8,710 · 2025: 16,804 · 2026: 13,006.

## Caveats / known gaps

- **Not a full comment archive**: unlike the ISB pull, comments here are
  intentionally limited to the top ~2,000 submissions by score (out of
  57,455 total posts) — this file cannot be used for subreddit-wide comment
  volume/sentiment analysis, only for deep-dives on the highest-engagement
  threads.
- **Score is a snapshot**: as with the ISB pull, `score`/`num_comments`
  reflect archive-time values; posts from the last ~36 hours before the pull
  may be under-scored and could be under-represented in the top-2,000 set
  purely due to not having accumulated votes yet.
- **Deleted/removed content**: same convention as the ISB pull — `body`/
  `selftext` show literal `[deleted]`/`[removed]` strings where applicable.
- **Comment ordering**: comments file is not globally sorted by
  `created_utc` (it's grouped by processing order across threads); sort
  downstream if a strict chronological read is needed.
- Two background-shard-watcher processes were used transiently during the
  submissions pull and both completed and wrote `DONE` before being merged;
  the entire comments pull (all 4 batches) was run as bounded foreground
  calls with on-disk resume (by scanning already-written `link_id`s), per a
  mid-task instruction to avoid backgrounding for this phase.
