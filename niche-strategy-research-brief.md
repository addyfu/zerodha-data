# Niche Trading Strategy Research Brief

**Purpose:** hand this file to Claude Code as the source-of-truth spec for a backtesting research project.
**Scope:** Part 1 covers India-specific structural strategies (primary focus). Part 2 covers global/US niche anomalies. Part 3 is the mandatory guardrails block. Part 4 is data and tooling.

**How to use this with Claude Code:** do not let the agent start coding from a strategy summary in this file. For each strategy, make it fetch the linked source first, write a dossier card quoting the source's own definitions of universe, signal and screens, and only then generate backtest code. The reasoning for that rule is in Part 3.

**Disclaimer:** this is research material, not investment advice. Every effect listed here may be dead, may never have existed, or may be untradeable after costs. The base rate for published anomalies surviving out-of-sample is poor. Treat a negative result as a successful outcome.

---

# PART 1: INDIA-SPECIFIC STRATEGIES

## 1.0 Regime breaks (hardcode these as dummies before anything else)

Any Indian backtest spanning these dates without a regime split is averaging two different markets.

| Date | Change | Impact |
|---|---|---|
| 2025-09-01 | SEBI standardised derivative expiry to Tuesday (NSE) or Thursday (BSE); ended 25 years of Thursday expiry | Breaks every day-of-week, expiry-week and expiry-day study |
| 2025-09-01 | Weekly expiries retained only for Nifty 50; Bank Nifty, Fin Nifty, Midcap Nifty restricted to monthly/quarterly | Bank Nifty weekly options history simply ends |
| 2025-12-08 | MWPL open interest moved from lot-count to delta-based Future Equivalent OI, checked 4 random times intraday instead of day-end only | Changes which stocks enter the F&O ban list and when |
| 2024 onward | SEBI revised F&O contract sizes / lot sizes | Per-lot P&L needs a point-in-time lot size table |

Sources:
- Expiry restructuring: https://www.venturasecurities.com/blog/changes-in-expiry-nse-and-bse/
- Expiry circular summary: https://hdfcsky.com/blogs/share-market/revision-of-nse-and-bse-expiry-day-of-derivatives-contracts
- Current 2026 expiry schedule: https://www.sahi.com/blogs/nse-vs-bse-expiry-shake-up-what-traders
- MWPL delta-based OI change: https://www.angelone.in/announcements/market/position-limits-for-stocks-in-ban-period-for-fo-segment-w-e-f-december-8-2025

---

## 1.1 F&O ban list as a forced-deleveraging event study

**Priority: BUILD FIRST**

**Mechanism.** A stock enters the ban when total market exposure crosses 95% of its Market Wide Position Limit. It exits only when exposure falls below 80%. During the ban, no participant may open fresh futures or options positions; only squaring off is allowed. The cash market remains completely unrestricted. This is a hard, published, exogenous limit-to-arbitrage event with no equivalent in US markets.

**Hypotheses to test:**
- H1: Cash-market abnormal returns over the ban window differ from matched non-ban periods, because hedgers who cannot use derivatives adjust cash holdings instead.
- H2: Ban-exit day shows a distinct return as the constraint releases and fresh positions reopen.
- H3: The effect is conditional on direction of the OI build (long-heavy vs short-heavy at entry).

**Signal spec:**
- Universe: all NSE F&O-eligible stocks
- Entry event: first day stock appears on NSE Clearing ban list
- Exit event: first day it drops off
- Return measurement: cash-market close-to-close, market-adjusted vs Nifty 50, plus a matched-sample control on stocks at 60 to 90% MWPL utilisation that never crossed 95%

**Data:** NSE daily ban list + daily MWPL/OI report. Free, published before each session.

**Known trap:** the Dec 2025 delta-based OI methodology change means the ban population before and after that date is not the same population. Split the sample.

Sources:
- Mechanism and thresholds: https://support.zerodha.com/category/trading-and-markets/trading-faqs/f-otrading/articles/why-do-futures-and-option-scrips-enter-ban-period-what-does-it-mean
- Cash-market spillover reasoning: https://www.stockezee.com/ban-list
- Alert zone at 60% MWPL: https://www.stockezee.com/ban-list

---

## 1.2 MWPL utilisation as a continuous crowding factor

**Priority: BUILD FIRST**

