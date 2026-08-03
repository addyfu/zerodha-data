# Options Data — Manifest

Acquired 2026-08-03 via free-source recon (sonnet agent, reviewer-verified by
direct download + row inspection). All sources legal/public.

## nifty_options_1min_2024-2026.zip (702MB)

1-minute OHLCV+OI for EVERY NIFTY weekly option strike, full contract life
(listing → expiry). 125 expiry archives, 2024-01-04 → 2026-05-05, ~190-207
strike CSVs per expiry. Columns: Date, Timestamp, Open, High, Low, Close,
Volume, OI, Ticker. Includes the 2024-06-04 election-crash week (expiries
20240606 onward) — a genuine tail event at minute resolution.
Source: shoonyatrader.in free Dropbox dump (openly published; NOT affiliated
with Finvasia broker despite the name). Reviewer verified: nested zip
structure intact, sample rows sane (prices/volume/OI plausible).

## banknifty_options_1min_2026H1.zip (37MB)

Same format, BANKNIFTY, but only 4 expiries from 2026-01-27 — too thin for
research; kept for completeness.

## bse_*.csv

Sample BSE F&O (SENSEX options) UDiFF bhavcopy days. BSE archive reaches
~2024 only.

## EOD F&O bhavcopy (NOT YET DOWNLOADED — verified working)

- Old format (2001 → 2024-06):
  archives.nseindia.com/content/historical/DERIVATIVES/YYYY/MON/foDDMONYYYYbhav.csv.zip
- New UDiFF (2024-01 →):
  nsearchives.nseindia.com/content/fo/BhavCopy_NSE_FO_0_0_0_YYYYMMDD_F_0000.csv.zip
- Per-expired-contract EOD query (works for dead contracts):
  nseindia.com/api/historicalOR/foCPV
- CRITICAL data note: only strikes with volume > 0 carry real OHLC; zero-
  volume strikes have O=H=L=0 with only close/settle populated. Filter on
  volume before trusting OHLC.

## Known gaps (nothing free/legal found)

- Intraday options before 2024 (any index) — paid vendors only.
- BankNifty intraday depth.
- Unverified lead: Finvasia/Shoonya official API get_time_price_series for
  expired contracts (needs a live account to test).

## Status

No study uses this data yet. Any option study requires its own frozen
pre-registered spec first (house rule). Standing note: even a passing
option-selling strategy is UNDEPLOYABLE at current capital (margin ~1.5-2L/
lot + earthquake reserves) — studies are knowledge-only.
