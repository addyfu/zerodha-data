"""Blind chart-reading trial — preparation (pre-registered).

Generates ~120 anonymized candlestick charts (120 trailing daily bars + volume,
no symbol, no dates, future hidden) from data/daily_universe/, plus a hidden
answer key with realized forward 5-day returns. LLM readers see ONLY the images.

Selection: stratified random across eras (2016-2019 / 2020-2022 / 2023-2026),
turnover gate 2cr, price > 20, needs 120 prior bars and 10 future bars.
Deterministic seed so the sample can't be re-rolled until a nice result appears.
"""
import random
from pathlib import Path

import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt
import pandas as pd

ROOT = Path(__file__).resolve().parents[2]
OUT = Path(r'C:\Users\pc\AppData\Local\Temp\claude\D--study-kite\c5eabc60-ba09-4803-be78-0882e5d0afd1\scratchpad\chart_trial')
LOOKBACK = 120
FORWARD = 5
PER_ERA = 40
SEED = 42
ERAS = [('2016-01-01', '2019-12-31'), ('2020-01-01', '2022-12-31'), ('2023-01-01', '2026-06-30')]


def load():
    data = {}
    for f in sorted((ROOT / 'data' / 'daily_universe').glob('*_day.csv')):
        sym = f.name[:-8]
        df = pd.read_csv(f, parse_dates=['datetime'])
        df['date'] = df.datetime.dt.tz_localize(None).dt.normalize()
        df = df.set_index('date')[['open', 'high', 'low', 'close', 'volume']]
        df = df[~df.index.duplicated(keep='last')]
        if len(df) >= 400:
            data[sym] = df
    return data


def render(window, path):
    fig, (ax, axv) = plt.subplots(2, 1, figsize=(10, 6), sharex=True,
                                  gridspec_kw={'height_ratios': [3, 1]}, dpi=80)
    x = range(len(window))
    for i, (_, r) in enumerate(window.iterrows()):
        color = '#26a69a' if r.close >= r.open else '#ef5350'
        ax.plot([i, i], [r.low, r.high], color=color, linewidth=0.7)
        ax.add_patch(plt.Rectangle((i - 0.35, min(r.open, r.close)), 0.7,
                                   max(abs(r.close - r.open), r.close * 1e-4),
                                   facecolor=color, edgecolor=color))
        axv.bar(i, r.volume, color=color, width=0.7)
    ax.set_xlim(-1, len(window))
    ax.set_ylabel('price')
    axv.set_ylabel('volume')
    ax.set_xticks([])
    axv.set_xticks([])
    axv.set_yticks([])
    fig.tight_layout()
    fig.savefig(path)
    plt.close(fig)


def main():
    random.seed(SEED)
    data = load()
    OUT.mkdir(parents=True, exist_ok=True)
    syms = sorted(data)
    rows = []
    n = 0
    for a, b in ERAS:
        a, b = pd.Timestamp(a), pd.Timestamp(b)
        picked = 0
        attempts = 0
        while picked < PER_ERA and attempts < 5000:
            attempts += 1
            sym = random.choice(syms)
            df = data[sym]
            era_idx = df.index[(df.index >= a) & (df.index <= b)]
            if len(era_idx) < LOOKBACK + FORWARD + 5:
                continue
            pos = random.randrange(LOOKBACK, len(era_idx) - FORWARD - 1)
            t = era_idx[pos]
            ti = df.index.get_loc(t)
            if ti < LOOKBACK or ti + FORWARD >= len(df):
                continue
            window = df.iloc[ti - LOOKBACK + 1: ti + 1]
            row = df.iloc[ti]
            turn = (window.close * window.volume).tail(60).median()
            if turn < 2e7 or row.close < 20:
                continue
            fwd = df.iloc[ti + FORWARD].close / row.close - 1
            mom20 = row.close / df.iloc[ti - 20].close - 1
            n += 1
            name = f'chart_{n:03d}.png'
            render(window, OUT / name)
            rows.append({'chart': name, 'symbol': sym, 'date': str(t.date()),
                         'fwd5': round(fwd, 5), 'mom20': round(mom20, 5)})
            picked += 1
    key = pd.DataFrame(rows)
    key.to_csv(OUT / 'answer_key.csv', index=False)
    print(f'{len(rows)} charts -> {OUT}')
    print('truth distribution: up', (key.fwd5 > 0.01).sum(), '| down', (key.fwd5 < -0.01).sum(),
          '| flat', ((key.fwd5 >= -0.01) & (key.fwd5 <= 0.01)).sum())


if __name__ == '__main__':
    main()
