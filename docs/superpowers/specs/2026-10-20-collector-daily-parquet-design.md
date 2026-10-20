# GitHub Collector: Daily Parquet History + Rolling DB — Design Spec

Date: 2026-10-20. Status: APPROVED (user: "do it now"). Type: DATA INFRA FIX.
Builder: sonnet. Reviewer: Opus. No trading-logic changes.

## The bug

`.github/workflows/collect_data.yml` downloads the previous release's
`zerodha_data.db`, appends all-NSE minute bars (~190 MB/trading day), and
re-uploads the WHOLE file. It grew 1349 -> 1921 -> 2112 -> 2302 MB and on
2026-10-16 hit GitHub's 2 GiB release-asset cap ("File size (2302656512) is
greater than 2 GiB"); data-200 shipped with no DB, so 2026-10-19's run started
fresh (data-201 = 191 MB). Next cap hit in ~10 trading days. History up to
~2026-10-15 is intact in release data-199 (2.1 GB).

## Design

History = one Parquet file per trading date, stored as assets on monthly
releases tagged `minute-YYYY-MM` (asset name `minute_YYYY-MM-DD.parquet`).
The `data-N` release keeps shipping `zerodha_data.db`, but ROLLING: only the
newest 5 trading dates. Consumers of `zerodha_data.db` (Oracle bot
`kite/live_monitor/db_manager.py`, dashboard, reports) need NO change.

### 1. `archive_minute.py` (repo root, beside cloud_collector.py)

CLI: `python archive_minute.py --db data/zerodha_data.db --out data/parquet_out
[--recent 5] [--keep 5] [--min-symbols 1000] [--all-dates] [--no-prune]`
- Distinct dates come from `ohlcv.datetime` (first 10 chars; table schema:
  id, symbol, datetime, interval, open, high, low, close, volume, oi).
- Export: for each of the newest `--recent` dates (or every date with
  `--all-dates`), write `minute_<date>.parquet` with columns symbol, datetime
  (string as stored), open, high, low, close, volume, oi — interval='minute'
  rows only. pyarrow, zstd compression. Stream per date (never load the whole
  2 GB DB into memory).
- Sanity: a date with fewer than `--min-symbols` distinct symbols is NOT
  written; the script records it and exits non-zero at the end (after doing
  everything else), printing which dates were thin.
- Prune (unless `--no-prune`): delete rows (all intervals) whose date is older
  than the newest `--keep` distinct dates, then VACUUM. Prune runs only after
  every export for the dates being deleted succeeded — never delete a date that
  has not been written to Parquet in this run or does not already exist in
  `--out`.
- Print a summary: per date rows/symbols/parquet MB, DB size before/after.

### 2. `upload_minute_parquet.sh` (repo root)

`bash upload_minute_parquet.sh <dir>`: for each `minute_YYYY-MM-DD.parquet`,
ensure release `minute-YYYY-MM` exists in $GITHUB_REPOSITORY (default
addyfu/zerodha-data) — `gh release view` || `gh release create <tag> --title
"Minute history YYYY-MM" --notes "One Parquet file per trading day."` — then
`gh release upload <tag> <file> --clobber`. `set -euo pipefail`. Uses `gh`
(present on GitHub runners; needs GH_TOKEN env).

### 3. Workflow edits (`.github/workflows/collect_data.yml`)

- pip install adds `pyarrow`.
- After "Collect data", new step "Archive + prune":
  `python archive_minute.py --db data/zerodha_data.db --out data/parquet_out`
- New step "Upload daily parquet": `bash upload_minute_parquet.sh
  data/parquet_out` with `env: GH_TOKEN: ${{ secrets.GITHUB_TOKEN }}`.
- Both run BEFORE "Create release" (so the uploaded DB is the pruned one).
- Final step `if: failure()`: send Telegram via curl to
  api.telegram.org/bot$TELEGRAM_BOT_TOKEN/sendMessage with chat_id
  $TELEGRAM_CHAT_ID, text "❌ Daily Data Collection failed — run
  ${{ github.run_number }}: ${{ github.server_url }}/${{ github.repository }}/actions/runs/${{ github.run_id }}".
  Never echo the token.
- Keep everything else (schedule, inputs, data-N release, artifact backup).

### 4. `minute_history.py` (repo root) — research loader

`load_minute(start: str, end: str, symbols: list | None = None,
cache_dir='data/minute_parquet') -> pandas.DataFrame`
- For each weekday date in [start, end]: use cached
  `cache_dir/minute_<date>.parquet` if present; else download
  `https://github.com/addyfu/zerodha-data/releases/download/minute-YYYY-MM/minute_<date>.parquet`
  (public, plain requests; 404 = holiday/missing -> skip silently, record it).
- Filter symbols via pyarrow filters when given. Concatenate, return.
- `missing_dates(start, end)` helper returns weekdays with no file (for gap
  audits).

### 5. Backfill (builder builds + tests; REVIEWER runs it)

`archive_minute.py --all-dates --no-prune` is the backfill tool: reviewer will
run it against downloaded data-199 and data-201 DBs, then
`upload_minute_parquet.sh`. Builder must NOT upload anything or create
releases.

## Tests — `test_archive_minute.py` (repo root), plain asserts, no network

(a) synthetic DB, 8 dates x 3 symbols (`--min-symbols 2`): default run writes
    parquet for newest 5 dates, DB keeps exactly newest 5 dates afterwards,
    parquet row counts equal source rows.
(b) a thin date (1 symbol) inside the recent window -> not written, exit code
    non-zero, and that date is NOT pruned if it falls outside --keep.
(c) `--all-dates --no-prune` writes all 8, DB untouched.
(d) `load_minute` with a pre-filled cache dir returns correct rows/symbol
    filter and performs zero HTTP calls (monkeypatch requests.get to raise).
(e) `bash -n upload_minute_parquet.sh` passes (syntax), and YAML parses
    (`python -c "import yaml; yaml.safe_load(open(...))"` if PyYAML present).

## Out of scope

cloud_collector.py internals, Oracle sync script (reviewer disables its
timer), research scripts migrating to the loader.

## Decision log

- 2026-10-20: spec written; user asked to do it immediately.
