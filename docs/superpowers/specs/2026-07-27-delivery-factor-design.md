# Delivery-Percentage Factor — Design Spec (Pre-Registered)

Date: 2026-07-27. Status: APPROVED & FROZEN (user, 2026-07-28). No changes after this line except decision-log entries.
Origin: niche-strategy-research-brief.md §1.9. NSE publishes deliverable quantity
per stock in the daily bhavcopy — the fraction of traded volume actually taken
into demat (conviction) vs intraday churn. This field has no US equivalent and
has never been tested in this project. Recon (2026-07-27) verified the data:
`sec_bhavdata_full_DDMMYYYY.csv` downloadable from archives.nseindia.com back to
~Oct 2019 with DELIV_QTY/DELIV_PER columns (sample file fetched and inspected),
and NSE corp-actions API returns real records back to 2001.

## Hypothesis

Abnormally high delivery share on an up day marks accumulation by holders with
multi-day horizons and predicts positive near-term drift (long leg). The mirror
(abnormal delivery on a down day = distribution) is measured for information
only — multi-day cash shorts are not tradeable for us, so it carries no verdict.

## Data (frozen)

- `sec_bhavdata_full` daily CSVs, 2019-10-01 → 2026-07-24, cached under
  `data/bhavcopy_full/`. Universe built per-date FROM THE FILES (survivorship-
  free by construction; brief rule R15 — never today's constituent list).
- Per-date eligibility: series EQ, turnover ≥ Rs 2 crore (TURNOVER_LACS ≥ 200),
  close ≥ Rs 20, ≥ 20 prior eligible days for the signal window. Same liquidity
  gate as the 679-universe studies.
- Corporate actions: adjustment factors for splits/bonuses from the NSE
  corp-actions API (verified to 2001). Dividends unadjusted (uniform small
  drag, direction-neutral). Guard: daily returns clipped to ±25%; a clip firing
  on >0.1% of observations halts the run for inspection (brief rule R9/R14).

## Signal (frozen)

- abnormal delivery z: z_t = (DELIV_PER_t − mean_20d) / std_20d over the
  trailing 20 eligible days (t−20..t−1), std > 0 required.
- Accumulation signal: z_t ≥ +2.0 AND same-day close-to-close return > 0.
- Leak wall: bhavcopy for day t is published after market close of day t.
  Signals computed on day t → entry at day t+1 OPEN. Signals never touch
  same-day or future data.

## Portfolio (frozen, primary config)

- Weekly: on the last trading day of each week, rank that day's accumulation
  signals by z; long the top 20 (all of them if fewer), equal weight; enter
  next trading day's open; exit at the following week's rebalance open (names
  re-qualifying are held, not churned). Long-only cash.
- Costs: full Zerodha delivery charges via calculate_charges(is_intraday=False)
  ['total'] — includes the Rs 13.5+GST DP charge per sell — plus 0.2%/side
  slippage (wide-universe convention, deliberately harsh). Weekly turnover
  makes costs the main killer; that is the test working, not a flaw.
- Benchmark: equal-weight B&H of the same eligible universe, same gates.

## Split and verdict (frozen)

- Train: 2019-10 .. 2023-12. Validation: 2024-01 .. 2026-07.
- The factor earns further work ONLY if ALL three hold:
  1. Validation net CAGR ≥ universe B&H validation CAGR + 3pp. (The breadth
     study showed 0–4pp of "edge" is noise on this kind of sort; +3pp is the
     floor for taking it seriously.)
  2. Train net CAGR ≥ universe B&H train CAGR (no train/validation sign flip).
  3. Validation maxDD ≤ 1.25× universe B&H validation maxDD.
- Any failure → dead, recorded, no re-tuning. A pass earns an incubator
  discussion, not a deployment.

## Declared test count (multiple-testing honesty)

Three runs total, declared now: the primary above, plus two sensitivity
variants reported but carrying NO verdict weight — (a) monthly rebalance,
(b) top decile by z instead of top-20. The distribution (short-side) leg is
measured/reported as information only. Nothing else gets run; any additional
variant requires a spec amendment BEFORE it runs.

## Caveats (stated before results)

- 2019-10 start = one bull-heavy sample; validation window contains the
  2024-25 chop but no full bear market. Stated, not fixable with free data.
- DELIV_PER is a ratio computed within day t, so it is split-immune; the
  RETURN series is what needs the corp-action table.
- Delivery data starts ~Oct 2019 in the merged file; earlier price-only
  history exists but is useless for this factor.

## Build plan

1. Fetcher: polite (~1 file/sec, resume-able) archive download, ~1,700 files
   (~600MB), cookie handshake + browser UA. Background, ~45 min.
2. Corp-action adjustment table builder from the verified API.
3. Study script `kite/research/delivery_factor_study.py` under datalib
   conventions, costs via kite.config (['total'], never sum(values())).
4. Sonnet builds all three; Fable/Opus reviews every line before the run
   (leak wall, cost calls, clip-guard, universe construction are the four
   review focal points). Results appended here as a decision-log entry.

## Decision log

- 2026-07-27: Spec drafted, pending user approval to freeze.