**Mechanism.** Instead of the binary ban, use MWPL utilisation percentage as a cross-sectional signal. This is effectively a published daily leverage-crowding metric per stock, which does not exist in most markets. Nobody sorts on it.

**Signal spec:**
- Compute daily MWPL utilisation % for every F&O stock
- Rank cross-sectionally, form quintiles, rebalance weekly
- Test both directions: crowding as a reversal signal (high utilisation predicts negative forward returns) and as a momentum-continuation signal
- Control for own-stock momentum, size and realised volatility, since utilisation will correlate with all three

**Data:** NSE daily MWPL report (aggregate OI vs limit per scrip).

**Known trap:** MWPL is computed from free-float and turnover, so the denominator changes over time. Use point-in-time MWPL, not a current snapshot.

---

## 1.3 Short-term ASM inclusion as a short signal

**Priority: BUILD FIRST**

**Mechanism.** SEBI/exchange surveillance places stocks under Additional Surveillance Measure based on objective price/volume/concentration parameters. Published academic event study on 245 ASM instances found cumulative abnormal returns declined after inclusion into short-term ASM **and stayed depressed after exclusion**, while abnormal volume changed significantly around the event. The persistence after the constraint is removed is the interesting part, since it suggests something beyond a purely mechanical margin effect.

**Signal spec:**
- Event: addition to ST-ASM list (NSE ASM reports)
- Windows: [-10, -1], [0, +5], [+6, +30], and a post-exclusion window
- Metric: CAR vs Nifty 500, plus abnormal volume
- Separate ST-ASM from LT-ASM, ESM and GSM. These are different frameworks with different criteria and different restrictions.

**Data:** https://www.nseindia.com/reports/asm/ (free)

**Known trap (critical):** surveillance stages impose real execution constraints. ESM Stage I means 100% margin, trade-to-trade settlement and a 5% or 2% price band. GSM Stage III restricts trading to once a week with a 100% additional surveillance deposit from the buyer. A short strategy on these names is frequently not executable at all. Model borrow availability and T2T restrictions or the backtest is fiction.

Sources:
- Event study (245 instances): https://ideas.repec.org/a/wsi/rpbfmp/v27y2024i01ns0219091524500048.html
- Related empirical study PDF: https://www.stern.nyu.edu/sites/default/files/2023-01/Chari%20Inamdar%20-%20Effectiveness%20of%20Additional%20Surveillance%20Measures--Empirical%20Study%20Using%20Indian%20Market%20Data.pdf
- Surveillance stage restrictions: https://www.kotaksecurities.com/investing-guide/articles/sebis-new-surveillance-measures/

---

## 1.4 Cross-exchange expiry structure (NSE Tuesday vs BSE Thursday)

**Mechanism.** Since Sept 2025, NSE and BSE expire on different days, creating distinct liquidity windows across Monday to Thursday. NSE traders get Friday, Monday and Tuesday sessions before expiry, so the theta decay profile is structurally different from BSE's compressed Wednesday-Thursday window.

**Hypotheses:**
- H1: Implied vol on the non-expiring exchange systematically misprices the realised expiry-day move on the other.
- H2: Nifty vs Sensex realised vol shows a repeatable day-of-week pattern post-Sept-2025 that did not exist before.
- H3: The Monday-before-NSE-expiry session has a distinct return/vol signature.

**Data:** NSE and BSE F&O bhavcopy, both exchanges, Sept 2025 onward only.

**Known trap:** BSE derivatives liquidity is materially lower than NSE. Any cross-exchange trade will be constrained by the BSE leg. Model wide spreads on the BSE side or the result is meaningless. Sample is short (under a year of post-regime data as of mid-2026), so statistical power is low. State that explicitly rather than reporting a t-stat as if the sample were long.

Source: https://www.arihantplus.com/blogs/market-updates/tuesday-is-the-new-thursday-nse-and-bse-expiry-shift-from-sep-2025/

---

## 1.5 Nifty reconstitution: fade the move rather than front-run it

**Mechanism.** Standard view is that additions pop on forced passive buying. The less-crowded finding is regional: in Asia ex-Japan and Europe, upweighted and downweighted stocks typically show **rapid mean reversion** after the rebalance, indicating the initial move is temporary liquidity pressure rather than fundamental repricing. In the US and Japan the move partly persists. India sits in the mean-reverting group.

