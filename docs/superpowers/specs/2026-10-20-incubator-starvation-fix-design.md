# Incubator Starvation Fix — Design Spec

Date: 2026-10-20. Status: APPROVED (user chose option A: all three fixes,
intraday resumes). Type: BUG FIX. Builder: sonnet. Reviewer: Opus.
Paper-trading only. October Contract gate untouched.

## The bug (diagnosed from Oracle logs 2026-10-20)

1. `monitor.check_open_positions()` prices open positions from
   `fetcher.get_quote()` (dead for enctoken sessions since 2026-08-04, always
   returns {}) and falls back to `self.data_cache`, which only holds NIFTY 50.
   Incubator swing positions (non-NIFTY-50: DEEPAKFERT, BSE, GESHIP, RATEGAIN,
   AJANTPHARM) get NO price -> `check_exits()` never evaluates their SL/TP ->
   they can only leave via an opposite daily signal. DEEPAKFERT held since
   2026-08-03, now 1256 vs stop 1465.
2. Incubator `PaperTrader(max_positions=5)` is shared by intraday and swing.
   On 2026-09-14 09:25 AJANTPHARM took slot 5 (cash left Rs 1,349). From then
   ~100 intraday signals/day were rejected: "Max positions (5) reached".
3. `parity_monitor.check_p3` saw k=0 trades in 21td and paused all incubator
   strategies 2026-10-12..14 (`data/strategies_paused.json`). The strategies
   were fine; the book was full.

## Fix 1 — every open position gets a price, or a loud alert

File: `kite/live_monitor/monitor.py`, `check_open_positions()`.

Price ladder, per symbol, filling only what's still missing:
  a. `get_quote()` result (keep — harmless if it ever comes back);
  b. `self.data_cache[s]` last close (existing behaviour);
  c. NEW: chart API via the existing fetcher,
     `self.fetcher.get_historical_data(sym, interval="minute", days=5)` — last
     row's close (same call `report_positions.py` already uses successfully).
     Wrap each symbol in try/except; a failure leaves the symbol missing.
     NEVER log in (one-session rule) — only reuse `self.fetcher`.
  d. Still missing after (c): log WARNING and send ONE Telegram message per
     symbol per day: "⚠ no price for <SYM> (<book>) — stop-loss NOT checked".
     Keep the once-per-day dedupe in an in-memory dict keyed (symbol, date).

Remove the early `return` paths that skip everything when quotes are empty and
data_cache is empty — the ladder must still try (c) for every held symbol.
The rest of the function (save_latest_prices, incubator check_exits, main
check_exits) is unchanged and simply receives a fuller price dict.

## Fix 2 — swing trades capped at 2 incubator slots

File: `kite/live_monitor/monitor.py`, `scan_swing_candidates()`.
Add class constant `MAX_SWING_SLOTS = 2`. Immediately before
`self.entry.try_enter(self.incubator, signal, 'CANDIDATE', 'incubator')`,
count incubator positions whose `trade_mode` is `'ROTATION'` or `'SWING'`;
if count >= MAX_SWING_SLOTS, log INFO
"CANDIDATE gate: <SYM> blocked — swing slots full (n/2)" and `continue`.
Existing swing positions are NOT force-closed; the cap only blocks new ones.
Exit logic in the same loop (opposite SELL closes a held BUY) is unchanged.

## Fix 3 — un-pause, and stop P3 instantly re-pausing

File: `kite/live_monitor/parity_monitor.py`, `check_p3()`.
New optional file `data/p3_reset.json` = {"date": "YYYY-MM-DD"}. If present
and parseable:
  - window_start = max(existing window_start, reset date)
  - if trading days since reset date < 10 -> return WARMING_UP with detail
    "k/10 trading days since P3 reset <date>".
Missing/corrupt file -> behave exactly as today. Nothing else in parity
changes. (Reviewer will, at deploy time, write p3_reset.json with 2026-10-21
and delete strategies_paused.json — builder does NOT touch data/ files.)

## Fix 4 — no trading on market holidays (added 2026-10-20 17:30)

Found during review: `is_market_hours()` checks clock time only. On NSE
holidays (2026-06-26, 09-14, 10-02, 10-20 confirmed via RELIANCE daily
candles) the monitor scanned frozen prior-day bars all day, and on 2026-09-14
09:25 it OPENED AJANTPHARM at a stale price — the very trade that filled slot 5.

File: `kite/live_monitor/monitor.py`. Data-driven, no hardcoded holiday list:
add `market_open_today()` -> bool. After 09:20 IST, it is True only if at
least one NIFTY 50 symbol in `self.data_cache` has a bar dated today (after
`update_with_latest_candle()` ran). Before 09:20 -> True (don't block the
open). Cache the answer for the day once it becomes True; while False, re-check
each cycle (so a slow data start isn't a permanent block). When False after
09:20: skip ALL entries (intraday scan, swing scan, rotation) AND exit checks
for that cycle; log INFO "Market closed today (no bars dated <today>) —
skipping"; send ONE Telegram message per day. Wire it where the scan cycle
already calls `is_market_hours()` — smallest change that gates every entry
path and check_open_positions.

Test (e): data_cache with only yesterday-dated bars at a simulated 10:00 ->
market_open_today() False and no entry path is called; with a today-dated bar
-> True.

## Tests — one new file `kite/live_monitor/test_starvation_fix.py`, plain asserts

(a) Fix 1: fake fetcher where get_quote -> {}, data_cache has only NIFTY50
    symbol A, chart call returns a DataFrame for non-N50 symbol B. Incubator
    holds B with stop above B's chart price -> after check_open_positions,
    B is closed with stop_loss. (Build a Monitor via __new__ + minimal attrs,
    or the lightest seam the builder finds; do not hit the network.)
(b) Fix 1: chart call raises for symbol C -> exactly one Telegram warning on
    two consecutive calls the same day; no exception escapes.
(c) Fix 2: incubator with 2 ROTATION positions -> a new swing BUY signal is
    not entered; with 1 -> it is entered.
(d) Fix 3: p3_reset 3 trading days ago + k=0 -> WARMING_UP, not RED; no reset
    file -> today's RED behaviour unchanged (rough-lambda card, k=0, mu>=10).
Also run the existing test_dashboard_*.py and test_report_marks.py — must
still pass.

## Out of scope

Separate intraday/swing capital accounts, smarter P3 (reading "Max positions"
log lines), main-book changes, release-sync failure, HTTP 429 tuning.

## Deployment (reviewer)

After review: scp monitor.py + parity_monitor.py + test file to Oracle, run
tests there, write data/p3_reset.json {"date":"2026-10-21"}, move
strategies_paused.json to strategies_paused.json.bak-20261020, verify the
monitor imports cleanly (`python -c "import kite.live_monitor.monitor"`).
Monitor is a timer-started service at 09:10 — no restart needed tonight.
Commit locally.

## Decision log

- 2026-10-20: written after log forensics; user picked option A.
