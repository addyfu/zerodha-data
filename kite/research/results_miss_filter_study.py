"""
Fast measurement study (pre-registered, frozen question):
If the live avoid-filter were extended with "block new entries for 20 trading
days in any stock whose results-day reaction was < -2%", how much abnormal
drift would the blocked window have dodged historically?

Inputs:
  - kite/research/pead_events.csv  (8022 PEAD events, R = results-day reaction,
    bucket already computed as NEGATIVE/MIDDLE/POSITIVE at the +/-2% threshold,
    car_20d = 20-day cumulative abnormal return from entry)
  - data/announcements/ann_*.csv   (raw NSE announcements, 'desc' column carries
    the category strings used by the live red-flag filter)

Output: printed report, also saved to kite/research/results_miss_filter_study.txt
"""
import pandas as pd
import numpy as np
import glob

pd.set_option('display.width', 140)

RED_FLAG_CATEGORIES = [
    'Change in Director(s)',
    'Disclosure under SEBI Takeover Regulations',
    'Spurt in Volume',
    'Statement of deviation(s) or variation(s) under Reg. 32',
]

OUT_LINES = []
def p(s=""):
    print(s)
    OUT_LINES.append(str(s))

# ---------------------------------------------------------------------------
df = pd.read_csv('kite/research/pead_events.csv', parse_dates=['ann_ts', 'E_date', 'entry_date'])
assert set(df['bucket'].unique()) <= {'NEGATIVE', 'MIDDLE', 'POSITIVE'}
assert df['category'].nunique() == 1  # sanity: this dataset is Financial Result Updates only

neg = df[df['bucket'] == 'NEGATIVE'].copy()
total_n = len(df)
neg_n = len(neg)

p("=" * 78)
p("RESULTS-MISS AVOID-FILTER STUDY  (pre-registered, frozen question)")
p("Rule tested: block new entries 20 trading days in any stock whose")
p("results-day reaction R was < -2%  (bucket == NEGATIVE)")
p("=" * 78)
p(f"Universe: {total_n} PEAD events, all category='Financial Result Updates'")
p(f"NEGATIVE-bucket events (R < -2%): {neg_n}  ({neg_n/total_n*100:.1f}% of all events)")
p("")

# ---------------------------------------------------------------------------
# 1. Per-era + pooled table
# ---------------------------------------------------------------------------
p("-" * 78)
p("1) NEGATIVE-bucket events by era")
p("-" * 78)

rows = []
for era, g in df.groupby('era'):
    gn = g[g['bucket'] == 'NEGATIVE']
    rows.append({
        'era': era,
        'n_all': len(g),
        'n_NEG': len(gn),
        'pct_NEG_of_era': len(gn) / len(g) * 100,
        'mean_car20d_NEG': gn['car_20d'].mean(),
        'median_car20d_NEG': gn['car_20d'].median(),
        'pct_car20d_negative': (gn['car_20d'] < 0).mean() * 100,
    })
era_table = pd.DataFrame(rows).set_index('era').sort_index()
p(era_table.to_string(float_format=lambda x: f"{x:0.4f}"))
p("")

pooled = {
    'n_NEG': neg_n,
    'pct_of_all': neg_n / total_n * 100,
    'mean_car20d': neg['car_20d'].mean(),
    'median_car20d': neg['car_20d'].median(),
    'pct_car20d_negative': (neg['car_20d'] < 0).mean() * 100,
    'p10_car20d': neg['car_20d'].quantile(0.10),
    'p90_car20d': neg['car_20d'].quantile(0.90),
}
p("POOLED (all eras):")
for k, v in pooled.items():
    p(f"  {k:22s}: {v:0.4f}" if isinstance(v, float) else f"  {k:22s}: {v}")
p("")

# ---------------------------------------------------------------------------
# 2. Counterfactual value + tail
# ---------------------------------------------------------------------------
p("-" * 78)
p("2) Counterfactual: abnormal drift a block would have dodged")
p("-" * 78)
mean_car20d_neg = neg['car_20d'].mean()
median_car20d_neg = neg['car_20d'].median()
p10_car20d_neg = neg['car_20d'].quantile(0.10)
p(f"Mean car_20d of NEGATIVE events   : {mean_car20d_neg:+.4f}  ({mean_car20d_neg*100:+.2f}%)")
p(f"Median car_20d of NEGATIVE events : {median_car20d_neg:+.4f}  ({median_car20d_neg*100:+.2f}%)")
p(f"10th pct car_20d (tail/bad case)  : {p10_car20d_neg:+.4f}  ({p10_car20d_neg*100:+.2f}%)")
p(f"Share of NEGATIVE events with car_20d < 0 : {(neg['car_20d']<0).mean()*100:.1f}%")
p("Interpretation: on average, a stock whose results reaction was < -2% kept")
p(f"drifting by about {mean_car20d_neg*100:+.2f}% (abnormal) over the following 20 trading")
p(f"days from entry; the worst 10% of such cases lost {p10_car20d_neg*100:+.2f}% or more.")
p("")

# ---------------------------------------------------------------------------
# 3. Overlap check with existing 4 red-flag categories
# ---------------------------------------------------------------------------
p("-" * 78)
p("3) Overlap with existing announcement-desc-based red-flag filter")
p(f"   Red-flag categories: {RED_FLAG_CATEGORIES}")
p("   Window: any red-flag announcement for the same symbol within +/-5")
p("   calendar days of E_date counts as overlap.")
p("-" * 78)