**Signal spec:**
- Events: NSE Indices semi-annual reviews (Nifty 50, Nifty Next 50, Nifty 500, Midcap 150)
- Three windows: announcement to effective date, effective date close (passive execution happens in the closing auction), and effective+1 to effective+20
- Trade: long the deletions and short the additions starting at the effective-date close, hold 10 to 20 sessions
- Control: separate index-level events (Nifty 50) from broad-index events (Nifty 500), since passive AUM tracking differs enormously

**Event count:** the March 2026 review changed 31 Nifty 500 constituents and 16 Midcap 150 constituents (10.7% churn), so there is enough event density over 10 years for a real sample.

**Known trap:** the announcement-to-effective window is heavily traded already. Prior research shows stocks targeted by hedge fund arbitrage around index changes outperformed peers by 0.86% per month *before* the event. Do not claim novelty on that leg.

Sources:
- Regional mean-reversion evidence and closing-auction impact: https://www.eastspring.com/insights/deep-dives/navigating-index-rebalancing-effects-key-insights-for-smarter-execution
- India-specific institutional ownership study: https://www.sciencedirect.com/science/article/abs/pii/S1042444X20300049
- March 2026 rebalance stats: https://insights.dsij.in/dsijarticledetail/index-inclusion-and-exclusion-why-getting-added-to-nifty-moves-a-stock-more-than-its-quarterly-numbers-id010-56121
- Inclusion rules and mechanics: https://www.equityresearchindia.com/post/index-rebalancing-explained-why-stocks-get-added-to-or-dropped-from-the-nifty

---

## 1.6 Free-float (IWF) changes, not just additions and deletions

**Mechanism.** Almost nobody trades this. A 5% increase in the investable weight factor of a large index constituent can trigger larger passive flows than the inclusion of a small stock. Multiple IWF changes across constituents can reshape index composition significantly, and the required flow is mechanically computable from tracked AUM.

**Signal spec:**
- Event: published IWF revision for any Nifty 50 / Next 50 constituent
- Compute expected flow = (delta weight) x (estimated passive AUM tracking that index)
- Sort events by expected flow as % of the stock's 20-day ADV
- Test return over announcement-to-effective and effective+1 to +10

**Data:** NSE Indices methodology documents and periodic index maintenance announcements.

Source: https://www.gwcindia.in/blog/why-free-float-adjustments-matter-in-index-rebalancing/

---

## 1.7 Predict the inclusion before it is announced

**Mechanism.** NSE Indices applies a fixed, published checklist using the preceding six months of data, including an impact-cost rule benchmarked at a Rs 10 crore order. Encode the rules, run them monthly over the Nifty Next 50 and broader universe, and rank inclusion probability ahead of the semi-annual review.

**Signal spec:**
- Recompute eligibility monthly: free-float market cap rank, average impact cost at Rs 10 crore, trading frequency, F&O eligibility
- Output a ranked candidate list before each review announcement
- Backtest: buy top-3 predicted inclusions 30 days before announcement, exit at effective date

**Known trap:** the index committee applies qualitative judgement (governance, sector representation) on top of the quantitative screen, so the rules alone will not perfectly predict. Measure hit rate honestly.

Source: https://www.equityresearchindia.com/post/index-rebalancing-explained-why-stocks-get-added-to-or-dropped-from-the-nifty

---

## 1.8 Participant-flow divergence (FII vs DII), not flow level

**Mechanism.** Everyone looks at the FII number. The untraditional framing is the divergence regime: FII selling absorbed by DII buying is a structurally different state from both selling together. NSE publishes provisional FII/DII cash data after 6pm IST daily, final figures next morning; NSDL publishes a separate FPI figure that additionally includes primary market flows.

**Signal spec:**
- State variable: sign(FII net) x sign(DII net), giving four regimes
- Add magnitude: z-score each flow against its trailing 90-day distribution
- Add FII F&O positioning from NSE participant-wise open interest (index futures long/short ratio) as a second dimension
- Test: forward 1/5/20-day Nifty returns conditional on regime; also test sector-level returns, since foreign ownership concentration differs sharply by sector

**Secondary idea:** AMFI publishes the monthly SIP collection figure. DII inflows are now largely retail SIP money. Condition India's turn-of-month effect on the SIP number. That converts a calendar anomaly into a mechanism test, which is much harder to overfit.

**Known trap:** practitioner consensus (and the shape of the data) is that single-day flow is noise and consecutive-session streaks carry more signal. Do not build a one-day flow signal and expect it to work.

