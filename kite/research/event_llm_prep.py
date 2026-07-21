"""Phase 3 prep: build the anonymized scoring sample for H2 testing.

Selects events in the qualifying (text-rich) categories from Phase 2 plus a
matched random control, anonymizes the text (strip company name tokens, ISIN,
person-name honorifics), and attaches each event's realized 5-day CAR from the
event study. Clean-window (2026) events flagged separately.

Output: kite/research/phase3_sample.csv  (id, anon_text, category, era,
clean_window, car5) — the LLM sees ONLY anon_text; car5 is hidden truth.
"""
import re
import sys
from pathlib import Path

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parents[2]

# Phase-2 qualifying categories that actually carry company-written text.
# "Spurt in Volume" is an exchange surveillance notice with no company narrative
# -> excluded from H2 (nothing to read); kept as an avoid-filter signal elsewhere.
TEXT_CATEGORIES = [
    'Change in Director(s)',
    'Disclosure under SEBI Takeover Regulations',
    'Statement of deviation(s) or variation(s) under Reg. 32',
]
CONTROL_CATEGORIES = ['Outcome of Board Meeting', 'Press Release', 'Updates']
STOP = {'limited', 'ltd', 'ltd.', 'industries', 'india', 'company', 'corporation',
        'corp', 'enterprises', 'the', 'and', 'of', 'co', 'co.', 'private', 'pvt'}


def anonymize(text, name, isin):
    if not isinstance(text, str):
        return ''
    out = text
    if isinstance(name, str):
        out = re.sub(re.escape(name), ' COMPANY ', out, flags=re.IGNORECASE)
        for tok in re.split(r'[\s,.]+', name):
            if len(tok) >= 3 and tok.lower() not in STOP:
                out = re.sub(r'\b' + re.escape(tok) + r'\b', 'COMPANY', out, flags=re.IGNORECASE)
    if isinstance(isin, str) and isin:
        out = out.replace(isin, 'ISIN')
    # person names after honorifics -> PERSON
    out = re.sub(r'\b(Mr|Ms|Mrs|Dr|Shri|Smt|Sri)\.?\s+([A-Z][a-z]+(\s+[A-Z][a-z]+){0,3})',
                 'PERSON', out)
    out = re.sub(r'\s+', ' ', out).strip()
    return out


def main():
    seed = 20260721
    rng = np.random.default_rng(seed)
    # need the event study's per-event car5; re-derive minimal join from results is
    # heavy, so recompute car5 here for just the sampled events would duplicate logic.
    # Instead: the event study already wrote per-cell aggregates, not per-event. We
    # recompute car5 per sampled event using the same price convention.
    prices = {}
    for f in (ROOT / 'data' / 'daily_universe').glob('*_day.csv'):
        sym = f.name[:-8]
        df = pd.read_csv(f, parse_dates=['datetime'])
        df['date'] = df.datetime.dt.tz_localize(None).dt.normalize()
        df = df.set_index('date')[['open', 'close', 'volume']]
        prices[sym] = df[~df.index.duplicated(keep='last')]
    closes = pd.DataFrame({s: d.close for s, d in prices.items()})
    uret = closes.pct_change(fill_method=None).clip(-0.25, 0.25).mean(axis=1)

    wanted = set(TEXT_CATEGORIES + CONTROL_CATEGORIES)
    frames = []
    for f in sorted((ROOT / 'data' / 'announcements').glob('ann_*.csv')):
        df = pd.read_csv(f, usecols=['sort_date', 'symbol', 'sm_name', 'sm_isin',
                                     'desc', 'attchmntText'])
        df = df[df.desc.isin(wanted) & df.symbol.isin(prices)]
        if len(df):
            frames.append(df)
    ev = pd.concat(frames, ignore_index=True)
    ev['ts'] = pd.to_datetime(ev.sort_date)

    rows = []
    for _, r in ev.iterrows():
        p = prices[r.symbol]
        idx = p.index
        d = r.ts.normalize()
        after = idx[idx >= d] if r.ts.time() <= pd.Timestamp('15:30').time() else idx[idx > d]
        if len(after) == 0:
            continue
        E = after[0]
        if (E - d).days > 5:
            continue
        ei = idx.get_loc(E)
        if ei + 6 >= len(idx):
            continue
        turn = (p.close * p.volume).iloc[max(0, ei - 59):ei + 1].median()
        if turn < 2e7 or p.close.iloc[ei] < 20:
            continue
        stock = p.close.iloc[ei + 5] / p.open.iloc[ei + 1] - 1
        span = idx[ei + 1:ei + 6]
        mkt = (1 + uret.reindex(span).fillna(0)).prod() - 1
        rows.append({'symbol': r.symbol, 'category': r.desc, 'ts': r.ts,
                     'car5': stock - mkt, 'is_text_cat': r.desc in TEXT_CATEGORIES,
                     'anon_text': anonymize(r.attchmntText, r.sm_name, r.sm_isin)})
    d = pd.DataFrame(rows)
    d = d[d.anon_text.str.len() >= 30]  # need something to read
    d['era'] = d.ts.dt.year.map(lambda y: '2020-2022' if y <= 2022 else ('2023-2024' if y <= 2024 else '2025-2026'))
    d['clean_window'] = d.ts.dt.year >= 2026

    # Pilot sample: 200 balanced text-category events, clean-window-weighted
    text = d[d.is_text_cat]
    clean = text[text.clean_window]
    old = text[~text.clean_window]
    n_clean = min(120, len(clean))
    n_old = min(80, len(old))
    pilot = pd.concat([clean.sample(n_clean, random_state=seed),
                       old.sample(n_old, random_state=seed)]).reset_index(drop=True)
    pilot['id'] = ['ev_%03d' % i for i in range(len(pilot))]
    pilot['anon_text'] = pilot.anon_text.str.slice(0, 600)
    pilot[['id', 'category', 'era', 'clean_window', 'car5', 'anon_text']].to_csv(
        ROOT / 'kite' / 'research' / 'phase3_pilot.csv', index=False)
    d.to_csv(ROOT / 'kite' / 'research' / 'phase3_full.csv', index=False)
    print(f'full text-cat events: {len(text)} (clean-window {len(clean)})')
    print(f'pilot: {len(pilot)} events -> phase3_pilot.csv')
    # leakage self-check: any surviving company name tokens?
    leaks = pilot.anon_text.str.contains(r'\b(Reliance|Adani|Tata|Infosys|HDFC)\b', case=False, regex=True).sum()
    print(f'obvious-name leakage in pilot: {leaks}/{len(pilot)}')
    print('sample anon_text:', pilot.anon_text.iloc[0][:200])


if __name__ == '__main__':
    main()
