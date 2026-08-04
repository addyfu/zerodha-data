# Broker fee comparison — August 2026

Two independent researchers, official pricing pages only, cross-checked against
each other; Shoonya additionally confirmed against their own calculator page.
Re-priced on our REAL 140 closed incubator trades (all intraday, ~Rs 20k orders).

## Our actual cost anatomy (Zerodha model, 140 trades)

- Total charges: Rs 2,708 (net P&L -2,975; gross -267)
- Brokerage + GST on it: Rs 1,808 (67%) — the only switchable part
- Statutory (STT/exchange/SEBI/stamp + their GST): Rs 900 (33%) — identical at every broker

## Same 140 trades under each broker (intraday equity)

| Broker | Formula (per executed order) | Total | vs Zerodha |
|---|---|---|---|
| Shoonya | min(0.03%, Rs 5) | 2,498 | **-210** |
| Zerodha | min(0.03%, Rs 20) | 2,708 | 0 |
| Dhan | min(0.03%, Rs 20) | 2,708 | 0 |
| Fyers | min(0.03%, Rs 20) | 2,708 | 0 |
| Kotak Neo | min(0.05%, Rs 10) | 3,913 | +1,205 |
| mStock | Rs 10 flat | 4,204 | +1,496 |
| Groww | min(0.1%, Rs 20), min Rs 5 | 6,926 | +4,218 |
| Angel One | min(0.1%, Rs 20), min Rs 5 | 6,926 | +4,218 |
| Upstox | min(0.1%, Rs 20) | 6,926 | +4,218 |
| 5paisa | Rs 20 flat | 7,508 | +4,800 |

Why Zerodha wins for us: percentage-with-cap beats flat fees at small order
sizes. 0.03% of Rs 20k = ~Rs 6/order; flat-Rs 20 brokers charge 3x that.
No broker offers zero intraday brokerage. Shoonya's Rs 5 cap is the only
cheaper formula and saves Rs 210 across our entire trading history.

## Delivery (matters for MAIN rotation book)

- Rs 0: Zerodha, Dhan, Shoonya
- Paid: Fyers min(0.3%,20), Angel/Groww min(0.1%,20) min Rs 5 (Angel ended free
  delivery Nov 2024), Upstox Rs 20 flat, mStock Rs 10, 5paisa Rs 20,
  Kotak Neo 0.20% uncapped (Rs 40 per Rs 20k order — worst).
- DP charge per delivery sell: Shoonya Rs 9+GST < Dhan 12.5 < Zerodha ~13 <
  mStock 18 < others Rs 20.

## API access (matters if we ever replace the enctoken scraper)

| Broker | Trading API | Market data API |
|---|---|---|
| Fyers | free | **free (historical + realtime)** |
| Angel One SmartAPI | free* | free* (*strong corroboration, primary page is JS-blocked) |
| Shoonya | free | free (their own APIs page) |
| 5paisa | free | free |
| Kotak Neo | free, "zero brokerage on API-routed trades" (own site, twice-corroborated — fine print UNVERIFIED) | ? |
| Zerodha Kite Connect | free | Rs 500/mo |
| Dhan | free | Rs 499/mo |
| Groww | Rs 499/mo bundle | included |

## Statutory notes (2026 changes)

- NSE exchange txn charge: 0.00307% from 1 Mar 2026 (was 0.00297%) —
  our config uses the old-era value; delta is paise-level, not worth chasing
  until a real-money decision.
- Budget 2026-27 (effective 1 Apr 2026) raised F&O STT ONLY: futures
  0.02%→0.05%, options premium 0.10%→0.15%, exercise 0.125%→0.15%.
  Equity intraday/delivery STT unchanged. RELEVANT to the shelved options
  strategies: options round-trips now carry ~50% more STT than our old
  assumptions would use.
- SEBI Closing Auction Session (CAS) live from 3 Aug 2026 — official close is
  now an auction print daily; last-minute-bar vs close divergence is permanent,
  not a rebalance-day quirk.

## Verdict (2026-08-04)

1. STAY on Zerodha. Already cheapest-or-tied for our profile; every popular
   alternative is 1.4-2.8x pricier on our real trade history.
2. The bleed is not a broker problem: even at a hypothetical Rs 0 brokerage,
   the 140 trades lose Rs 1,167 (gross -267, statutory -900). Charges being
   67% brokerage does NOT mean a broker switch fixes the P&L.
3. Kotak Neo "zero brokerage on API-routed trades" — RESOLVED 2026-08-04 via
   r/IndiaAlgoTrading practitioner thread (July 2026, incl. a Kotak exec
   replying in-thread): the zero brokerage is REAL today, no hidden charges
   reported by multiple live users. The fine print is INSTABILITY, not fees:
   (a) pricing flip-flopped 0 -> paid -> 0 over three years ("once they get
   enough customers they will charge again"); (b) APIs rewritten 3x in 3
   years, each forcing a full client rebuild "from login to everything";
   (c) one user reports occasional ~10-second order delays; (d) bracket/OCO
   orders missing; (e) BSE intraday disabled (irrelevant to us, NSE-only).
   Community consensus in that thread matches ours: reliability beats
   brokerage ("misfiring of an algo can take all your money saved from
   charges"); the two brokers named most reliable are Zerodha and Fyers —
   independently the same pair our fee table already shortlisted. Their
   0.20% uncapped delivery still disqualifies Kotak for the rotation book.
4. Fyers' genuinely free historical+realtime data API is the interesting
   non-fee finding — a possible future replacement for the enctoken-scraping
   fragility. Zero urgency; noted for the day Zerodha breaks something else.
5. Paper trading is unaffected by all of this — charges are simulated via
   kite/config.py either way.

Unverified/blocked during research: Paytm Money (domain 403 everywhere,
single-proxy numbers only), mStock API price (captcha), Angel SmartAPI price
(JS-only site), Kotak DP/AMC tabs, 5paisa DP/AMC exact figures.
