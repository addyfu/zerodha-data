# Dashboard Position Charts — Design Spec

Date: 2026-08-05. Status: APPROVED (user: "build the spec and spawn sonnet").
Type: INFRASTRUCTURE (dashboard feature). Builder: sonnet. Reviewer: Fable.
Read-only feature — this must never write to any DB, never log in, never
place the dashboard in the session war we just ended.

## What it does

Every position row on the dashboard (open positions, today's closed trades)
becomes a link. Clicking it opens a chart view for that (symbol, date,
strategy): candlesticks with the STRATEGY'S OWN indicator plotted, plus the
trade's entry/stop/target as horizontal lines and entry/exit markers.
Purpose: see what the bot saw. This is a trade-review tool, not decoration.

## Mechanical rules

1. INDICATOR FIDELITY (the one non-negotiable): the chart plots what the
   strategy actually computes — same code path or, where impractical,
   identical parameters read from the same config the SignalDetector uses,
   never hardcoded copies. The JSON response echoes the parameters used
   (e.g. {"indicator": "bollinger", "period": 20, "std": 2}) so a human
   can audit chart-vs-strategy parity. If the builder cannot establish a
   strategy's exact params from code, the chart says "indicator
   unavailable" rather than plotting a guess.
2. Strategy -> chart mapping (builder verifies each against
   signal_detector.py/config.py and echoes findings in results):
   - bb_mean_reversion: minute candles + Bollinger bands overlay
   - cci_divergence: minute candles + CCI subpane
   - choppiness_filter: minute candles + choppiness-index subpane
   - adx_filter: minute candles + ADX subpane
   - rsi_trend_confirmation: minute candles + RSI subpane
   - momo_rotation_63: DAILY candles (~6 months) + 63-day momentum %
     subpane — rotation decisions are daily-scale; minute noise is the
     wrong lens for it.
3. Data ladder (mirrors the price-ladder fix, 2026-08-05):
   - Minute bars for TODAY: chart API, token from repo-root enctoken.txt /
     ZERODHA_ENCTOKEN env — read-only reuse of the existing session, NEVER
     a login (one-session rule; a dead token degrades, see rule 5).
   - Minute bars for past days + all daily bars: data/zerodha_data.db
     (read-only connection).
   - In-process cache, 60s TTL per (symbol, interval): page refreshes and
     repeat clicks must not hammer Zerodha.
4. Chart window: intraday trades — that trade's full day 09:15-15:30 plus
   the prior session for context; rotation — ~130 trading days of daily
   candles. Entry/exit markers only within the shown window.
5. Fail-soft everywhere (dashboard discipline): dead token, missing bars,
   unknown strategy, missing DB — the chart page renders a plain
   "chart unavailable: <reason>" line; the server never 500s, the position
   tables never break. A tier that fails silently falls to the next tier
   with the staleness visible (candles from the stale DB get the same
   loud stale tag convention as prices).
6. Rendering: vendored TradingView lightweight-charts (single standalone
   JS file, Apache-2.0, committed into the repo and served by the
   dashboard itself — NO CDN, page stays self-contained). One new endpoint
   GET /chart?symbol=..&date=..&strategy=..&book=.. returning JSON
   {candles, indicator series, trade levels, params-echo}; one new page
   route rendering the chart container + vendored JS. Main dashboard page
   gains only <a> links — its existing rendering must not change beyond
   that.

## Tests (plain asserts, style of test_dashboard_prices.py)

(a) endpoint JSON correct on synthetic DBs (candles + levels + markers);
(b) indicator parity: builder's indicator values match SignalDetector's
    own computation on a shared fixture series (the fidelity rule, tested);
(c) cache: second call within TTL performs zero fetches (counter);
(d) no token + no DB coverage -> "chart unavailable", HTTP 200, no raise;
(e) unknown strategy -> unavailable, no raise;
(f) rotation mapping returns daily candles, intraday returns minute;
(g) rendered chart page contains container div, vendored JS reference,
    and the params echo.

## Out of scope (v1)

Live-updating charts (static per click is fine), drawing tools, multi-day
intraday panning, incubator-vs-main visual theming, any change to
monitor.py or collectors.

## Deployment

Reviewer deploys after line-by-line review: scp dashboard.py + static JS +
tests, restart kite-dashboard, verify a real chart renders on Oracle for
one open rotation position and one closed intraday trade, then commit.

## Decision log

- 2026-08-05: Spec written and approved. Charts queued behind the day's
  verification work (TZ-fix release check, CAS backfill debut, parity
  sweep) — build proceeds in parallel; deploy waits for reviewer.