Sources:
- Data release timing and NSDL vs NSE distinction: https://www.sahi.com/blogs/fii-dii-data-meaning-how-to-read
- Streak vs single-session evidence: https://www.niftytrader.in/markets/how-to-read-fii-dii-data-report-guide/

---

## 1.9 Delivery percentage as a cross-sectional factor

**Mechanism.** NSE publishes daily deliverable quantity per stock in the bhavcopy. Delivery percentage separates conviction accumulation from intraday churn. This field does not exist in US data and is almost never used as a systematic factor.

**Signal spec:**
- Factor: (delivery % today) minus (trailing 20-day mean delivery %), i.e. an abnormal-delivery z-score
- Interact with same-day return sign: high abnormal delivery + positive return = accumulation; high abnormal delivery + negative return = distribution
- Cross-sectional decile sort, weekly rebalance
- Control for volume shock, since abnormal delivery correlates with abnormal volume

**Data:** NSE equity bhavcopy (includes DELIV_QTY and DELIV_PER fields in the security-wise delivery file).

---

## 1.10 Monsoon conditioning (not calendar-based)

**Mechanism.** The Indian literature has a weak "monsoon effect" as a calendar anomaly. The stronger version discards the calendar entirely and uses actual IMD data as a state variable for rural-exposed sectors.

**Signal spec:**
- State variable: IMD cumulative rainfall departure-from-normal, and revisions to the seasonal forecast
- Long basket: tractors, two-wheelers, fertilisers, agri-inputs, rural-skewed FMCG
- Short basket: urban-skewed discretionary
- Rebalance on forecast revision dates plus weekly during June to September

**Data:** IMD publishes rainfall and forecast data free. Sector constituents from NSE sector indices.

**Known trap:** small number of independent monsoon seasons. Twenty years gives you twenty observations. This is a low-power test by construction. Say so in the report.

Source (calendar version, for reference only): https://www.abacademies.org/articles/calendar-anomalies-in-the-indian-stock-markets-monsoon-effect-8015.html

---

## 1.11 Domestic macro event drift (RBI MPC, Union Budget)

**Mechanism.** The India analogue to US pre-FOMC drift. Critically, the European version of this effect sits the day *before* the announcement, because of session timing relative to the announcement hour. Test the day-before window explicitly for RBI MPC, not just the announcement day.

**Signal spec:**
- Events: scheduled RBI MPC announcement dates (published in advance by RBI), Union Budget day (Feb 1 in recent years)
- Windows: T-2, T-1, T-0 intraday (pre-announcement vs post-announcement), T+1
- Instruments: Nifty 50, Bank Nifty, and India VIX for the vol-crush leg

**Known trap:** MPC dates were not always on the current bi-monthly schedule. Pull the actual historical announcement calendar rather than assuming a fixed cadence.

Reference for the day-before logic: https://quantpedia.com/uncovering-the-pre-ecb-drift-and-its-trading-strategy-applications/

---

## 1.12 Expiry-day settlement dislocation (STUDY ONLY, DO NOT REPLICATE)

**Why this matters for research.** SEBI's July 3, 2025 interim order against Jane Street is regulatory confirmation that Indian index settlement prices are dislocatable. The order found that across 18 expiry days between Jan 2023 and Mar 2025, trades distorted index levels to benefit large options positions, and directed a deposit of Rs 4,843.57 crore. The documented pattern was aggressive buying of constituents and futures in the morning to lift the index, then reversal from around 11:49am to press it into the expiry close.

**What is legitimate to research from this:**
- Expiry-day cash-futures basis convergence behaviour and whether it is predictable
- Whether index closing auction prices on expiry days show systematic deviation from a VWAP-based fair value
- Whether that deviation has changed after the Sept 2025 expiry restructuring and increased surveillance

**What is not:** anything that takes directional positions in index constituents with the purpose of moving a settlement price. That is PFUTP territory, it is now actively surveilled with forensic cross-market analytics, and it is not a strategy to backtest. Study the dislocation passively.

Sources:
- Oxford Business Law Blog analysis: https://blogs.law.ox.ac.uk/oblb/blog-post/2025/07/jane-street-and-expiry-day-trap-unpacking-sebis-crackdown-algorithmic
- ECGI analysis: https://www.ecgi.global/publications/blog/expiry-day-and-the-governance-of-algorithmic-trading-the-jane-street-episode

---

## 1.13 Indian calendar anomalies: use as a control group, not a strategy

