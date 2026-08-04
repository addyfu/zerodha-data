# Regime Exit on the Buy-and-Hold Core — Design Spec (Pre-Registered)

Date: 2026-08-04. Status: FROZEN. No changes after this line except decision-log
entries. Origin: shortlist candidate D,
docs/superpowers/specs/2026-08-04-entries-exits-research-shortlist.md section D
("cheap likely-funeral"). Stated prior in the shortlist itself: "industry-mined
to death, and our bar includes capital-gains tax on every exit, which
historically kills these. Expected verdict: FAIL." This spec exists to run that
funeral properly, not to save the idea — no rule below may be loosened after
seeing results.

## Hypothesis

Exiting NIFTY buy-and-hold to cash when the index is below its 200-day moving
average improves after-tax returns versus staying invested throughout.

## Data (frozen)

- NIFTY 50 price index, daily closes, as far back as obtainable. Target
  2005-present; actual range obtained is whatever the source returns — report
  it honestly, do not pad or splice in a second source.
- Source: yfinance `^NSEI` (auto_adjust=True daily close), the source this
  spec's own text names as acceptable. Probed 2026-08-04 from this
  environment: 4,630 rows, **2007-09-17 → 2026-08-04** — short of the 2005
  target by ~2 years (yfinance's own ^NSEI history limit; not a scraping
  failure). Stooq (the fallback used successfully by
  docs/superpowers/specs/2026-07-30-overnight-postopen-design.md for other
  series) was re-probed for NIFTY and returned the same anti-bot JS
  challenge page as before, not real data — confirms it is not a viable
  fallback in this environment, consistent with the prior study's finding.
  NSE's own historical-index archive was not attempted (no free bulk daily
  series endpoint known to be reachable without a browser session; out of
  scope for a small-effort candidate when the spec's own text already
  blesses yfinance). No Zerodha login, no enctoken, no DB writes — this
  study touches nothing under `data/` except a scratch CSV cache named
  `kite/research/regime_exit_cache.csv`.
- The 200-day moving average needs 200 trading days of history before its
  first valid value; the study's own "day zero" (GLOBAL_START) is therefore
  the 200th trading day of the fetched series, not the series' first date.
  Whatever that date turns out to be is reported in the results file.

## Method — two variants ONLY (frozen, no others)

- **V1 (monthly check):** at each calendar month's last trading-day close,
  compare close to the 200-day MA computed through that same day. If
  close < MA200: be in cash. Else: be invested. The decision is made and
  executed at that same day's close (no lag, no lookahead — both figures are
  already known on that day). Between month-end checks, hold whatever state
  was last decided; intra-month moves are ignored by construction — that is
  the point of "monthly check," not a bug.
- **V2 (daily check, 1% hysteresis band):** every trading day, compare close
  to MA200 computed through that day. Exit to cash when
  close < 0.99 × MA200. Re-enter when close > 1.01 × MA200. Inside the band
  (0.99×MA200 ≤ close ≤ 1.01×MA200), hold the current state — this is what
  "hysteresis" means and is what stops the band from being a third variant.
- **Initial state (GLOBAL_START):** each variant applies its OWN rule on
  GLOBAL_START itself to decide whether day one is spent in cash or invested
  (V1: is that day a month-end? if not, treat it as this variant's first
  decision point regardless, since it is the earliest day the rule can be
  evaluated at all; V2: apply the exit/re-entry thresholds directly — if
  GLOBAL_START's close falls inside the dead band with no prior state to
  hold, default to invested, the natural "buy-and-hold with an exit overlay"
  reading of the hypothesis). Buy-and-hold always starts invested at
  GLOBAL_START by definition — it has no rule to evaluate.
- All three lines (buy-and-hold, V1, V2) share the identical GLOBAL_START and
  GLOBAL_END dates, so CAGR figures are computed over identical windows and
  are directly comparable. No other variants, no parameter sweep, no
  optimization over the MA length or the band width — 200 days and 1% are
  fixed by this document, not fit.

## Costs (frozen)

0.05% slippage per side + delivery-style charges per side (STT 0.1%, stamp
duty 0.015% buy-side only, exchange+SEBI ~0.00317%), charged on every switch
(every exit AND every re-entry, each as its own "side"):
- Cost paid when SELLING (exit to cash): slippage 0.05% + STT 0.1% +
  exchange/SEBI 0.00317% = 0.15317% of the transacted value.
- Cost paid when BUYING (re-entry, or the initial purchase): slippage 0.05%
  + STT 0.1% + stamp duty 0.015% + exchange/SEBI 0.00317% = 0.16817% of the
  transacted value.
- A full round trip (exit then later re-entry) costs ~0.321% combined — this
  is the number every switch has to overcome before tax is even considered.

## Taxes (frozen)

Indian capital gains on every exit: gains on a holding held **>12 months**
taxed at the LTCG rate; **≤12 months** taxed at the STCG rate. Buy-and-hold
pays LTCG exactly once, at the very end of the study window (it never
exits before then).

