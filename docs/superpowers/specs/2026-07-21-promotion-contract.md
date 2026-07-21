# The October Contract — Promotion Criteria for Paper Strategies

Date drafted: 2026-07-21. Status: **FROZEN / PRE-REGISTERED.**
Companion to `2026-07-21-parity-monitor-design.md` (the monitor that produces
the evidence this contract judges).

This document is written **before any live paper track record exists.** That is
the entire point. It fixes, in advance, the arithmetic under which a strategy
now running paper-only may be moved toward real money — so that when the first
lucky month arrives (and by the base rates below, one almost certainly will),
the decision has already been made by the person who had no stake in the
outcome yet. Present-Aditya writes the rules; Future-Aditya only checks the
boxes. No box may be checked by feel.

The name: signed in July, the earliest date any strategy can accrue enough
sample to clear Gate G1 is roughly **October–November 2026** (momo needs three
monthly rebalance cycles; the swing pair needs dozens of trades at 2–5
trades/month). Nothing can be promoted before then no matter how good it looks.
This is deliberate.

---

## The roster under contract

Two virtual books, ₹1,00,000 each, paper-only since 2026-07-21. Seven
strategies, survivors of the July-2026 honest-backtest cull that falsified
130+ others.

| book | strategy | cadence | card win-rate | card max DD |
|---|---|---|---|---|
| **main** (₹1,00,000) | `momo_rotation_63` | monthly rotation | 0.4449 (n=81) | −29.0% |
| **incubator** (₹1,00,000) | `rsi_trend_confirmation` | daily-swing | 0.4758 (n=353) | −20.9% |
| incubator | `cci_divergence` | daily-swing | 0.4769 (n=174) | −13.9% |
| incubator | `choppiness_filter` | intraday | — (no card win-rate) | −15% |
| incubator | `bb_mean_reversion` | intraday | — | −15% |
| incubator | `adx_filter` | intraday | — | −15% |
| incubator | `cci_divergence_intraday` | intraday | — | −15% |

Numbers are transcribed verbatim from `kite/live_monitor/expectations/*.json`.
The four intraday cards carry **no win-rate** (their lambda and drawdown are
rough 5-stock/5-day walkforward extrapolations, not a trustworthy edge
estimate). That gap is not a rounding detail — it structurally caps how far
those four can be promoted. See G3 and §3.

---

## 1. Purpose & the temptation model