files = sorted(glob.glob('data/announcements/ann_*.csv'))
ann_chunks = []
for f in files:
    try:
        c = pd.read_csv(f, usecols=['an_dt', 'symbol', 'desc'])
    except ValueError:
        # some monthly files may have slightly different columns; skip gracefully
        c = pd.read_csv(f)
        c = c[['an_dt', 'symbol', 'desc']]
    c = c[c['desc'].isin(RED_FLAG_CATEGORIES)]
    if len(c):
        ann_chunks.append(c)
ann = pd.concat(ann_chunks, ignore_index=True)
ann['an_dt'] = pd.to_datetime(ann['an_dt'], errors='coerce')
ann = ann.dropna(subset=['an_dt'])
p(f"Loaded {len(ann)} red-flag-category announcements across {len(files)} monthly files "
  f"({ann['symbol'].nunique()} distinct symbols).")

# build a per-symbol sorted array of red-flag announcement dates for fast windowed lookup
ann_by_symbol = {sym: np.sort(g['an_dt'].values.astype('datetime64[D]'))
                 for sym, g in ann.groupby('symbol')}

def has_overlap(symbol, e_date, window_days=5):
    dates = ann_by_symbol.get(symbol)
    if dates is None or len(dates) == 0:
        return False
    e = np.datetime64(pd.Timestamp(e_date).date())
    lo, hi = e - np.timedelta64(window_days, 'D'), e + np.timedelta64(window_days, 'D')
    idx_lo = np.searchsorted(dates, lo, side='left')
    idx_hi = np.searchsorted(dates, hi, side='right')
    return idx_hi > idx_lo

neg = neg.copy()
neg['has_redflag_overlap'] = [
    has_overlap(sym, e) for sym, e in zip(neg['symbol'], neg['E_date'])
]
overlap_n = int(neg['has_redflag_overlap'].sum())
overlap_pct = overlap_n / neg_n * 100
p(f"NEGATIVE-bucket events with a red-flag-category announcement for the SAME")
p(f"symbol within +/-5 days of E_date: {overlap_n} / {neg_n}  ({overlap_pct:.1f}%)")
p(f"=> {100-overlap_pct:.1f}% of NEGATIVE-bucket events have NO overlap with the")
p("   existing 4-category filter -- the results-miss rule would be catching")
p("   drift episodes the current announcement-desc filter does not flag.")
p("")

# ---------------------------------------------------------------------------
# 4. Frequency: blocked-stock-days per year
# ---------------------------------------------------------------------------
p("-" * 78)
p("4) Frequency: blocked-stock-days/year this rule would add")
p("   (20 TRADING days per NEGATIVE event, starting at entry_date,")
p("    deduped by symbol-day across overlapping/re-triggered windows)")
p("-" * 78)

blocked_pairs = set()
for sym, entry in zip(neg['symbol'], neg['entry_date']):
    window = pd.bdate_range(start=entry, periods=20)  # trading-day proxy
    for d in window:
        blocked_pairs.add((sym, d.date()))

total_blocked_days = len(blocked_pairs)
all_dates = [d for _, d in blocked_pairs]
span_years = (max(all_dates) - min(all_dates)).days / 365.25
blocked_days_per_year = total_blocked_days / span_years

p(f"Total unique (symbol, day) blocked pairs, {min(all_dates)} to {max(all_dates)}: "
  f"{total_blocked_days}")
p(f"Span: {span_years:.2f} years  =>  ~{blocked_days_per_year:,.0f} blocked-stock-days/year")
p(f"(gross, no dedup, would have been {neg_n*20} = {neg_n} events x 20 days)")
dedup_savings = 1 - total_blocked_days / (neg_n * 20)
p(f"Dedup collapsed {dedup_savings*100:.1f}% of gross blocked-days (re-triggers / overlapping windows on same symbol)")
p("")

# ---------------------------------------------------------------------------
# Verdict
# ---------------------------------------------------------------------------
p("-" * 78)
p("VERDICT / RECOMMENDATION")
p("-" * 78)
p(f"Pooled: {neg_n} events ({neg_n/total_n*100:.1f}% of all PEAD events) had results-day")
p(f"reaction < -2%. These kept drifting by a mean of {mean_car20d_neg*100:+.2f}% (median "
  f"{median_car20d_neg*100:+.2f}%) abnormal")
p(f"return over the next 20 trading days, with {(neg['car_20d']<0).mean()*100:.0f}% staying negative and a bad-case "
  f"(10th pct) of {p10_car20d_neg*100:+.2f}%.")
p(f"Only {overlap_pct:.1f}% of these events overlap with the existing 4-category announcement")
p("red-flag filter within +/-5 days -- this is largely ADDITIVE coverage, not redundant.")
p(f"Adding the rule would cost ~{blocked_days_per_year:,.0f} blocked-stock-days/year of lost opportunity")
p("across the universe.")
p("")
p("ONE-LINE RECOMMENDATION: The results-miss rule looks worth prototyping --")
p("large, mostly non-overlapping population with a clearly negative and fairly")
p("consistent 20-day aftermath -- but this is IN-SAMPLE measurement of an")
p("already-observed effect (the bucket/car_20d were computed from the same")
p("realized data being scored here); deploying it as a live filter needs its")
p("own forward-looking pre-registration doc (fixed threshold decided BEFORE")
p("seeing new data, walk-forward or out-of-sample era holdout, and transaction-")
p("cost/opportunity-cost accounting for the ~%.0f blocked-days/year) before it" % blocked_days_per_year)
p("goes anywhere near the live monitor.")
p("=" * 78)

with open('kite/research/results_miss_filter_study.txt', 'w') as fh:
    fh.write("\n".join(OUT_LINES) + "\n")
