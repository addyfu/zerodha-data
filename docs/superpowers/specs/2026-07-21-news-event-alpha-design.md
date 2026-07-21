# News/Event Alpha Project — Design Spec (Pre-Registered)

Date: 2026-07-21. Status: DRAFT — awaiting user approval before Phase 1 begins.
Author: Claude + Aditya. Discipline: same falsification-first protocol as the
July 2026 strategy audit (see kite/research/ — ~130 strategies tested, honest
harness, pre-registered criteria).

---

## 1. Hypothesis

Price-pattern alpha on NSE is dead at retail scale (established: 78 strategies,
17 intraday families, momentum grids, chart-vision trials — all falsified).
The one input class our machinery has never tested is **text**: corporate
announcements, whose interpretation requires language understanding.

**H1 (category effect):** certain announcement categories (order wins, pledge
creation/release, resignations, results, ratings actions) are followed by
abnormal returns exploitable at retail latency (next-day-open entry).

**H2 (LLM increment):** an LLM reading the announcement *text* — sizing an
order win against market cap, reading guidance tone, detecting surprise —
predicts abnormal returns better than the category label alone.

H2 only matters if H1 or its LLM-conditioned version survives costs. Both can
fail; that outcome is a valid, useful verdict.

## 2. Why this might work when price patterns didn't

- Event-reaction nuance requires reading; most retail can't systematize it and
  most institutions in India focus text-mining on large caps. Mid/smallcap
  announcement flow is plausibly under-processed (same breadth logic as the
  universe study, but on an input rules cannot parse).
- Post-announcement drift is a documented anomaly internationally (PEAD —
  post-earnings-announcement drift persists for decades in the literature).
  India-specific published evidence exists but is thin — which is the
  opportunity and the risk.

## 3. Non-goals

- No real-money trading from this project. Endpoint = incubator (paper) at best.
- No intraday reaction-speed play (we lose latency races by construction —
  entries are next-day-open only).
- No social-media sentiment in v1 (unverifiable data quality; announcements
  are official, timestamped, complete).

---

## Phase 1 — Data Acquisition

**Deliverable:** `data/announcements/` archive + loader.

1. **Corporate announcements**: NSE and BSE official archives (free,
   timestamped, ticker-tagged, categorized). Downloader
   `kite/research/fetch_announcements.py`:
   - Target window: 2020-01-01 → present (5.5+ years).
   - Fields: timestamp (IST, exchange receipt time), symbol, category,
     subject, attachment text where available (PDF extraction best-effort,
     subject line is the v1 fallback).
   - Storage: one parquet/CSV per year: `announcements_<year>.csv`.
   - Rate-limited, resumable (lesson from the universe fetch: retry wrapper,
     single session, checkpoint files).
2. **Join keys**: symbol normalization map (announcement symbols ↔
   daily_universe symbols); drop announcements for stocks outside our 679-stock
   price universe.
3. **Quality gate** (pre-registered): ≥100,000 usable announcements AND ≥60%
   joinable to price data, else pause and reassess sourcing before any
   analysis.

**Effort:** 1 evening. **Cost:** ₹0.

**Known risks:** NSE archive endpoints are JS/bot-protected (hit this in the
verification session — SLB page unfetchable). Fallback order: NSE JSON API →
BSE archive → both-partial. PDF text extraction quality varies; v1 may run on
subject lines + categories only, which weakens H2 tests (flag in results).

## Phase 2 — Deterministic Event Study (no LLM)

**Deliverable:** `kite/research/event_study.py` + results table.

Method (standard event-study, adapted to our harness conventions):
1. Event day E = first trading day on/after announcement timestamp
   (announcements after 15:30 roll to next day — timestamp discipline is
   critical; this is where lookahead hides).
2. **Abnormal return** AR(t) = stock return − equal-weight universe return
   (market model kept simple deliberately; beta-adjustment as sensitivity
   check only).
3. Windows: entry at E+1 open (retail-realistic), measure cumulative AR over
   E+1→E+2, E+1→E+5, E+1→E+20. Delivery costs + 0.2% slippage/side on the
   tradeable variants.
4. Group by announcement category × market-cap tercile × era
   (2020-2022 / 2023-2024 / 2025-2026). Report N, mean/median CAR, t-stat,
   % positive.