**Current FY2026-27 rates, verified 2026-08-04 (do not trust memory, this
spec would have been wrong — pre-Budget-2024 LTCG was 10% over a ₹1L
exemption, not today's number):**
- **LTCG (Section 112A, listed equity, held >12 months): 12.5%**, on gains
  in excess of ₹1.25 lakh per financial year, for transfers on/after
  23-07-2024. Source: Income Tax Department (official),
  https://www.incometaxindia.gov.in/w/section-112a-60 — "12.5% in excess of
  Rs. 1,25,000 for any transfer which takes place on or after 23-07-2024."
- **STCG (Section 111A, listed equity, held ≤12 months): 20%**, for
  transfers on/after 23-07-2024, where STT is paid. Source: corroborated by
  ClearTax, TaxGarden, and CACube (independent reputable Indian tax
  publishers), all citing the same Section 111A rate and effective date;
  cross-checked against the Income Tax Department's own Section 112A page
  for the shared 23-07-2024 effective-date anchor.
- **Budget 2026 (most recent, before this spec's freeze date) made no change
  to either rate** — multiple sources (Precize, Lakshmishree, MoneyKit,
  CACube) independently confirm the 12.5%/20% structure, the ₹1.25L LTCG
  exemption, and the 12-month holding threshold all carry into FY2026-27
  unchanged.
- **4% health & education cess and any income-linked surcharge are NOT
  modeled** — surcharge is income-bracket dependent (no income assumption
  exists in this study) and cess would scale both arms' tax bills by the
  same 1.04× multiplier, non-decisive for a beats/loses-to-benchmark
  comparison. Stated, not hidden.
- **The ₹1.25 lakh annual LTCG exemption is NOT modeled.** This study
  reports scale-free CAGR, not an absolute-rupee position; applying a
  rupee-denominated annual exemption would require inventing an arbitrary
  starting capital the spec does not otherwise need. Flat-rate tax (no
  exemption) is the literal reading of this document's own tax rule above,
  and it is a bias AGAINST the switching variants specifically: in reality
  each year V1/V2 realizes a gain, part of it would land in the tax-free
  band; buy-and-hold realizes only once and its single gain dwarfs ₹1.25L
  regardless, so omitting the exemption barely touches the benchmark while
  costing the switching variants a real (if modest) shield every time they
  exit in the green. Consistent with this spec's other pro-benchmark
  leanings (see cash yield, below).
- **No loss carry-forward.** A losing exit pays zero tax (no rebate) and
  does not offset a later gain. Simplification, stated.
- Gain for tax purposes = (net sale proceeds, after sell-side costs) − (net
  cost basis, i.e. the capital actually deployed after buy-side costs was
  paid) — an economic-P&L convention, not a strict application of every
  nuance of what is/isn't deductible under Indian case law (e.g. whether
  STT itself is deductible from sale consideration is disputed in practice
  and not modeled either way). Stated.
- Holding period for the LTCG/STCG split: `holding_days > 365` → LTCG, else
  STCG, where `holding_days` is the calendar-day gap between entry and exit
  dates — a direct proxy for "more than 12 months."

## Eras (frozen, reported separately)

2005-2015, 2016-2020, 2021-present, and the full period. Each era's start
and end are clipped to the actually-obtained data range (GLOBAL_START /
GLOBAL_END) — if an era's declared start predates GLOBAL_START (certain for
2005-2015, since data starts 2007-09), the era is reported using whatever
sub-window actually exists, flagged as such, never silently padded.
"Present" = GLOBAL_END, the last trading day actually obtained.

Era-level after-tax CAGR needs a value even mid-holding (an open position
that hasn't been sold yet has paid no real tax). This spec's chosen
convention, applied uniformly to all three lines at every era boundary
except the one exception below: mark an open position to market and apply
the tax rate it WOULD owe if sold that day (12.5% or 20%, by the same
>365-day rule, on any positive unrealized gain; zero on an unrealized
loss). This is a notional/paper tax for reporting only, not a real cash
event — it exists so an era boundary landing mid-holding produces an
honest, comparable number instead of either a fictitious 0%-tax mark or an
arbitrary full liquidation. **Exception:** at GLOBAL_END specifically,
buy-and-hold's mark-to-market number and its real "sell once, pay LTCG
once, pay the one-time sell-side cost" number are, by construction, the
same figure (by GLOBAL_END its holding is certainly >365 days old, so the
notional and real LTCG computations coincide) — the one-time sell-side
transaction cost is the only thing added on top at that single boundary,
matching "buy-and-hold pays LTCG once at the end" literally. V1/V2 are
never force-liquidated at GLOBAL_END; if either is mid-holding there, its
GLOBAL_END figure is the same mark-to-market convention as every other
era boundary, consistent with them being live ongoing strategies, not
wound up on the study's last day.

## Pass bar (frozen)

V1 or V2 after-tax, after-cost CAGR strictly exceeds buy-and-hold
after-tax CAGR over the FULL period AND in at least 2 of the 3 eras.
Anything else — including "wins on the full period but only 1 era," "wins
0 eras," or "an era is N/A for lack of data and therefore can't be won" —
is FAIL. No partial credit, no re-scoring after the fact.

## Cash yield (frozen, biased against the strategy — stated plainly)

Cash earns 0% while a variant is out of the market. This is a conservative
assumption working AGAINST V1/V2 relative to reality (idle cash could sit
in a savings account or liquid fund and earn something) — but 0% is the
correct FIRST test: if a regime-exit strategy cannot clear buy-and-hold
even with its idle cash earning nothing, it does not need a fancier cash
model to be pronounced dead. If the funeral test somehow fails to bury the
idea even at 0% cash yield, THEN a follow-up with a realistic cash yield
would be the natural next question — not before.

## Self-check requirement (frozen)

The implementation must include a standalone, plain-`assert` self-check of
the core switching/tax/cost/mark-to-market logic against a synthetic price
series where the correct answer is hand-computable, run automatically
before the real data run, printed to the console and captured in the
results file. This is not optional and not a suggestion.

## Decision log

- 2026-08-04: Spec frozen (per task instruction, pre-registered before any
  code). Data source probed and confirmed (yfinance ^NSEI, 2007-09-17 →
  2026-08-04; stooq re-confirmed non-viable). Tax rates verified via web
  search against the Income Tax Department's own Section 112A page plus
  three independent reputable secondary sources, all agreeing: LTCG 12.5%
  (>₹1.25L/yr exemption), STCG 20%, both effective 23-07-2024 onward,
  unchanged by Budget 2026.
