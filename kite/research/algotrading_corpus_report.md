# r/algotrading Corpus Mining Report

Source: `data/reddit/algotrading_submissions.ndjson` (57,455 posts, 2012-06-17 → 2026-07-29) and
`data/reddit/algotrading_top_thread_comments.ndjson` (133,347 comments, covering the top ~2,000
submissions by score, score range 2,328 → 65). Processed locally with Python (regex keyword-family
search + manual reading of the highest-scored matches). No network calls made.

Owner's project context used as the "already known" baseline: NSE cash-equities paper-trading system;
honest backtest harness with pre-registered frozen specs; known lessons already learned — lookahead
leaks, same-bar fills, survivorship bias, cost modeling (brokerage/STT/GST/DP charges, slippage tiers),
silent API caps, holiday-file traps, cluster-robust inference, multiple-testing discipline, "publication
kills edges," 137 strategies tested/failed (78 TA-indicator strategies in `kite/strategies/` plus ~15
alternative-data/event-driven studies in `docs/superpowers/specs/`), buy-and-hold undefeated.

---

## 1. Pitfall gap analysis

Method: regex keyword-family search (35 families: slippage, overfitting, walk-forward, live-vs-backtest,
paper-vs-real, latency, partial fills, survivorship, regime change, position sizing, Kelly, risk of ruin,
broker issues, data quality, transaction costs, drawdown, correlated strategies, market impact,
tick-vs-OHLC, in/out-of-sample, lookahead, multiple testing, psychological, infra/ops, capital
requirements, taxes, black swan, alpha decay, overnight/gap risk, crowding, Sharpe gaming, etc.) run
against all 133,347 comment bodies (comments are pre-filtered to the top-2,000 highest-scored threads,
so this is already a "best of" sample), ranked by comment score, then the highest-scored matching threads
were read in full (submission text + top comments).

**Top-line finding: the owner's known-pitfall list holds up well.** Lookahead bias, overfitting,
survivorship bias, and transaction-cost/slippage modeling are by a wide margin the most-discussed
failure modes in the corpus (1,855 / 1,626 / 1,593 / 753 / 444 comment hits respectively for
overfitting/drawdown/slippage/in-sample-out-of-sample/lookahead) — this is a validating result, not a
gap. The community's single most-repeated diagnostic move on a "too good to be true" backtest is,
in order: check for lookahead bias → check slippage/commissions → check overfitting/out-of-sample. That
is exactly the owner's existing discipline.

Below are the lessons that appeared with real frequency and high community endorsement (comment score)
but are **not** on the owner's known list.

1. **Paper trading systematically lies about fill quality — even after backtest fixes.**
   Thread: *"For the algotraders who have live deployment of their algorithms and are successful..."*
   (score 83, r/algotrading). Top comment (score 39): *"The hard truth about IBKR (and any broker): Paper
   trading fills are a lie. They assume infinite liquidity at your price and rarely simulate the brutal
   reality of partial fills or slippage accurately... Go live tomorrow with the absolute minimum position
   size. You will immediately find infrastructure bugs your paper account hid from you."* Corroborated
   independently in *"Lessons learned building an ML trading system that turned $5k into $200k"* (score
   653): live P&L ran at roughly 1/10th of backtest, and in a `1r0h13s` comment: *"r/algotrading lore is
   full of 'paper crushed it → live blew up' stories."*
   This is distinct from the owner's known "same-bar fills" (a backtest-engine mechanic) — it is a claim
   that even a *live* paper-trading environment (not a historical backtest) still overstates achievable
   fills, because it typically assumes your order fills at the quoted price with no queue position or
   partial-fill friction. Directly relevant to the October Contract's N≥60 paper-trade gate: passing
   paper trades may not be testing what it looks like it's testing.