The published Indian calendar-effect literature contradicts itself badly. Across papers you will find: a Monday effect with lowest returns Monday and highest Wednesday; negative Tuesday returns with higher Monday returns; a Friday effect; a January effect; a March effect; an April/December effect; and a November/December effect. That distribution of findings is what a non-existent effect looks like when many researchers test it on overlapping data.

**Use it this way:** run all of them, count how many clear t > 2, and compare against what pure multiple testing would produce. That calibrates the significance hurdle for the real strategies above. Do not trade it.

Sources:
- NSE's own research paper on seasonality: https://nsearchives.nseindia.com/content/research/res_paper_final228.pdf
- Survey of contradictory findings: https://www.researchgate.net/publication/315088292_SEASONALITY_AND_MARKET_CRASHES_IN_INDIAN_STOCK_MARKETS

---

# PART 2: GLOBAL / US NICHE STRATEGIES

## 2.1 Calendar and microstructure

**Overnight vs intraday decomposition.** Short-term reversal is attributable almost entirely to past *intraday* returns; overnight returns do not reverse in the following week. The reversal is stronger for illiquid stocks and in volatile markets, and is unaffected by fundamental news, supporting a liquidity-provision explanation rather than an information one. Most retail backtests never split close-to-open from open-to-close.
- https://quantpedia.com/strategies/short-term-reversal-in-stocks

**Pre-ECB drift.** European equities drift up the day *before* the ECB press conference, because the ECB speaks at 14:15 CET, before US markets open, so investors front-run the signal. Less crowded than the US pre-FOMC version.
- https://quantpedia.com/uncovering-the-pre-ecb-drift-and-its-trading-strategy-applications/

**Option expiration week.** Large caps with actively traded options averaged 0.45% in expiration weeks vs 0.12% in other weeks over 1996-2008, strongest where the option/stock volume ratio is high.
- https://www.cxoadvisory.com/calendar-effects/option-expiration-week-stock-return-drill-down/
- https://quantpedia.com/strategies/option-expiration-week-effect
- Backtest notes and SPY implementation caveats: https://www.quantifiedstrategies.com/the-option-expiration-week-effect/

**Expiration-driven option return anomalies.** More than half of monthly option anomaly returns occur inside the two-day expiration window, driven by roll-over order imbalances overwhelming market makers' risk-bearing capacity. Particularly pronounced for S&P 500 names.
- https://harbourfrontquant.substack.com/p/expiration-effects-and-return-anomalies

**Payday anomaly.** The 16th of the month outperforms all calendar days except the 1st and 2nd, weakening as employers shift to biweekly pay.
- https://quantpedia.com/strategies/payday-anomaly

**Overnight reversal in high-yield bond ETFs.** Liquid ETFs holding illiquid bonds: overnight returns systematically exceed intraday, concentrated Monday close to Tuesday open and Tuesday close to Wednesday open, and stronger following a negative prior close-to-close.
- https://quantpedia.com/overnight-reversal-effects-in-the-high-yield-market/

**Niche alternative ETF reversal.** Managed futures, merger arb and option-income ETFs are liquid wrappers around hard-to-price underlyings, so price/NAV dislocations create short-term reversal setups. The source itself flags that low liquidity, intraday noise on EOD data, and transaction costs eat much of it.
- https://quantpedia.com/evaluating-reversal-potential-in-niche-alternative-etfs/

**Other documented seasonality with named papers:** turn-of-the-month (Xu and McConnell), Treasury auction cycle (Lou et al. 2013), GSCI annual commodity index rebalance (Yan et al. 2019), FOMC and the US dollar (Mueller et al. 2014).
- Overview: https://quantpedia.com/are-there-seasonal-intraday-or-overnight-anomalies-in-bitcoin/

## 2.2 Cross-sectional and network signals

**Customer-supplier momentum spillover.** Buy the supplier after a positive shock to its customer. Survives controls for three-factor, liquidity, own-firm momentum, industry momentum, within-industry lead-lag and cross-industry momentum.
- https://www.aqr.com/Insights/Research/Journal-Article/Economic-Links-and-Predictable-Returns
- **Critical robustness check:** restricting to links with the smallest customer-to-supplier size ratio cuts the effect by 2-4x, and adding a relative-size interaction term to Fama-MacBeth regressions flips the sign. Replicate this check before believing any result. https://arxiv.org/pdf/2301.11394