The documented, repeated human failure in this project is not a coding bug. It
is this: **promote a strategy after a lucky month, demote it after an unlucky
one, and mistake noise for information both times.** Every version of that
mistake feels like prudence in the moment ("it's clearly working now" / "it's
clearly broken now"). This contract exists to remove the discretion that the
mistake requires.

### 1.1 The base rate that makes discretion dangerous

We are running **7 strategies**. Ask the modest question: if every one of them
were a *worthless coin flip* (true win probability 0.50), how often would at
least one of them *look* hot over a ~1–2 month sample?

Model each strategy as 30 independent closed trades, win probability 0.50.
"Looks hot" = win rate strictly above 60%, i.e. ≥ 19 wins of 30.

- Per strategy: P(≥19 wins of 30 | p=0.50) = **0.1002** (≈ 10.0%).
- Across 7 independent strategies:
  P(at least one shows >60%) = 1 − (1 − 0.1002)⁷ = **0.5226 ≈ 52%.**

**Read that again.** With seven pure-noise strategies, a coin-flip portfolio,
there is a **~52% chance** that at least one of them posts a >60% win rate over
30 trades by luck alone. Slightly loosen the bar to "≥60%" (≥18 wins) and the
probability jumps to **~75%**. The lucky winner will feel like the discovery of
an edge. It will be nothing. If the promotion decision is left to judgment,
this arithmetic guarantees that judgment will eventually be handed a
compelling-looking impostor and asked to fund it.

The only defense is to fix the bar *before* seeing which strategy gets lucky,
and to set the bar high enough and the sample large enough that luck cannot
clear it. That is §2. (Full binomial arithmetic in Appendix B.)

### 1.2 What this contract is not

It is not a performance-optimizer, not a strategy-picker, and not revisable in
the heat of a drawdown. It is a ratchet: it can only ever make promotion
*harder* to reverse on a whim. Loosening is fenced by §5.

---

## 2. Promotion gates

**ALL six gates must pass. Evaluation happens only at calendar month-end (§6).**
A strategy that fails any gate is not "close" — it is not promoted, full stop,
until a later month-end where every gate passes on the record then in hand. No
gate is averaged against another. No gate is waived for a strategy that "clearly
would have passed."

### G1 — Sample floor

Minimum count of **closed live paper trades** (or cycles) before any other gate
is even read:

| strategy class | strategies | G1 floor |
|---|---|---|
| intraday | choppiness_filter, bb_mean_reversion, adx_filter, cci_divergence_intraday | **≥ 60 closed trades** |
| swing | rsi_trend_confirmation, cci_divergence | **≥ 40 closed trades** |
| rotation (main) | momo_rotation_63 | **≥ 3 completed rebalance cycles** |

Implied earliest arrival at G1 (from card lambda): intraday clears in days
(100–990 trades/month); `rsi_trend_confirmation` ≈ 7.5 months at 5.35/mo;
`cci_divergence` ≈ 15 months at 2.64/mo; momo ≈ 3 months. **Slow strategies
wait. That is a feature.**

### G2 — Parity clean

Over the **full evaluation window** for that strategy:

- **Zero unresolved RED findings** for that strategy in `parity_history.jsonl`.
  A RED that was raised and properly cleared by a human is acceptable history;
  a RED still open at month-end is an automatic G2 failure.
- The parity **win-rate check (P5)** must sit **inside the card's confidence
  band** (P5's own two-proportion z-test, not colored RED or AMBER).

> **Gate interaction (binding):** P5 only arms at **N ≥ 60 closed trades**
> (parity design §3.3). The swing G1 floor is 40. Therefore a swing strategy
> that has reached 40 trades but not 60 has **no evaluable win-rate band**, and
> G2's win-rate sub-check is "not yet satisfiable" → the strategy is **not
> promotable** until N ≥ 60. In practice the binding swing sample floor is
> `max(40, 60) = 60`. G1's 40 governs only whether the *other* gates begin to
> be read; full promotion still waits for 60. This is stated so no future
> reading can treat 40 trades as a green light.

### G3 — Performance floor

**Live paper performance over the window must clear the lower bound of its own
backtest expectation, not merely be positive.** The cards expose exactly one
performance statistic with an attached sample size, so the statistically-honest
floor is expressed on **win rate**: the live closed-trade win rate must be

&nbsp;&nbsp;&nbsp;&nbsp;**≥ card_p − 1 × SE(p),  where SE(p) = √(p(1−p)/n_backtest).**

Frozen per-strategy floors (computed from the cards; arithmetic in Appendix A):

| strategy | card p | n | SE(p) | **G3 win-rate floor** | return anchor (out-of-sample) |
|---|---|---|---|---|---|
| momo_rotation_63 | 0.4449 | 81 | 0.0552 | **≥ 39.0%** | annualized ≥ **3.5%** (validation CAGR) |
| rsi_trend_confirmation | 0.4758 | 353 | 0.0266 | **≥ 44.9%** | annualized ≥ **11.1%** (validation CAGR) |
| cci_divergence | 0.4769 | 174 | 0.0379 | **≥ 43.9%** | annualized ≥ **5.0%** (validation CAGR) |

The **return anchor** is the honest out-of-sample (validation-split) CAGR from
the source backtest (momo: `lab_results.csv`; swing pair:
`retest_results.csv`). It carries **no standard error** (the cards store no
avg-win/avg-loss, so a return SE cannot be reconstructed), so it is applied as a
**hard floor, not a statistical test**: live annualized paper return must reach
at least the weaker (validation) figure. Both the win-rate floor and the return
anchor must hold.

**The four intraday strategies — choppiness_filter, bb_mean_reversion,
adx_filter, cci_divergence_intraday:** *insufficient card data — gate defaults
to G2 parity + G4 only, promotion ceiling stays at Stage 1.* Their cards lack a
win-rate, and their walkforward return is a rough 5-stock/5-day extrapolation,
not a trustworthy edge estimate. With no credible performance floor to clear,
G3 cannot be a real test for them; they may satisfy the reduced gate set
(G1, G2-REDs-only, G4, G5, G6) but **may never advance past Stage 1** under this
contract. Promotion beyond Stage 1 for these four requires first *regenerating a
card with a real win-rate from live paper history* and a **dated amendment**
(§5) — not a discretionary call.

### G4 — Drawdown

Live max drawdown over the window must be **≤ 1.5 × the card's
`max_drawdown_pct`** (this mirrors parity P6's AMBER threshold). Frozen ceilings:

| strategy | card max DD | **G4 ceiling (1.5×)** |
|---|---|---|
| momo_rotation_63 | −29.0% | **−43.5%** |
| rsi_trend_confirmation | −20.9% | **−31.4%** |
| cci_divergence | −13.9% | **−20.9%** |
| choppiness_filter / bb_mean_reversion / adx_filter / cci_divergence_intraday | −15% | **−22.5%** |

Breaching 1.5× fails G4 (no promotion). Breaching 2.0× is a *kill* trigger (§4).

### G5 — Execution integrity

- **Zero impossible fills, ever (parity P8).** A single paper fill priced
  outside that day's candle `[low, high]` over the entire window fails G5.
  There is no tolerance and no "it was only once."
- Observed slippage drift must stay **within the assumed 0.05%** slippage
  baked into every card. Sustained slippage above assumption fails G5.

### G6 — Human confirmation

**The user confirms the promotion in writing.** No strategy is ever promoted
automatically, even with G1–G5 all green. G6 is a veto, never a rubber stamp:
the user may decline a strategy that passed every arithmetic gate. The user may
**not** approve a strategy that failed any of G1–G5. G6 can only subtract.

---

## 3. Promotion stages

Real money enters in fixed steps. **Every stage transition requires re-passing
all applicable gates (§2) on the live-money record accrued at the new stage** —
passing at paper does not pre-clear the next rung; passing at Stage 1 does not
pre-clear Stage 2.

| stage | capital ceiling | concurrency | minimum duration | entry requirement |
|---|---|---|---|---|
| **Stage 0 — Paper** | ₹0 real (₹1,00,000 virtual/book) | all 7 | — (now) | none; this is the status quo |
| **Stage 1 — First real money** | **₹25,000** | **exactly ONE strategy at a time** | **≥ 3 months** | all applicable gates green at a month-end + G6 |
| **Stage 2 — Scale** | **₹50,000** | one strategy | ≥ 3 months | **3 clean Stage-1 months** + all gates re-passed on the Stage-1 live record + G6 |

**Hard ceilings that never move on their own:**

- Only **one** strategy may hold real money at a time through Stage 1.
- **≤ 20% of total investable capital** may be committed to **all algorithmic
  trading combined, forever.** This ceiling is revisable **only upward, only by
  dated amendment (§5), and never automatically** — no performance streak, no
  matter how strong, raises it by itself.
- The four intraday strategies are **capped at Stage 1** by G3 (see above) until
  a real card is earned and amended in.

A strategy demoted to paper (§4) re-enters at **Stage 0** and must earn its way
back up from scratch; time already served at a higher stage is forfeit.

---

## 4. Demotion & kill triggers (automatic, no discretion)

These fire on the evidence, without a meeting. "Automatic" means the action is
taken first and rationalized never.

| trigger | condition | action |
|---|---|---|
| **Repeat parity pause** | Any parity RED pauses the strategy **twice within 30 days** | **Demote to paper (Stage 0).** Re-earn from scratch. |
| **Drawdown kill** | Live max DD **> 2.0 × card max_drawdown_pct** | **Kill** (momo −58.0%, rsi −41.8%, cci −27.8%, intraday −30.0%). Real money withdrawn. |
| **Sustained underperformance** | Strategy **behind its backtest band for 2 consecutive evaluation windows** | **Kill.** The edge is presumed gone, not paused. |
| **Impossible fill at real money** | Any parity P8 impossible fill while at **Stage ≥ 1** | **Immediate halt + investigation** before any further trade. A live impossible fill is a harness/broker fault, not a market event. |

Demotion and kill are **not symmetric** with promotion by design: promotion is
slow, gated, and human-confirmed; demotion is fast and mechanical. This
asymmetry is the whole safety model — the system errs toward pulling money out.

---

## 5. The anti-tampering clause

This contract is a ratchet. It resists its author.

1. **Amendments require a dated decision-log entry** at the bottom of this file
   stating what changed, why, and what data prompted it. An undated or
   unlogged change is void.
2. **Amendments take effect only at the NEXT month-end evaluation, never
   retroactively.** A change decided today cannot alter the judgment of a window
   that is already running or already closed.
3. **Loosening any gate during a drawdown is forbidden.** If any book or
   strategy under contract is currently in drawdown, no amendment may weaken any
   threshold, floor, ceiling, or sample requirement. Drawdowns are exactly when
   the temptation to loosen is strongest and exactly when loosening is banned.
4. **The contract cannot be amended in the same calendar week as an
   evaluation.** No editing the rules while holding the scorecard. Amendments
   proposed during an evaluation week wait until the following week at the
   earliest, and then take effect only at the next month-end (per clause 2).
5. Tightening a gate (raising a floor, lowering a ceiling, shortening a real-
   money exposure) is exempt from the drawdown ban but still requires clauses
   1–2 and 4. Safety may be added at any time; it may only be removed slowly,
   in the open, and never while losing.

---

## 6. Evaluation ritual

- **When:** the **first Saturday after each calendar month-end.**
- **Inputs:** the scorecard assembled from `parity_history.jsonl` plus both
  ledgers (`data/paper_trades.db` for each book: main + incubator).
- **Procedure:** for each of the 7 strategies, walk G1→G6 (or the reduced set
  for the four intraday) using the frozen numbers in §2 and Appendix A. Record
  a one-line verdict per strategy — PROMOTE / HOLD / DEMOTE / KILL, with the
  gate that decided it — in the **decision log at the bottom of this file.**
- **Discipline:** the verdict is whatever the arithmetic says. If a strategy
  looks great but fails G1 sample, the verdict is HOLD, not PROMOTE. If it looks
  ugly but no kill trigger fired, the verdict is HOLD, not KILL. The ritual
  produces a record, and the record is the memory that defeats the temptation
  model of §1.

---

## Appendix A — Frozen per-strategy numbers (transcription + arithmetic)

All source values read from `kite/live_monitor/expectations/*.json` on
2026-07-21. Win-rate floor SE(p) = √(p(1−p)/n). Return anchors from
`kite/research/lab_results.csv` (momo) and `kite/research/retest_results.csv`
(swing pair), validation split.

```
momo_rotation_63     p=0.4449 n=81   SE=0.05522  G3 floor=0.3897 -> 39.0%   G4=-43.5%  kill=-58.0%  val CAGR=3.5%  (train 5.0%)
rsi_trend_confirm.   p=0.4758 n=353  SE=0.02658  G3 floor=0.4492 -> 44.9%   G4=-31.4%  kill=-41.8%  val CAGR=11.1% (train 21.1%)
cci_divergence       p=0.4769 n=174  SE=0.03786  G3 floor=0.4390 -> 43.9%   G4=-20.9%  kill=-27.8%  val CAGR=5.0%  (train 9.3%)
choppiness_filter    no card win-rate  -> G3 defaults out; ceiling Stage 1   G4=-22.5%  kill=-30.0%
bb_mean_reversion    no card win-rate  -> G3 defaults out; ceiling Stage 1   G4=-22.5%  kill=-30.0%
adx_filter           no card win-rate  -> G3 defaults out; ceiling Stage 1   G4=-22.5%  kill=-30.0%
cci_divergence_intr. no card win-rate  -> G3 defaults out; ceiling Stage 1   G4=-22.5%  kill=-30.0%
```

Card lambdas (trades/month) for G1 timing: momo 1.227; rsi 5.348; cci 2.636;
choppiness 236.9; bb 789.6; adx 118.4; cci_intraday 987.0. Intraday lambdas are
`rough-extrapolation` quality — reason enough that G3 cannot lean on them.

## Appendix B — Base-rate arithmetic (§1.1)

Fair coin, p=0.50, n=30 trades. X = wins ~ Binomial(30, 0.5).

- ">60% of 30" ⇒ X ≥ 19.
  P(X ≥ 19) = Σ_{k=19}^{30} C(30,k) / 2³⁰ = 107,635,996 / 1,073,741,824 = **0.10024**.
- "≥60% of 30" ⇒ X ≥ 18. P(X ≥ 18) = **0.18080**.
- Family of 7 independent strategies:
  - strict >60%: 1 − (1 − 0.10024)⁷ = **0.5226**.
  - ≥60%: 1 − (1 − 0.18080)⁷ = **0.7524**.

Interpretation: worthless strategies produce hot-looking samples routinely.
The gates in §2 exist because "it posted a great month" is, by itself,
approximately zero evidence.

---

## Decision log

- 2026-07-21: Contract drafted and frozen, in advance of any live paper track
  record. Seven strategies at Stage 0. First eligible evaluation ritual: the
  first Saturday after the first calendar month-end at which any strategy
  reaches its G1 sample floor (earliest ≈ momo, ~Oct–Nov 2026). No promotions,
  no demotions — the record begins empty by design.

<!-- Append future evaluation verdicts and amendments below, dated, one entry
     per line/block. Amendments must comply with §5. -->

---

**Agreed in advance of any evidence:** ______________________________

*Present-Aditya, 2026-07-21 — binding on Future-Aditya at every month-end hereafter.*