2. **Position sizing / Kelly criterion / risk-of-ruin is treated as a first-class discipline, separate
   from strategy validation — and is entirely absent from the owner's known-pitfall list.**
   Threads: *"What percentage of my account should I risk per trade?"* (score 84, top comment score 50:
   "Look into the kelly criterion, this is the only correct answer"); *"My algo works, now what?"* (score
   173, top comment score 121: recommends computing Kelly criterion or Optimal-f on live trade history
   before scaling, with a quick proxy — "average trade profit % / stdev, <0.1 = meh, >0.3 = awesome");
   *"The small take profit, large stop loss dilemma"* (score 109, comment score 33: "the bigger concern
   is the risk of ruin... what happens with a Monte Carlo simulation?"). 434 comment hits on
   position-sizing generally, 205 on Kelly specifically, 30 explicit "risk of ruin" — this is a
   consistently recurring, high-conviction community norm that a strategy passing backtest/OOS tests is
   not enough; bet-sizing has its own failure mode independent of signal quality.

3. **Regime-aware validation is a specific refinement beyond a single walk-forward split.**
   Thread: *"Those of you who started Algotrading from zero..."* (score 161, top comment score 123):
   recommends tagging every backtested trade by a regime bucket (trend strength via ADX × volatility via
   rolling ATR percentile → ~9 regime combinations) rather than a plain chronological 70/30 split,
   because "the gap between backtest and real market... is mostly invisible until you're already
   invested," and 30%+ OOS degradation is the overfitting tell. This sharpens (not duplicates) the
   owner's existing walk-forward/OOS practice — the addition is stratifying results by market regime, not
   just by time.

4. **Adverse selection: a filled *passive* (limit) order is disproportionately likely to have filled
   *because* the market just moved against you.**
   Threads: *"Market Making for Idiots (Detailed)"* (score 233, comment score 21: "the big bogeyman MMs
   are scared from: adverse selection. Is the trader against me better informed than me?"); *"Out of
   sample machine learning strat - too good to be true?"* (score 108, comment score 18, listing 4 distinct
   cost components: exchange fees, spread-crossing penalty, **adverse selection**, market impact). This is
   a selection-bias mechanism distinct from a flat slippage/cost assumption — a backtest that fills limit
   orders "at the quoted price whenever price touched it" silently ignores that touches correlated with
   adverse price movement are overrepresented in the fills you'd actually get.

5. **Alpha decay from silent parallel discovery, not just publication.**
   Thread: *"״Money-Printing Machine״"* (score 221, top comment score 43): a market-making strategy that
   nailed 40% annualized for 8 months on a low-competition crypto pair "vaporized overnight" once three
   other traders independently found the same inefficiency — no publication involved. This is a distinct
   mechanism from the owner's known "publication kills edges" (which implies the edge died because it
   became public); this is edges decaying purely from unpublished, independent competitive discovery.

6. **Strategy capacity is a hard ceiling, separate from whether the edge exists.**
   Thread: *"I am convinced retail algo trading is just gambling with extra steps. Prove me wrong."*
   (score 214, top comment score 114): turned $15k→$280k over 14 months on a low-liquidity inefficiency
   that "cannot probably scale more than generating a few dozen K per month" — i.e., the strategy has a
   real, durable edge that is nonetheless capital-capped by the market's own depth, independent of
   position-sizing or cost modeling. Comment score 33 in the same thread: "you don't enter with 10k the
   same way you enter with 100k." Relevant to the October Contract's staged Rs 25k→50k capital ramp: a
   strategy validated at one size is not guaranteed to hold its edge-per-rupee at the next size.

7. **Catastrophic-loop bugs need an explicit kill switch, independent of API-cap handling.**
   Thread: *"Big loss due to coding error"* (score 137): a bug in a *safety* feature (auto-close open
   positions) running across multiple threads caused a position to open/close every minute for an entire
   volatile session, costing $40k+; top comment (score 47) draws the direct comparison to Knight Capital's
   $440M algorithmic-trading loss from an unsupervised deployment bug, calling for "a dumb-and-reliable-
   as-a-rock killswitch." This is a distinct failure mode from "silent API caps" (rate-limit blindness) —
   it's about a logic bug compounding through repeated execution with no circuit breaker.