**Other linkage types.** Documented spillover via industry, geographic, technology, news-implied, concept and analyst co-coverage links. In the US, analyst co-coverage subsumes the others.
- Cross-market comparison and full linkage taxonomy: https://www.sciencedirect.com/science/article/abs/pii/S037842662400270X
- Overnight/intraday decomposition of spillover: https://www.cambridge.org/core/journals/journal-of-financial-and-quantitative-analysis/article/decoding-momentum-spillover-effects/EB6BE5A096753108881E1514E54035DF

**EDGAR co-search relatedness.** Firms co-searched on SEC EDGAR predict each other's returns, and this factor explains returns based on shared analyst coverage. Free data.
- https://quantpedia.com/oh-my-i-bought-a-wrong-stock-investigation-of-lead-lag-effect-in-easily-mistyped-tickers/

**Network momentum across asset classes.** Extends spillover beyond equities to 64 continuous futures contracts across commodities, equities, bonds and FX.
- https://ar5iv.labs.arxiv.org/html/2308.11294

**Microcap insider buying.** 17,237 Form 4 open-market purchases, $30M-$500M caps, 2018-2024. Gradient boosting achieves 0.70 AUC on out-of-sample 2024 data. Distance from the 52-week high alone accounts for 36% of feature importance. Purchases disclosed after >10% prior appreciation give the highest mean CAR (6.3%).
- https://arxiv.org/pdf/2602.06198

**Vol spread with turnover correction.** Abnormal turnover contaminates the realized-minus-implied vol spread as a variance risk premium proxy. Applying a mean-reversion correction to realized volatility raises returns to equity VRP strategies by about 42% on average.
- https://papers.ssrn.com/sol3/papers.cfm?abstract_id=5234112

## 2.3 The nine-anomaly replication set (use as benchmarks / negative controls)

These were replicated on clean survivorship-free data 1998-2025 and **none survived out-of-sample**. Use them to validate your harness: if your pipeline reports a strong out-of-sample edge on any of these, your pipeline has a bug.

1. Hill, *RSI for Trend-Following and Momentum Strategies* (2019): https://papers.ssrn.com/sol3/papers.cfm?abstract_id=3412429
2. Zhu, Sun & Stivers, *Price Anchors and Short-Term Reversals* (2021): https://ssrn.com/abstract=3092325
3. Bali, Cakici & Whitelaw, *Maxing Out: Stocks as Lotteries* (2011): https://www.nber.org/papers/w14804
4. Frazzini & Pedersen, *Betting Against Beta* (2014): http://pages.stern.nyu.edu/~lpederse/papers/BettingAgainstBeta.pdf
5. Arendarski, *Tactical Allocation in Falling Stocks* (2012): http://www.wne.uw.edu.pl/inf/wyd/WP/WNE_WP67.pdf
6. Rodon Comas, *Winners & Losers in Motion* (2025): https://papers.ssrn.com/sol3/papers.cfm?abstract_id=5130289
7. Chen, *Persistency of the Momentum Effect* (2016): https://papers.ssrn.com/sol3/papers.cfm?abstract_id=2652592
8. Heston & Sadka, *Seasonality in the Cross-Section of Expected Stock Returns* (2008): https://papers.ssrn.com/sol3/papers.cfm?abstract_id=687022
9. Geertsema & Lu, *Revisiting the Price Effect in US Stocks*: https://papers.ssrn.com/sol3/papers.cfm?abstract_id=4013958

Full write-up of the replication and every failure mode: https://quantpedia.com/guardrails-make-the-researcher-what-an-ai-agent-got-right-and-wrong-replicating-nine-equity-anomalies/

Post-publication decay literature: https://papers.ssrn.com/sol3/papers.cfm?abstract_id=2156623

---

# PART 3: GUARDRAILS (paste this section into CLAUDE.md)

Every rule below corresponds to a documented failure of an autonomous agent doing exactly this task. Source: https://quantpedia.com/guardrails-make-the-researcher-what-an-ai-agent-got-right-and-wrong-replicating-nine-equity-anomalies/

## 3.1 Process rules

**R1. Dossier card before code.** For every paper or source, first write a card that quotes verbatim the source's own definition of universe, signal, screens and rebalance schedule. Check the extracted spec against those quotes. Do not write a line of backtest code before this exists.
*Why:* the agent built a momentum strategy from a paper that was explicitly contrarian, and applied a $5 price floor where the paper specified $0.50, which would have removed most of the names the strategy was about. It can read fast, but it cannot trade a paraphrase.

