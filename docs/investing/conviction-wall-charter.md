# The Conviction Wall Charter

*A decision framework for a ring-fenced Rs 50,000 individual-stock allocation. Not stock
tips — a pre-registered process with an honest scoreboard, built in the same spirit as the
137 backtests that already failed: skepticism first, evidence over narrative, and a
scoreboard that's allowed to say "the index won."*

Researched and drafted 2026-07-29 (sonnet agent, reviewer-verified). Pledge-data columns
verified against data/pledge/ by reviewer: `symbol`, `promoterName`, `encumbPerc`,
`postEventHoldingPerc`, `eventDetailsType` (Creation/Revocation/Invocation),
`reportingDate` all present.

## 0. Ground rules

- Rs 50,000 is the ENTIRE lifetime capital for this experiment. No refills, ever. Zero =
  experiment over, and "stock-picking doesn't work for this person" is a valid recorded
  result — exactly like a failed backtest.
- Direct equity, cash market (CNC/delivery) only, existing Zerodha account. No F&O, no
  MTF/leverage, no SME board. (SEBI Sept-2024: 93% of 1cr+ individual F&O traders lost
  money FY22-24, aggregate -Rs 1.8 lakh crore.)
- Held 2-3+ years minimum by design — a test of business-selection skill, not trading.

## 1. Picking framework