8. **Deflated Sharpe Ratio (Bailey & López de Prado) as a concrete tool, not just "be aware of
   multiple testing."**
   Thread: *"Swing traders: how do you find and validate a genuine edge?"* (score 67, comment: "if you
   tested more than a handful of variations to land on this, your in-sample Sharpe is inflated just from
   multiple testing, even with an honest holdout. Bailey and Lopez de Prado's work on the deflated Sharpe
   ratio is worth reading... it adjusts your significance bar for how many shots you took"). The owner's
   list already has "multiple-testing discipline" as a principle; this names a specific, implementable
   statistic that operationalizes it for a Sharpe-based go/no-go decision.

9. **Cross-vendor data disagreement (e.g., differing "official close") is structural, not necessarily a
   bug to chase.**
   Thread: *"Does anyone know why data across providers varies so much?"* (score 124, top comment score
   64, from an apparent data-vendor employee): exchanges are not obligated to broadcast official
   open/close messages, and different vendors fill the gap with their own conventions — so bar-level
   mismatches between data sources are expected background noise, not automatically evidence of bad data
   on either side. Distinct from the owner's known "holiday-file trap" (a calendar-completeness issue);
   this is about the definition of a bar's price disagreeing by vendor even when both are "complete."

10. **"Beat buy-and-hold with one strategy" may be the wrong bar — the community's own stated holy grail
    is a portfolio of many small, weak, uncorrelated edges, not a single outperforming strategy.**
    Thread: *"Advice for aspiring algo-traders"* (score 596, 16-point list, point 16: "No single strategy
    works for all market conditions... [the doc continues into] holy grail of trading is running multiple
    non-correlated strategies specializing on different market conditions" — echoed independently in a
    comment on *"My first almost complete algo"* (score 106): "Don't try to perfect one strategy too
    much... instead, go for trading a lot of uncorrelated strategies at once to reduce drawdown."
    Actionable reframe: the 137 strategies the owner tested standalone-vs-buy-and-hold could instead be
    re-evaluated as a correlation-adjusted portfolio (do any subsets have low pairwise correlation even
    if each alone underperforms?) rather than only as 137 independent pass/fail checks.

11. **Live data-feed disconnects need heartbeat + reconnect logic as a distinct failure mode from
    rate-limit throttling.**
    Thread: *"RPI4 stack running 20 websockets"* (score 313, comment score 14): a Coinbase websocket
    "would just stop randomly within 8 hours" because the exchange silently drops idle connections absent
    a stay-alive signal — solved with an explicit heartbeat, separate connections per symbol group to
    isolate failure domains. Different from "silent API caps" (which is about hitting a rate limit); this
    is about a connection dying with no error at all. Most relevant once/if the owner moves beyond daily
    EOD collection to any live/intraday data stream.

12. **Empirical (not textbook) stop-loss shape: several experienced posters report wide-stop/tight-target
    (or wide-stop + time-stop) configurations backtesting and forward-testing *better* than the standard
    "cut losses short, let profits run" heuristic**, and warn that adding tight stops to an otherwise
    working system often hurts raw performance. Thread: *"The small take profit, large stop loss
    dilemma"* (score 109, several corroborating comments, one citing Marcos López de Prado's *Advances in
    Financial Machine Learning* on why tight-stop/wide-target retail behavior is what market makers are
    structurally positioned to profit from). Flagged as a hypothesis worth testing on the owner's own
    data, not gospel — the thread itself treats it as counter-intuitive and unresolved.

13. **Tax treatment of high-frequency trading is a structural cost category the owner's list doesn't
    cover at all** (the owner's cost list is brokerage/STT/GST/DP charges — all *per-trade* costs; this is
    a *loss-realization-timing* cost). Thread: *"Wash Rule Impact on Algo Trading"* (score 145): the US
    wash-sale rule can defer/disallow loss deductions on rapid re-entries into the same symbol, materially
    changing net-of-tax P&L for high-frequency strategies. **Not directly transferable** — India has no
    wash-sale rule — but the category is worth a deliberate check: India's F&O turnover-based tax-audit
    threshold (Section 44AB) and speculative-vs-business income classification for intraday equity
    trades could have analogous bite once the owner is past paper trading and the October Contract gates
    open. Flagged as a gap in the *cost taxonomy*, not a specific number to import.

14. **Calibration on timeline, not a technical pitfall but a repeated, high-conviction community norm:**
    multiple top threads (*"Advice for aspiring algo-traders,"* score 596: "Expect to spend 3-5 years
    coming up with remotely consistent/profitable method... 80% spent on strategy development"; *"After 5
    years of attempting algo trading, I quit. AMA,"* score 394; *"Why I gave up algo trading,"* score 399)
    put the median time-to-any-consistency at 4-7 years of sustained effort. Useful context given the
    owner is already at 137 tested strategies — the corpus suggests that is not yet an unusual amount of
    failed search relative to people who eventually reported success.

**Summary verdict for deliverable 1:** of ~14 identifiable candidate lessons, most are refinements or
adjacent categories to what the owner already knows (regime-tagging refines walk-forward; deflated Sharpe
operationalizes multiple-testing discipline; tax and capacity are new cost/constraint *categories* rather
than wholly new concepts). The genuinely load-bearing new items for this specific project are **#1 (paper
fills lie — directly undermines the October Contract's paper-trade gate as currently framed), #2 (Kelly /
risk-of-ruin as a missing discipline), #6 (capacity ceiling relevant to the staged capital ramp), and #7
(kill-switch requirement for logic bugs, not just API caps)**. Everything else is corroborating detail.

---

## 2. Strategy-family census

Counted by regex match against **all 57,455 submission titles** (not just the top-2,000), so this
reflects raw community mention volume, independent of the comments-coverage limit.

| Family | # posts (title match) | Avg score | Community sentiment on top threads |
|---|---:|---:|---|
| Crypto-specific | 3,334 | 9.1 | Mixed; mostly hobby-project posts, no consistent edge claims |
| Options (general) | 1,574 | 10.1 | Out of scope for owner (cash equities) |
| ML/AI | 1,068 | 18.4 | Split — high mention, but top threads are heavily caveat-laden ("ML+trading isn't a free lunch") |
| HFT/Microstructure | 777 | 13.3 | Out of scope for owner (retail can't compete on latency, community agrees) |
| Backtesting tools/frameworks | 568 | 8.5 | Neutral, tooling discussion not edge claims |
| Arbitrage (general/crypto) | 384 | 14.0 | Mostly crypto-specific, out of scope |
| Momentum/Trend | 308 | 11.8 | Mixed-positive; several live-trading updates report modest live gains |
| Pairs/Stat-arb | 261 | 17.2 | **Positive-leaning** — "Pairs Trading - A Real-World Profitable Strategy" (score 175) explicitly claims it works; second-highest avg score of any testable-for-NSE family |
| MA/EMA cross | 251 | 12.5 | Mixed — one top thread (score 135) literally asks "do really simple algorithms still work" with mixed answers |
| Scalping | 214 | 20.4 | Mostly negative once costs included — top thread by score is literally "Proof 'scalping' on volatility alone almost always fails, in just 17 lines of code" (score 206) |
| Mean reversion | 193 | 21.7 | **Positive-leaning**, highest avg score of any testable family; several "X% Sharpe" claims, though community routinely flags overfitting risk on these same posts |
| Sentiment/NLP | 133 | 14.2 | Sparse, no strong consensus either way |
| Risk parity/Portfolio opt | 76 | 26.9 | Highest avg score of all families — top thread: "At Morgan Stanley we found Simple Trading Rules Outperformed Fancy Portfolio Optimization" (score 664) — sentiment is skeptical of over-engineering, favors simplicity |
| Pattern/TA (chart patterns) | 65 | 7.6 | Low engagement, weakly negative |
| Grid trading | 62 | 12.1 | Neutral-to-negative; mostly "how to build one" tutorials, no strong live-profitability claims |
| Options Greeks/vol | 59 | 12.5 | Out of scope |
| Options-selling | 48 | 11.1 | Out of scope |
| Martingale | 21 | 3.4 | Clearly negative — lowest avg score in the census; community treats it as a well-known trap |

### Cross-reference against the owner's actual tested roster

The owner's `kite/strategies/` directory holds ~78 TA-indicator strategies (extensively covering MA/EMA
cross — GMMA, VWMA/SMA, EMA-21/55, McGinley, MA envelopes; Momentum/Trend — MACD variants, ROC, ADX/DMI,
Donchian/Turtle; Mean reversion — Bollinger mean-reversion, double-BB, RSI-centerline, stochastic;
Pattern/TA — candlesticks, Elliott wave, Fibonacci, Wyckoff, triangles; Volume — OBV, CMF, VWAP variants;
Scalping — ema_3_scalping, ema_scalping_1min, vwap_scalping), plus ~15 alternative-data/event-driven
studies in `docs/superpowers/specs/` (announcement drift, filing timing, IPO anchor-unlock, AMFI
band-crossing, bulk-buyer persistence, "zoo-silence," delivery-%, breadth/momentum rotation, short-selling
intraday). A `TradingAgents/` clone (an LLM multi-agent trading framework) is present in the repo but
appears to be an external tool pulled in, not yet run through the honest backtest harness.

**Testable-for-NSE-cash-equities families the owner has NOT tested**, per this census:

- **Pairs/stat-arb (cointegration-based pairs trading).** 261 mentions, second-highest sentiment-positive
  family after risk parity, and genuinely testable on NSE cash equities (no options/leverage required —
  just two correlated names and a spread). This is the single most notable gap: high community
  conviction it works, mechanically simple, and completely absent from the tested roster.
- **ML/AI, in the "honest backtest harness" sense.** The `TradingAgents/` clone exists but the census
  shows this is the second-most-discussed family in the whole corpus (1,068 posts) with genuinely split
  sentiment — worth running through the same frozen-spec discipline used for the other 137 rather than
  leaving it unintegrated.
- **Portfolio-level combination of already-tested strategies** (the "Risk parity/Portfolio opt" family,
  which has the single highest average score of any family in the census, 26.9, and whose top thread is
  explicitly skeptical of complexity — "simple trading rules outperformed fancy portfolio optimization").
  This isn't a new strategy family so much as a new evaluation lens: correlation-adjusted combination of
  the existing 137, addressed in gap-analysis item #10 above.
- **Sentiment/NLP as a standalone signal** (distinct from the owner's existing event-driven filing/
  announcement work, which is closer to an event study than an NLP sentiment score). Low community
  conviction (133 posts, no standout top thread), so this is a low-priority gap.
- Grid trading and Martingale are both testable in principle but the corpus's own sentiment on them is
  neutral-to-clearly-negative — not recommended as a priority given the pattern of the owner's project
  ("be skeptical of new strategy ideas by default").

---

## 3. The honest-consensus sample

Ten highest-scored threads matching "does retail algo trading actually make money" / P&L reveals / "quit
my job" framing, found via title-pattern search across all 57,455 posts (194 total candidates matched;
top 10 shown), then read in full (post + top comments by score).

