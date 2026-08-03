# NIFTY Options Minute-Bar Forward Collector — Design Spec

Date: 2026-08-03. Status: APPROVED (user). Type: INFRASTRUCTURE (data
collector). This is plumbing, not a study — there are no pass/fail verdict
bars. The frozen parts are the MECHANICAL RULES below: they exist so the
archive we hand future-us is unbiased. Any later change to a mechanical rule
gets a decision-log entry with a date, so a backtest can split the archive
at the rule change.

## Why this exists (time pressure, unlike the studies)

Zerodha's free chart API serves minute candles only for LIVE contracts;
an expired option's minute history disappears from the free path forever.
Our acquired archive (data/options/MANIFEST.md) ends 2026-05-05. Every
uncollected week is permanently lost. Studies wait until after October
(user decision 2026-08-03); collection cannot.

## What it collects (mechanical rules — the frozen part)

1. Underlying: NIFTY index options only (matches the acquired archive).
2. Expiry selection: the TWO nearest unexpired NIFTY option expiries, taken
   from Zerodha's public instrument dump (api.kite.trade/instruments,
   NFO-OPT rows, name=NIFTY). No hardcoded expiry weekday — NSE has moved
   expiry days before; discovery is the rule.
3. Strike window: all listed strikes within ±1,000 index points of spot,
   both CE and PE, both selected expiries. Strike list comes from the
   instrument dump (no hardcoded 50/100-point step assumptions).
4. Spot: latest NIFTY 50 index close from the chart API (instrument token
   256265), asserted to be within [10,000, 60,000]. If the index fetch
   fails, the run FAILS loudly (no fallback spot — a wrong center biases
   the archive silently).
5. Self-healing fetch: per contract, fetch minute bars from
   max(contract listing, last stored ts + 1 min) → now, with oi=1.
   Upsert (INSERT OR REPLACE). Consequences, stated:
   - A missed day heals automatically on the next run while the contract
     lives (weekly contracts ⇒ up to ~a week of grace).
   - A big spot move re-centers the window next run, and newly-entering
     strikes get their FULL contract history fetched retroactively — so a
     crash day's wing strikes are captured as long as the collector runs
     once before that expiry dies.
6. Zero-volume minutes are stored as returned (volume=0 rows carry no
   trustworthy OHLC — same caveat as the acquired archive; the filter is
   the CONSUMER's job, per MANIFEST.md).

## Storage

data/options_data.db (SQLite, separate from zerodha_data.db — the nightly
release sync atomically replaces zerodha_data.db and must never touch this).

- option_bars(tradingsymbol, expiry, strike, opt_type, ts, open, high,
  low, close, volume, oi) PK(tradingsymbol, ts) — column meanings identical
  to the acquired archive so the two concatenate cleanly.
- collection_runs(run_date, started_at, finished_at, expiries, contracts,
  contracts_empty, rows_added, status, note) — one row per run; this is the
  heartbeat trail.

## Tripwires (NSE-silent-failure discipline; all HTTP 200 lessons apply)

- Token missing/stale (enctoken.txt absent or API 403): CRITICAL log,
  exit 1 (systemd shows failure). Never attempts a login of its own —
  same one-session rule as report_positions.py.
- Empty-chain tripwire: on a day the NIFTY index itself printed bars,
  >30% of selected contracts returning zero rows ⇒ CRITICAL, exit 1.
  If the index printed nothing (holiday), exit 0 quietly.
- Run summary line ALWAYS logged (date, expiries, contracts, rows added,
  empty count) to data/options_collector.log — greppable heartbeat.
- Pacing 0.3s between contract fetches (daily_collector convention);
  ~150-250 contracts ⇒ ~1-2 min per run.

## Deployment

- options_collector.py at repo root (sibling and stylistic sibling of
  daily_collector.py). Reads the token from repo-root enctoken.txt (the
  file monitor.py persists at 09:10 login) or ZERODHA_ENCTOKEN env.
- Oracle systemd: kite-options-collector.service (oneshot) +
  kite-options-collector.timer, Mon..Fri 15:45:00 Asia/Kolkata
  (market closed; monitor's morning token still fresh; well before the
  19:45 release sync).
- Known gap, accepted for v1: the DB lives only on Oracle; backup is a
  manual scp until an automated push is worth building. Logged here so
  it is a decision, not an oversight.

## Verification checklist (reviewer, before deploy)

- [ ] Instrument-dump parsing: expiry/strike/type pulled from the correct
      NFO-OPT columns; two-nearest-expiry logic correct at an expiry-day
      boundary (the day an expiry dies, selection must roll forward).
- [ ] oi=1 requested and the 7th candle field parsed into oi.
- [ ] Upsert is idempotent (run twice ⇒ zero net new rows).
- [ ] Tripwires fire: fake dead token ⇒ exit 1; empty-chain simulation
      ⇒ exit 1; holiday simulation ⇒ exit 0.
- [ ] Live smoke from the PC (its own enctoken.txt): a handful of current-
      expiry strikes fetch real rows; prices sane vs spot/strike; near-ATM
      volume > 0.
- [ ] No import of zerodha_auto_login anywhere in the file.

## Decision log

- 2026-08-03: Spec written and approved (user: "spec and plan and build,
  reviewer verifies"). Builder: sonnet subagent. Reviewer: Fable (this
  session).
- 2026-08-03 (build, reviewer-accepted): builder resolutions — ts stored as
  str(pandas.Timestamp) with +05:30 offset (mirrors zerodha_data.db exactly,
  NOT the spec prose's guessed T-separated naive format; spec's own "mirror
  daily_collector" escape hatch invoked); bare datetime.now() everywhere
  (project-wide system-clock-is-IST convention); mid-run 403 counts the
  contract empty instead of crashing (aggregate tripwire catches broad
  breakage; 403 on the FIRST fetch and on the holiday check stay fatal);
  instrument dump parsed by header name, not position.
- 2026-08-03 (reviewer fix): same-day post-close re-run false-tripwire —
  a second run the same evening put every contract's from_dt at >= 15:30
  with zero fetchable bars, counting 100% empty and tripping the wire on a
  healthy archive. Guard added (same-date from_dt >= 15:30 => skip as
  up-to-date); regression test added. 7/7 offline tests pass.
- 2026-08-03 (live smoke, PC token): discovery found expiries 2026-08-04 +
  2026-08-11 (Tuesday weeklies — no-hardcoded-weekday rule vindicated),
  spot 24,774.3, 160 contracts in window. 12-contract bounded run: 95,430
  rows (45-day lookback captured full contract life), re-run 0 rows/status
  ok (idempotency + tripwire guard verified live). Dead-token path also
  fired live (PC's stale token 403'd) before refresh. DATA QUALITY: put-call
  parity across 6 strikes implies forward 24,591 == the index's actual
  traded level at 15:25-15:29; the official close 24,774 is the closing-
  auction construct printed into the final index minute bar (+200pt last-
  bar artifact on this rebalance Monday). Options archive is faithful to
  traded prices. Bars through ~15:39 exist (post-close settlement prints,
  real volume) — stored as served, consumer filters.
- 2026-08-03: Deployed to Oracle; timer enabled; first scheduled run
  2026-08-04 15:45 IST (first Oracle run needs monitor's 09:10 token —
  by design, no token exists on the box tonight).