Free sources: screener.in (10yr financials, shareholding, Documents tab with annual
reports + concall transcripts), company annual-report PDFs, NSE/BSE corporate
announcements (Reg 30 primary filings), NSE ASM / GSM surveillance lists, and OUR OWN
data/pledge/*.csv (139 monthly files, 2015-01..2026-07 — full promoter-encumbrance event
trail incl. Invocation events; deeper history than any free UI).

Annual-report sections that matter: chairman's letter vs delivered numbers; auditor's
report (qualified opinions, Emphasis of Matter, Key Audit Matters); Notes → related-party
transactions; Notes → contingent liabilities (group guarantees); cash-flow statement vs
P&L over multiple years; corporate-governance report. Concalls: does Q&A answer directly,
and did last call's promises land this quarter.

### The 10-point checklist (all 5 quality PASS + zero red flags before a rupee moves)

Quality (multi-year evidence, not one good year):
1. ROCE >= 15% in at least 7 of last 10 years (Coffee Can bar).
2. Revenue and PAT CAGR >= 10% over 10 years, not one-off driven.
3. Debt/equity low and flat-or-falling; comfortable interest coverage.
4. Cumulative CFO tracks cumulative PAT (>=80-90% over 5-10 yrs) — profit that never
   becomes cash is the Manpasand pattern.
5. Promoter holding flat/rising over 3-5 yrs; pledge absent or declining.

Red flags (any ONE = hard no at entry; post-entry = mandatory re-check):
6. Promoter pledge present/rising, or ANY Invocation event — check the on-disk pledge
   trail (grep symbol across data/pledge/, sort by reportingDate; Invocation = alarm).
7. Related-party transactions growing as share of revenue; loans/guarantees to unlisted
   group entities.
8. Frequent dilution — repeated preferential allotments/warrants, esp. to promoters at
   discount.
9. Auditor resignation mid-year, qualified opinion, or auditor churn (the Vakrangee tell).
10. On ASM/GSM lists, SME board, or a "concept stock" (narrative-first, no multi-year
    profitable history to even run items 1-4 against — the Sadhna/pump-and-dump zone).

## 2. Portfolio rules (frozen before first buy)

- 3-5 names, equal weight (4 x 12.5k or 5 x 10k). Count chosen BEFORE candidates.
- Floors per name, at entry and quarterly: mcap >= Rs 5,000cr; listed+audited >= 3yrs;
  not on ASM/GSM; liquid mainboard.
- Averaging down: DEFAULT NEVER. Optional pre-committed single second tranche only
  (60/40 split declared upfront; deploys only if price -25%+ AND full checklist still
  passes AND no new money). Never a third.
- Selling: THESIS-BREAK = sell, no debate (any red flag trips; ROCE < bar 2 consecutive
  yrs; unexplained promoter-stake fall; cash conversion collapse; guidance missed 2
  quarters unexplained). PRICE-DROP ALONE = never a sell trigger, never a buy trigger.

## 3. The honest scoreboard

- Every wall buy is mirrored same-date/same-amount into a real NIFTY 50 index fund
  direct plan (the counterfactual SIP; dividend reinvestment embedded in NAV).
- XIRR both sides on actual cash-flow dates.
- 2-year checkpoint: informational only, no action.
- 3-year checkpoint, PRE-REGISTERED: PASS = wall XIRR beats benchmark XIRR by >= 5pp
  annualized AND >= 3 of the names individually beat the benchmark (breadth bar —
  one lucky 10-bagger dragging laggards = variance, not skill). FAIL = the index wins
  PERMANENTLY for this decision-maker; no extensions; any future attempt needs a brand
  new charter.
- Quarterly review ritual: 30 min, fixed calendar date. Check: new announcements,
  results vs concall guidance, shareholding/pledge change, full checklist re-run, XIRR
  update, one dated journal line per name. Do NOT react to: daily prices, headlines
  without a checklist item, others' targets, market-wide moves. (Myopic loss aversion:
  more checking = worse decisions — the cadence is a bias-control, not laziness.)

## 4. Known failure modes this charter defends against

Story stocks / narrative crowding (Suzlon/Yes Bank/RPower retail-favorite pattern);
confirmation bias (checklist written before emotional investment); averaging into frauds
(Manpasand, Vakrangee — the tells predated the collapses); the disposition effect
(Shefrin-Statman 1985 — selling winners early, riding losers; only the checklist decides
exits); over-checking prices (myopic loss aversion).

## 5. Charter template (sign before first buy; editing after entry = violation)

```markdown
# CONVICTION WALL CHARTER
Signed: ______________  Date: ______________

## Capital
Ring-fenced: Rs 50,000. HARD CAP. No refills ever. Zero = experiment over.

## Holdings (frozen at entry)
| # | Symbol | Rs | Entry date | Entry price | 10-pt pass? |
|---|--------|----|------------|-------------|-------------|
| 1 |        |    |            |             | Y/N |
| 2 |        |    |            |             | Y/N |
| 3 |        |    |            |             | Y/N |
| 4 |        |    |            |             | Y/N |
| 5 |        |    |            |             | Y/N |
Names committed: ___ (3-5). CNC only, no F&O/MTF/SME: [ ]
Floors confirmed (mcap/history/ASM/pledge-trail): [ ]

## Averaging down
[ ] Never (default)
[ ] One pre-planned tranche: initial ___% / reserve ___%, deploys only if
    price -___% AND checklist fully passes AND no new money. No third. Ever.

## Selling
Thesis-break (sell, no debate): red flag trips / ROCE<bar 2yrs / unexplained
promoter-stake fall / cash-conversion collapse / guidance missed 2Q.
Price-drop alone: NEVER a trigger either way. Confirmed: [ ]

## Scoreboard
Benchmark fund: ______________. Every buy mirrored same date/amount.
2yr: informational. 3yr PASS BAR: wall XIRR >= benchmark + 5pp AND >= 3/___
names individually beat it. Not cleared => index wins permanently.

## Review
Quarterly, 30 min, on: ______________. Checklist re-run + XIRR + journal line.
Nothing checked outside the window.

Signed: ______________  Date: ______________
```

*(Full sourced research memo with all citations lives in the 2026-07-29 research agent
transcript; key sources: SEBI SAST/LODR pledge rules, SEBI Oct-2019 auditor-resignation
circular, SEBI Sept-2024 F&O study, Shefrin-Statman 1985, Coffee Can criteria,
Manpasand/Vakrangee case reporting.)*