1. **"6 year algo trading model delivering the goods"** (score 502) — GBPUSD support/resistance-reversal
   ML model, reports turning £10k into £550k over 5-6 years. Top comment (score 215) is from a
   self-identified data-science professional validating the general approach; other top comments probe
   retrain cadence and note forex vs. equity market differences. Rare case where the crowd's top response
   is *engaged and constructive* rather than skeptical — but note this is a currency/leverage strategy,
   not directly comparable to NSE cash equities.
2. **"1 month of trading my strategy live ( > 30% return)"** (score 474) — OP's own top comment admits the
   shown equity curve is "a bit disingenuous" because it blends several strategies tested and then
   "whittled down" after the fact (in-sample survivorship in strategy selection, acknowledged by the OP).
3. **"A 14 year-old's Take on Algorithmic Stock Trading"** (score 434) — a stock-scraper/momentum bot;
   community response is overwhelmingly encouragement-of-a-teenager rather than technical validation; the
   one substantive technical comment flags likely overfitting and asks whether parameters were backtested
   at all.
4. **"Went live with the bot!"** (score 424) — anonymous futures (ES) bot; account went $15k→$150k+→crashed
   to $30k within the same run; community reaction is a mix of excitement and pointed risk-sizing
   questions once the drawdown became visible.
