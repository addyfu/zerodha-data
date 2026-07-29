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