**R2. Two independent review passes.**
- *Code-fidelity pass:* re-read generated code against the spec. Check assets, entry/exit logic, rebalance schedule, fees, lookback off-by-one, rebalance day.
- *Execution-fidelity pass:* ignore the code entirely, read the trade log. Check actual fills, trade counts vs stated schedule, fill times, failed data requests, error log.
*Why:* trade-log review caught bugs code review cannot see. A universe refresh scheduled at year-start traded nothing for a full year because the schedule skipped the start date. A 500-name daily rebalance generated orders in the millions before being gated to month-rolls and active-set changes, cutting it to ~20,000 over 26 years.

**R3. Recompute all statistics from the equity curve.** Never trust the engine's headline Sharpe, return or drawdown. Use one stated convention throughout.

**R4. Re-run every promising result on a second, independent engine before believing it.**

**R5. If any check flags a major deviation, the strategy goes back for a fix and a full re-run.** Do not patch and report.

## 3.2 Data rules

**R6. As-traded prices for any level-based signal.** Never sort on retroactively split-adjusted prices. In the replication, the same low-minus-high-price long/short compounded to roughly 500x on split-adjusted prices and decayed toward zero on as-traded prices, about 3.5 Sharpe points of pure illusion, because a low split-adjusted price quietly flags a stock that will split, which is typically a past winner. Applies to: 52-week-high proximity, RSI, nominal price, any signal computed on price levels.

**R7. Survivorship-free universe.** Retain delisted names so the strategy only ever holds names that were actually listed on the formation date.

**R8. Point-in-time everything.** Index membership, fundamentals, MWPL limits, lot sizes, index weights, sector classifications. If it changes over time and you used today's value, the result is fiction.

**R9. Stale-price and liquidity screen on every broad-universe sort, plus a single-month outlier scan on every return series.** In the replication, one halted micro-cap with a frozen price followed by a corrupt print produced a +76% month and inflated a 27-year curve from ~16x to ~38x. Worse, low-volatility sorts select frozen prices *on purpose*, because a frozen price looks like the calmest stock in the cross-section.

**R10. Pre-filter the universe to names with real price history** before requesting data, or delisted-but-still-in-snapshot names will hard-fail their data requests.

## 3.3 Tradeability and cost rules

**R11. Cost-stress every candidate on its measured turnover and report a break-even cost.** A market-neutral reversal book can run ~2,200% annual turnover and look superb at flat paper-comparison costs, then become ordinary under liquidity-tiered costs with borrow on the short leg. A Sharpe that exists only at zero cost is not a result.

**R12. India-specific cost model.** Model STT, stamp duty, exchange transaction charges, GST and SEBI turnover fees as separate line items. STT on exercised in-the-money options is a distinct and frequently decisive cost for expiry strategies. Fetch current rates rather than hardcoding from memory; they have been revised multiple times.

**R13. India-specific execution constraints.**
- Circuit filters: a stock locked at upper or lower circuit is not tradeable at that price. Fill logic must reject entries on circuit-locked bars.
- Trade-to-trade segment: no intraday netting, delivery-only.
- Surveillance stages: ESM Stage I imposes 100% margin, T2T and a 5%/2% band; GSM Stage III restricts trading to once a week with a 100% additional surveillance deposit. Any strategy touching small caps must model whether the position was enterable at all.
- Short selling: intraday only for most retail participants in the cash segment. A "short" leg in an equity backtest usually needs to be a futures or options position, with its own margin and availability constraints.

**R14. Bhavcopy prices are not adjusted for splits, bonuses or dividends.** Build a point-in-time corporate-action adjustment table. This is the Indian version of R6 and it is the single most common India backtest bug.

**R15. Symbol churn.** NSE symbols change on mergers and renames, and delisted names disappear from current lists. Build the universe from historical bhavcopy files, never from today's constituent list.

## 3.4 Statistical rules

**R16. Use a multiple-testing hurdle, not t > 2.** In the replication, only one of nine anomalies cleared t > 3 even in-sample. Out-of-sample none cleared either bar. Apply the Harvey, Liu & Zhu style hurdle and state the number of strategies tested.