5. **"3 months of live trading with proof"** (score 401) — forex bot, +13% over 3 months, ~100 trades; OP
   explicitly hedges ("too early to declare victory"); the second-highest comment (score 107) is a
   cautionary parallel from someone who had a similar multi-month live success streak that "started
   losing out of nowhere" during a low-liquidity summer despite years of backtesting.
6. **"Why I gave up algo trading"** (score 399) — the most methodologically detailed failure post in the
   sample: an ML model showing 1000%/yr turned out to be implicitly selecting illiquid low-volume names
   with wide bid-ask spreads (a universe-selection/survivorship trap); fixed to point-in-time S&P 500
   membership, it still eventually broke down out-of-sample around 2013 due to regime change. Top comment:
   *"You didn't give up algotrading, you gave up backtesting."*
7. **"After 5 years of attempting algo trading, I quit. AMA"** (score 394) — anonymized long-form
   retrospective; top comments reference a backtest bug that spuriously produced 3,000% yearly returns,
   advise against writing everything from scratch/unorganized code, and note a university trading-ML
   course of 800 students where the professor's own punchline is "ML+trading isn't a free lunch."
8. **"after written hundreds of failed algos, i may finally found one which works!"** (score 304) — shows
   $1.2M losses / $1.3M profits (net positive); community immediately identifies the backtest window as
   covering a major bull run and that the strategy loses money on the short side — verdict is "not
   validated yet."