5. **Multiple-testing control:** with ~30 categories × 3 caps × 3 eras,
   ~270 cells — apply Benjamini-Hochberg FDR at 10%; only cells surviving
   correction count as candidate effects.

**Pre-registered H1 verdict rule:** a candidate effect must (a) survive FDR,
(b) be consistent in sign across ≥2 of 3 eras, (c) show mean net CAR after
costs ≥ 0.5% at the 5-day window. Zero qualifying cells → H1 dead → project
ends at Phase 2 (H2 untested — no fishing in a dead pond).

**Effort:** 1 evening. **Cost:** ₹0.

## Phase 3 — LLM Scoring Layer (only if H1 produced qualifying cells)

**Deliverable:** `kite/research/event_llm_score.py` + incremental-value table.

1. Sample: all announcements in qualifying categories + a matched random
   control sample of non-qualifying ones (so the LLM can't win by category
   identification alone).
2. **Anonymization (mandatory — chart-trial lesson):** strip company names,
   ticker symbols, and person names from text before scoring; replace with
   COMPANY/PERSON tokens. Market cap provided as a bucket label, not name.
3. LLM (haiku for bulk, sonnet for a 500-item agreement audit) scores each
   text: direction (-2..+2), magnitude-vs-company-size (1-5), surprise (1-5),
   one-line rationale. Fixed prompt, frozen before first batch.
4. **Clean-window priority:** primary verdict computed on announcements dated
   AFTER the scoring model's training cutoff (2026 window); pre-cutoff results
   reported but labeled contaminated-possible.
5. **Pre-registered H2 verdict rule:** within qualifying categories, top-tercile
   LLM-score events must show ≥1.0% higher 5-day net CAR than bottom-tercile,
   surviving a permutation test at p<0.05, in the clean window. Else H2 dead
   (H1-only strategy may still proceed if it qualified).

**Effort:** ~half a day. **Cost:** API — ~50-100k scored items ≈ modest haiku
spend; sonnet audit small. Estimate before running; abort if >$50 equivalent.

## Phase 4 — Live Paper Pipeline (only on H1-pass; H2 layer only on H2-pass)

**Deliverable:** `kite/live_monitor/event_scanner.py` + incubator wiring.

1. Poll NSE/BSE announcements every 15 min during market hours.
2. Filter to qualifying categories (+ LLM gate if H2 passed; live scoring via
   API with the frozen prompt).
3. Signal → incubator book, trade_mode "ROTATION"-style (no trailing
   interference), position = capital/5 slot, exit at pre-registered horizon
   (the qualifying window, e.g. E+5 close) or 15% disaster stop.
4. Expectation Book entry generated from Phase 2/3 stats; parity monitor
   (self-auditing system spec) watches live vs expected from day one.
5. Promotion rules: standard incubator protocol — ≥60 live paper events AND
   performance inside the historical confidence band.

**Effort:** 1 evening + ongoing ~zero (rides existing monitor infra).

---

## Kill criteria summary (all pre-registered, none negotiable after data)

| gate | rule | on failure |
|---|---|---|
| Phase 1 quality | ≥100k usable, ≥60% joinable | pause, reassess sourcing |
| H1 (Phase 2) | FDR-surviving, era-consistent, ≥0.5% net 5d CAR | project ends |
| H2 (Phase 3) | ≥1.0% tercile spread, p<0.05, clean window | H1-only variant proceeds |
| Phase 4 | standard incubator promotion rules | strategy dies in paper |

## Confound register (what could fake a positive)

1. **Timestamp lookahead** — announcement time vs price reaction; mitigated by
   exchange receipt timestamps + E+1-open entries; audited by sampling 50
   events manually.
2. **LLM training contamination** — model "remembers" what happened to the
   company; mitigated by anonymization + clean-window priority.
3. **Survivorship** — universe is today-liquid stocks (documented limitation,
   same as universe study; delisted-stock announcements absent).
4. **Category drift** — exchanges recategorize over time; category mapping
   table versioned.
5. **Multiple testing** — FDR control in Phase 2; single pre-registered
   verdict metric in Phase 3.
6. **Illiquidity mirage** — smallcap CARs that can't absorb even one retail
   order; turnover gate (2cr median) inherited from universe lab.

## Decision log

- 2026-07-21: Spec drafted. Awaiting approval to begin Phase 1.
