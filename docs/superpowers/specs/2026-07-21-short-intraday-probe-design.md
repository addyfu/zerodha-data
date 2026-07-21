# Short-Selling Intraday Probe — Design (Pre-Registration)

Date: 2026-07-21. Approved by user before any test ran.

## Goal

(A) Hunt standalone intraday short alpha on NIFTY-50 cash equity, and
(C) complete the intraday viability picture — longs already probed (all negative:
ORB-15 -18.3%, ORB-30 -16.4%, FHM -11.6% over 43 days; confirmed on Jul 13-20 sample).

India cash-equity constraint: shorts are intraday-only (square-off 15:15 in sim,
15:20 broker-side in live). Multi-day short exposure = F&O, out of scope here.

## Method

Same harness discipline as the long probe (`kite/research/intraday_probe.py`):
- 1-min bars, two independent samples: Nov 2025–Jan 2026 (43 days, 48 stocks) and
  Jul 13–20 2026 (release DB week).
- Signal on bar close → entry at NEXT bar open, 0.05% slippage per side.
- Real Zerodha intraday charges on every round trip.
- Max 5 concurrent positions, one trade per stock per day, ₹100k capital.
- Rules below are FROZEN before the first run. No parameter tuning afterward.
  Whatever prints is the answer.

## The 5 frozen rules (all short-side, all square-off 15:15)

1. **ORB-down-15 / ORB-down-30** — opening range = first 15 (variant: 30) min.
   First 1-min close below range low → short next bar open. Stop = range high.
   Target = entry − 2×(stop − entry). Risk 1% of capital per trade, position
   value capped at capital/5.
2. **First-hour weakness (FHW)** — at 10:15 rank stocks by return from 9:15 open;
   short the 3 worst if return < −0.5%. Stop +1% from entry, target −3%.
   Slot size capital/3.
3. **Gap-up fade** — open gap vs previous day close > +1.5%; after 9:30, first
   1-min close below the first-15-min low → short next bar open. Stop = day high
   so far. Target = entry − 2×(stop − entry).
4. **Failed-breakout fade** — 1-min close above the 15-min opening-range high,
   then within 30 min a 1-min close back below that high → short next bar open
   (trapped-longs hypothesis: the direct anti-strategy of the losing ORB long).
   Stop = day high so far. Target = entry − 2×(stop − entry).
5. **Relative weakness (RW)** — at 10:15: stock return < −0.3% while equal-weight
   universe mean return > +0.3% → short up to 3 worst such laggards.
   Stop +1%, target −3%. Slot size capital/3.

## Success criteria (decided now)

- A family is a **candidate** only if total P&L is positive on BOTH samples.
- Anything negative on either sample is dead; no re-tuning, no "but if we tweak".
- A candidate graduates only to the incubator (paper), never straight to money.

## Expected outcome (honest prior)

Longs lost mostly to cost drag + intraday mean reversion. Shorts pay the same
costs; #1/#2/#5 (momentum-continuation mirrors) likely lose similarly. #3/#4
(fade structures) trade WITH mean reversion instead of against it — if anything
survives, it's these. Probability any survives both samples: maybe 20%.

## Implementation

`kite/research/short_probe.py`, reusing loaders + cost fn from intraday_probe.
Short-aware day-loop (inverted SL/TP checks, pnl = entry_value − cover_value − fees).

## Results (run 2026-07-21, immediately after freezing rules)

| family | Nov-Jan (43d) | Jul 13-20 (6d) | verdict |
|---|---|---|---|
| ORBdn-15 | -13.3%, 264 trades | -0.6% | dead |
| ORBdn-30 | -16.0% | -1.9% | dead |
| FHW | -12.6% | -1.6% | dead |
| GapFade | +0.2% (3 trades = noise) | -0.8% | dead (fails both-samples rule) |
| FailedBO | **-40.9%**, 678 trades, 20% win | -4.4% | dead, spectacularly |
| RelWeak | -1.1% | -0.0% | dead |

Zero survivors under the pre-registered criteria. Notable: FailedBO — the
trapped-longs hypothesis — was the worst idea tested all session. Failed
breakouts resume upward more often than they collapse; fading them fights
both the drift and the costs. Combined with the long probe: intraday
NIFTY-50 large caps lose in BOTH directions. Goal C answered conclusively.
Inverting FailedBO is not free alpha either: its inverse ≈ buying failed
breakouts (a worse ORB long, already dead) and costs bleed both directions.