**R17. Report probabilistic / deflated Sharpe.** The standard Sharpe ratio assumes Gaussian returns. Compute PSR accounting for skew and kurtosis.
- Deflated Sharpe and backtest overfitting: https://sdm.lbl.gov/oapapers/ssrn-id2507040-bailey.pdf
- Backtesting protocol checklist: https://people.duke.edu/~charvey/Research/Published_Papers/SSRN-id3275654.pdf

**R18. State sample power honestly.** Post-Sept-2025 India strategies have under a year of data. Twenty years of monsoons is twenty observations. Report the effective N, not just the daily observation count.

**R19. A negative result is a successful run.** Do not iterate parameters until something works. Log every variant tested and include the count in the multiple-testing correction.

---

# PART 4: DATA AND TOOLING

## 4.1 India data

| Source | What | Cost | Link |
|---|---|---|---|
| jugaad-data | `bhavcopy_save`, `bhavcopy_fo_save`, `stock_df`, NSELive. Best Python entry point. | Free | https://github.com/jugaad-py/jugaad-data |
| OpenChart | NSE + NFO intraday (5m) and EOD historical | Free | https://www.marketcalls.in/python/introducing-openchart-a-python-library-for-nse-and-nfo-historical-data.html |
| NSE bhavcopy archives | Ground truth. F&O bhavcopy has strike-wise settle price, OI, volume for every active contract, going back years. Script date-by-date downloads. | Free | https://www.nseindia.com |
| NSE ASM reports | ASM / ESM / GSM lists | Free | https://www.nseindia.com/reports/asm/ |
| NSE FII/DII activity | Provisional after 6pm IST, final next morning | Free | https://www.nseindia.com |
| NSDL FPI data | Includes primary market flows, unlike NSE figure | Free | https://www.fpi.nsdl.co.in |
| AMFI | Monthly SIP collection figure | Free | https://www.amfiindia.com |
| NSE paid EOD/historical | Binary EOD files + order and trade data via SFTP for CM, F&O, CD, COM | Paid | https://www.nseindia.com/static/market-data/eod-historical-data-subscription |

**Avoid for long backtests:** NSEPython's `equity_history()` errors or returns empty beyond 365 days, and can return only ~50 days when asked for 90.
Reference: https://unofficed.com/courses/mastering-algotrading-beginners-guide-nsepython/lessons/how-to-download-historical-data-from-nse-using-python/

India backtesting walkthrough with free tools: https://marketnetra.in/blog/backtesting-trading-strategy-india-free-tools

## 4.2 Backtest engines

| Engine | Use when | Note |
|---|---|---|
| vectorbt | Parameter sweeps, hypothesis research, large-universe signal work | Fastest. Vectorised, so it will lie to you about microstructure. |
| NautilusTrader | Intraday, order-book behaviour, execution realism, production parity | Rust core, Python API, event-driven, multi-asset |
| PyBroker | Features -> model -> signals workflows | Best walk-forward and train/test discipline |
| Backtesting.py | Quick sketches, teaching | Not for production research |
| zipline-reloaded + pyfolio | Classic factor research with tear sheets | Bundle ingestion setup takes hours |
| Backtrader | Maintaining existing code only | Went into long-term maintenance in 2023; not recommended for new projects |

Suggested pipeline: **PyBroker or vectorbt for discovery, NautilusTrader for execution validation.**

References:
- https://bullalert.ai/blog/best-python-backtest-engines-2026/
- https://hasanjaved.me/blog/best-python-backtesting-libraries-2026/
- https://python.financial/

---

# PART 5: SUGGESTED BUILD ORDER

1. **Build the harness first, not a strategy.** Data loader with point-in-time corporate actions (R14), survivorship-free universe (R7), circuit-lock-aware fill logic (R13), full Indian cost model (R12), and the two-pass review scripts (R2).
2. **Validate the harness against known negatives.** Run 2-3 of the nine anomalies from section 2.3. If any shows a strong out-of-sample edge, the harness is broken. Fix it before proceeding.
3. **Run the Indian calendar-anomaly battery (1.13) as a multiple-testing calibration.** Count false positives. Set your hurdle from the result.
4. **Then build, in order:** F&O ban event study (1.1), MWPL utilisation factor (1.2), ST-ASM short signal (1.3).
5. **Then the index-mechanics cluster:** 1.5, 1.6, 1.7 share most of the same data plumbing.
6. **Then flow and microstructure:** 1.8, 1.9.
7. **Report every variant tested**, including the ones that failed, with the multiple-testing count.