9. **"My experience after over 10 years of manual trading and 4 years of algo trading"** (score 302) — the
   OP's own bullet-point lessons: no single algo is "the" one; transaction costs/slippage/spread "kill
   your backtest results" once live; backtesting can't see inside the candle/timeframe so forward and
   live testing are necessary; latency under 10 seconds is explicitly called out as the "second most
   important task" after minimizing operational costs.
10. **"Full 2 year Data on Algorithm trading"** (score 293) — textbook AI-generated-sounding "money
    printing machine" post claiming a 2,690% annual return; community response is immediate and
    unanimous skepticism — top comment (174) demands to know if it's backtest or live, second comment
    (109) methodically debunks the claim as mathematically impossible for even the largest hedge funds
    combined, third comment flags it as reading like an LLM-generated sales pitch.

**What the community's own top-voted answers conclude, in aggregate:** the single most-upvoted response
in nearly every high-visibility "success" thread in this sample is a demand for proof or an identification
of a specific overlooked flaw — not encouragement, and not blanket dismissal either. Even the two
genuinely modest, restrained live results in the top 10 (#5's 13%/3mo, #2's >30%/1mo) draw immediate
warnings from people who had similar early success that later reversed. The detailed "I quit" posts (#6,
#7) attribute failure to specific, correctable research-methodology mistakes (universe-selection bias,
regime change, code-quality/backtest bugs) rather than to "the market is efficient, don't bother." No
thread in the top 10 asserts retail algo trading is flatly impossible; the recurring qualified verdict is
closer to: modest, inconsistent returns are achievable for some, after a multi-year methodology-hardening
process, and any claim of large, smooth, consistent returns is treated by the community as near-certainly
fake or about to blow up. This is a **validating finding** for the owner's project posture (skeptical
default, demand for out-of-sample evidence, buy-and-hold as the honest bar) rather than a new lesson.
