"""
Zerodha unofficial API rate-limit probe (READ-ONLY, safety-first)
===================================================================

PURPOSE
-------
Empirically measure the throttle behaviour of the unofficial Zerodha
browser-session API (kite.zerodha.com/oms) that ZerodhaDataFetcher talks to.
Stops at the FIRST 429 per endpoint. Every request is a read-only GET.

WHEN/WHERE TO RUN
------------------
This must run on the Oracle production host, and ONLY after the
live_monitor systemd service has been stopped. Zerodha's web session is
single-session: logging in here (to get a fresh enctoken) silently
invalidates whatever session the running monitor is holding. Running this
next to a live monitor would kick its token and break live trading.

Because of that, main() refuses to do anything unless invoked with
--i-stopped-the-monitor, e.g.:

    systemctl stop live_monitor      # or however it's supervised
    python kite/research/rate_probe.py --i-stopped-the-monitor

SAFETY INVARIANTS (line-review these against the code below)
--------------------------------------------------------------
1. Read-only GETs only. Every network call in this file is `requests.get`;
   nothing ever POSTs/PUTs/DELETEs, and the only non-GET traffic is the
   login flow itself (zerodha_auto_login, which is the standard auth flow
   the monitor already performs on every restart).
2. Hard global cap of 600 requests total, enforced by the single shared
   `Budget` object passed into both probes. Checked BEFORE every request is
   sent (see the `if budget.exhausted(): ... break` guards) — the cap can
   never be exceeded even mid-stage.
3. First-429-stop, per endpoint, with NO retry-through-429 ever. The 429
   branch in each request loop always does: record -> print -> break.
   There is no code path anywhere that re-sends a request after seeing 429;
   grep this file for "429" to verify every occurrence is followed by a
   `break`/`return`, never a retry.
4. 120s cool-down between probe A and probe B (COOLDOWN_SECONDS).
5. Every stage transition is printed live (`print(..., flush=True)`) as it
   starts, plus a per-request line during batch-size discovery.
6. Graceful KeyboardInterrupt handling: every stage loop wraps its body in
   try/except KeyboardInterrupt, appends whatever partial stage stats it
   has collected so far, marks the result `interrupted`, and returns
   immediately (no re-raise needed) so main()'s finally-block always
   writes rate_probe_results.json before exiting.
7. Instrument-list loading (ZerodhaDataFetcher._load_instruments, an
   unauthenticated GET to api.kite.trade/instruments — a different, public,
   non-throttled endpoint) and the login flow are NOT counted against the
   600-request budget; the budget only counts calls to the two throttled
   trading endpoints under test.

OUTPUTS
-------
- kite/research/rate_probe_log.jsonl  — one JSON line per request:
      {ts, probe, rate_stage, batch_size, http_status, n_returned, latency_ms}
  (plus `detail`/`note` extra fields for debugging context.)
- kite/research/rate_probe_results.json — final structured report.
- stdout — human-readable live progress + final summary.
"""
import sys
import os
import json
import time
import random
import argparse
import statistics
from pathlib import Path
from datetime import datetime, timedelta

import requests

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

from zerodha_auto_login import get_enctoken
from kite.live_monitor.data_fetcher import ZerodhaDataFetcher

# ---------------------------------------------------------------------------
# Config / safety constants
# ---------------------------------------------------------------------------
LOG_PATH = Path(__file__).parent / 'rate_probe_log.jsonl'
RESULTS_PATH = Path(__file__).parent / 'rate_probe_results.json'

HARD_GLOBAL_CAP = 600            # absolute ceiling across BOTH probes combined
REQUEST_TIMEOUT = 15              # seconds, generous but bounded
COOLDOWN_SECONDS = 120            # between probe A and probe B

PROBE_A_CAP = 400
PROBE_A_STAGES = [0.5, 1, 2, 3, 4, 6, 8]   # req/s
PROBE_A_STAGE_SECONDS = 20

QUOTE_BATCH_SIZES = [10, 25, 50, 100, 200, 400]
QUOTE_DISCOVERY_SPACING = 2.0      # seconds between batch-size discovery requests
PROBE_B_STAGE_CAP = 150            # cap for the rate-escalation phase only (discovery is separate, fixed at 6 requests)
PROBE_B_STAGES = [0.5, 1, 2, 4]     # req/s
PROBE_B_STAGE_SECONDS = 15

# NIFTY-50 -- copied from kite/live_monitor/monitor.py's NIFTY_50 list. Keep in
# sync. Duplicated here (rather than `from kite.live_monitor.monitor import
# NIFTY_50`) so this probe has zero import-time side effects from monitor.py,
# which wires up schedule/telegram/db logging handlers and a shared
# data/monitor.log FileHandler just by being imported.
NIFTY_50 = [
    'ADANIPORTS', 'APOLLOHOSP', 'ASIANPAINT', 'AXISBANK', 'BAJAJ-AUTO',
    'BAJAJFINSV', 'BAJFINANCE', 'BHARTIARTL', 'BPCL', 'BRITANNIA',
    'CIPLA', 'COALINDIA', 'DIVISLAB', 'DRREDDY', 'EICHERMOT',
    'GRASIM', 'HCLTECH', 'HDFCBANK', 'HDFCLIFE', 'HEROMOTOCO',
    'HINDALCO', 'HINDUNILVR', 'ICICIBANK', 'INDUSINDBK', 'INFY',
    'ITC', 'JSWSTEEL', 'KOTAKBANK', 'LT', 'M&M',
    'MARUTI', 'NESTLEIND', 'NTPC', 'ONGC', 'POWERGRID',
    'RELIANCE', 'SBIN', 'SHREECEM', 'SUNPHARMA', 'TATACONSUM',
    'TATASTEEL', 'TCS', 'TECHM', 'TITAN',  # TATAMOTORS removed: token dead post-2025 demerger
    'ULTRACEMCO', 'UPL', 'WIPRO'
]


def _load_dotenv():
    """Same inline .env loader monitor.py uses (local dev convenience; on
    Oracle the env vars are normally already exported in the service unit)."""
    env_file = ROOT / '.env'
    if not env_file.exists():
        return
    with open(env_file) as f:
        for line in f:
            line = line.strip()
            if line and not line.startswith('#') and '=' in line:
                key, _, val = line.partition('=')
                val = val.strip()
                if val.startswith(('"', "'")) and val.endswith(val[0]):
                    val = val[1:-1]
                else:
                    val = val.split('#')[0].strip()
                os.environ.setdefault(key.strip(), val)


class Budget:
    """Single shared counter enforcing the hard global request cap (600).
    Checked before every single HTTP request in both probes — never after."""

    def __init__(self, hard_cap):
        self.hard_cap = hard_cap
        self.count = 0

    def exhausted(self):
        return self.count >= self.hard_cap

    def record(self):
        self.count += 1


def log_request(probe, rate_stage, batch_size, http_status, n_returned,
                 latency_ms, detail=None, note=None):
    """Append one line to rate_probe_log.jsonl. Never raises on I/O failure
    on the caller's behalf beyond what json/open naturally raise, since a
    logging failure should be loud, not silently swallowed."""
    row = {
        'ts': datetime.now().isoformat(timespec='seconds'),
        'probe': probe,
        'rate_stage': rate_stage,
        'batch_size': batch_size,
        'http_status': http_status,
        'n_returned': n_returned,
        'latency_ms': round(latency_ms, 1) if latency_ms is not None else None,
        'detail': detail,
        'note': note,
    }
    with open(LOG_PATH, 'a') as f:
        f.write(json.dumps(row) + '\n')
    return row


def _stage_latency_stats(latencies):
    if not latencies:
        return {'n': 0}
    s = sorted(latencies)
    return {
        'n': len(s),
        'mean_ms': round(statistics.mean(s), 1),
        'p50_ms': round(s[len(s) // 2], 1),
        'p95_ms': round(s[min(len(s) - 1, int(len(s) * 0.95))], 1),
        'max_ms': round(max(s), 1),
    }


# ---------------------------------------------------------------------------
# Raw HTTP helpers. Deliberately NOT using fetcher.get_quote /
# fetcher.get_historical_data: those swallow the HTTP status code and
# response shape we need here to detect 429 precisely and to check for
# silent truncation of the quote endpoint's response.
# ---------------------------------------------------------------------------

def _historical_request(fetcher, symbol):
    """Single read-only GET to /oms/instruments/historical/<token>/5minute
    for a 1-day window. Returns (http_status, latency_ms, n_candles, error)."""
    token = fetcher.instruments[symbol]
    to_date = datetime.now()
    from_date = to_date - timedelta(days=1)
    url = f"{fetcher.BASE_URL}/instruments/historical/{token}/5minute"
    params = {'from': from_date.strftime('%Y-%m-%d'),
              'to': to_date.strftime('%Y-%m-%d'), 'oi': 1}
    t0 = time.monotonic()
    try:
        resp = requests.get(url, headers=fetcher._get_headers(),
                             params=params, timeout=REQUEST_TIMEOUT)
    except requests.RequestException as e:
        return -1, (time.monotonic() - t0) * 1000, 0, str(e)
    elapsed_ms = (time.monotonic() - t0) * 1000
    n_returned = 0
    if resp.status_code == 200:
        try:
            n_returned = len(resp.json().get('data', {}).get('candles') or [])
        except Exception:
            n_returned = 0
    return resp.status_code, elapsed_ms, n_returned, None


def _quote_request(fetcher, symbols):
    """Single read-only GET to the bulk quote endpoint for `symbols`.
    Returns (http_status, latency_ms, n_returned, error)."""
    instruments = [f"NSE:{s}" for s in symbols]
    url = f"{fetcher.QUOTE_URL}?i={'&i='.join(instruments)}"
    t0 = time.monotonic()
    try:
        resp = requests.get(url, headers=fetcher._get_headers(), timeout=REQUEST_TIMEOUT)
    except requests.RequestException as e:
        return -1, (time.monotonic() - t0) * 1000, 0, str(e)
    elapsed_ms = (time.monotonic() - t0) * 1000
    n_returned = 0
    if resp.status_code == 200:
        try:
            n_returned = len(resp.json().get('data') or {})
        except Exception:
            n_returned = 0
    return resp.status_code, elapsed_ms, n_returned, None


# ---------------------------------------------------------------------------
# Probe A -- historical endpoint escalating-rate sweep
# ---------------------------------------------------------------------------

def run_probe_a(fetcher, budget, symbols):
    print("\n" + "=" * 70)
    print("PROBE A: historical endpoint throttle sweep "
          "(/oms/instruments/historical/<token>/5minute)")
    print("=" * 70, flush=True)

    result = {
        'endpoint': 'historical/<token>/5minute',
        'stages': [],
        'throttle_rate_req_s': None,
        'no_throttle_up_to': None,
        'stopped_reason': None,
        'session_abort': False,
        'interrupted': False,
        'total_requests': 0,
    }
    total_sent = 0

    for rate in PROBE_A_STAGES:
        interval = 1.0 / rate
        print(f"\n[PROBE A] --- stage {rate} req/s (sleep {interval:.2f}s between requests, "
              f"{PROBE_A_STAGE_SECONDS}s budget) --- total sent so far: {total_sent}/{PROBE_A_CAP}",
              flush=True)
        stage_count = 0
        latencies = []
        hit_429 = False
        cap_hit = False
        stage_start = time.monotonic()

        try:
            while time.monotonic() - stage_start < PROBE_A_STAGE_SECONDS:
                if total_sent >= PROBE_A_CAP:
                    result['stopped_reason'] = (
                        f'no throttle found up to {rate} req/s '
                        f'(stopped early: hit {PROBE_A_CAP}-request probe cap mid-stage)')
                    result['no_throttle_up_to'] = rate
                    cap_hit = True
                    print(f"[PROBE A] hit probe cap ({PROBE_A_CAP} requests) — stopping sweep", flush=True)
                    break
                if budget.exhausted():
                    result['stopped_reason'] = (
                        f'no throttle found up to {rate} req/s '
                        f'(stopped early: hit HARD GLOBAL CAP {budget.hard_cap})')
                    result['no_throttle_up_to'] = rate
                    cap_hit = True
                    print(f"[PROBE A] hit HARD GLOBAL CAP ({budget.hard_cap}) — stopping everything", flush=True)
                    break

                symbol = random.choice(symbols)
                status, latency_ms, n_returned, note = _historical_request(fetcher, symbol)
                budget.record()
                total_sent += 1
                stage_count += 1
                latencies.append(latency_ms)
                log_request('historical', rate, None, status, n_returned, latency_ms,
                             detail=symbol, note=note)

                if status in (401, 403):
                    print(f"[PROBE A] *** HTTP {status} on {symbol} — SESSION ISSUE, "
                          f"aborting everything ***", flush=True)
                    result['session_abort'] = True
                    result['stopped_reason'] = f'auth_error_{status}'
                    result['stages'].append({
                        'rate': rate, 'requests_this_stage': stage_count,
                        'total_sent': total_sent, 'hit_429': False,
                        'latency': _stage_latency_stats(latencies)})
                    result['total_requests'] = total_sent
                    return result

                if status == 429:
                    hit_429 = True
                    result['throttle_rate_req_s'] = rate
                    result['stopped_reason'] = f'429 at {rate} req/s'
                    print(f"[PROBE A] *** 429 at {rate} req/s after {stage_count} reqs this "
                          f"stage ({total_sent} total) — STOPPING PROBE A, no retry ***", flush=True)
                    break

                time.sleep(interval)
        except KeyboardInterrupt:
            result['interrupted'] = True
            result['stopped_reason'] = 'keyboard_interrupt'
            result['stages'].append({
                'rate': rate, 'requests_this_stage': stage_count,
                'total_sent': total_sent, 'hit_429': hit_429,
                'latency': _stage_latency_stats(latencies)})
            result['total_requests'] = total_sent
            print("\n[PROBE A] KeyboardInterrupt — saving partial stage results", flush=True)
            return result

        result['stages'].append({
            'rate': rate, 'requests_this_stage': stage_count,
            'total_sent': total_sent, 'hit_429': hit_429,
            'latency': _stage_latency_stats(latencies)})

        if hit_429 or cap_hit:
            break

    if result['stopped_reason'] is None:
        result['no_throttle_up_to'] = PROBE_A_STAGES[-1]
        result['stopped_reason'] = f'no throttle found up to {PROBE_A_STAGES[-1]} req/s'

    result['total_requests'] = total_sent
    return result


# ---------------------------------------------------------------------------
# Probe B -- bulk quote endpoint: batch-size discovery, then rate sweep
# ---------------------------------------------------------------------------

def run_probe_b(fetcher, budget):
    print("\n" + "=" * 70)
    print("PROBE B: bulk quote endpoint — batch-size discovery + throttle sweep")
    print("=" * 70, flush=True)

    result = {
        'endpoint': 'quote (bulk)',
        'batch_discovery': [],
        'max_working_batch_size': None,
        'stages': [],
        'throttle_rate_req_s': None,
        'no_throttle_up_to': None,
        'stopped_reason': None,
        'session_abort': False,
        'interrupted': False,
        'anomalies': [],
        'total_requests': 0,
    }

    all_symbols = list(fetcher.instruments.keys())
    if not all_symbols:
        result['stopped_reason'] = 'no instruments loaded — cannot run probe B'
        return result
    print(f"[PROBE B] instrument universe: {len(all_symbols)} NSE EQ symbols available", flush=True)

    # --- Phase 1: batch-size discovery --------------------------------------
    best_full = None       # largest size where n_returned == symbols actually sent
    best_any_200 = None    # largest size that returned HTTP 200 at all (even truncated)

    try:
        for target_size in QUOTE_BATCH_SIZES:
            if budget.exhausted():
                result['stopped_reason'] = 'hit HARD GLOBAL CAP during batch discovery'
                print(f"[PROBE B] {result['stopped_reason']} — stopping", flush=True)
                break

            n = min(target_size, len(all_symbols))
            if n < target_size:
                result['anomalies'].append(
                    f"instrument universe only has {len(all_symbols)} symbols; "
                    f"batch target {target_size} downsized to {n}")
            sample = random.sample(all_symbols, n)
            status, latency_ms, n_returned, note = _quote_request(fetcher, sample)
            budget.record()
            log_request('quote_batch_discovery', None, n, status, n_returned, latency_ms, note=note)

            entry = {'requested': n, 'http_status': status, 'n_returned': n_returned,
                     'latency_ms': round(latency_ms, 1)}
            result['batch_discovery'].append(entry)
            trunc_flag = ' *** TRUNCATED ***' if status == 200 and n_returned < n else ''
            print(f"[PROBE B] batch={n:4d}  ->  HTTP {status}   returned={n_returned}{trunc_flag}",
                  flush=True)

            if status in (401, 403):
                print(f"[PROBE B] *** HTTP {status} — SESSION ISSUE, aborting everything ***", flush=True)
                result['session_abort'] = True
                result['stopped_reason'] = f'auth_error_{status}'
                result['total_requests'] = budget.count
                return result

            if status == 429:
                result['throttle_rate_req_s'] = 'discovery'
                result['stopped_reason'] = f'429 during batch discovery at size {n}'
                print(f"[PROBE B] *** 429 during batch discovery at size {n} — "
                      f"STOPPING PROBE B, no retry ***", flush=True)
                break

            if status == 200:
                best_any_200 = n
                if n_returned == n:
                    best_full = n
                else:
                    result['anomalies'].append(
                        f"quote endpoint silently truncated batch: requested {n}, returned {n_returned}")

            time.sleep(QUOTE_DISCOVERY_SPACING)
    except KeyboardInterrupt:
        result['interrupted'] = True
        result['stopped_reason'] = 'keyboard_interrupt (during batch discovery)'
        result['total_requests'] = budget.count
        print("\n[PROBE B] KeyboardInterrupt during discovery — saving partial results", flush=True)
        return result

    if result['session_abort'] or result['interrupted']:
        result['total_requests'] = budget.count
        return result

    chosen = best_full or best_any_200
    result['max_working_batch_size'] = best_full
    if best_full is None and best_any_200 is not None:
        result['anomalies'].append(
            f"no batch size returned a FULL (non-truncated) result; falling back to "
            f"size {best_any_200} for the rate-test stage")

    if chosen is None or result['stopped_reason']:
        # every discovery request failed outright, or we already hit a 429 above —
        # nothing safe left to rate-test.
        if result['stopped_reason'] is None:
            result['stopped_reason'] = 'no working batch size found during discovery'
        result['total_requests'] = budget.count
        return result

    # --- Phase 2: rate-escalation at the chosen batch size -------------------
    print(f"\n[PROBE B] rate-escalation phase using batch size {chosen}", flush=True)
    stage_sent = 0

    for rate in PROBE_B_STAGES:
        interval = 1.0 / rate
        print(f"\n[PROBE B] --- stage {rate} req/s (sleep {interval:.2f}s), "
              f"{PROBE_B_STAGE_SECONDS}s budget --- rate-phase sent so far: "
              f"{stage_sent}/{PROBE_B_STAGE_CAP}", flush=True)
        stage_count = 0
        latencies = []
        hit_429 = False
        cap_hit = False
        stage_start = time.monotonic()

        try:
            while time.monotonic() - stage_start < PROBE_B_STAGE_SECONDS:
                if stage_sent >= PROBE_B_STAGE_CAP:
                    result['stopped_reason'] = (
                        f'no throttle found up to {rate} req/s '
                        f'(stopped early: hit {PROBE_B_STAGE_CAP}-request rate-test cap mid-stage)')
                    result['no_throttle_up_to'] = rate
                    cap_hit = True
                    print(f"[PROBE B] hit rate-test cap ({PROBE_B_STAGE_CAP} requests) — stopping", flush=True)
                    break
                if budget.exhausted():
                    result['stopped_reason'] = (
                        f'no throttle found up to {rate} req/s '
                        f'(stopped early: hit HARD GLOBAL CAP {budget.hard_cap})')
                    result['no_throttle_up_to'] = rate
                    cap_hit = True
                    print(f"[PROBE B] hit HARD GLOBAL CAP ({budget.hard_cap}) — stopping everything", flush=True)
                    break

                sample = random.sample(all_symbols, min(chosen, len(all_symbols)))
                status, latency_ms, n_returned, note = _quote_request(fetcher, sample)
                budget.record()
                stage_sent += 1
                stage_count += 1
                latencies.append(latency_ms)
                log_request('quote_rate', rate, chosen, status, n_returned, latency_ms, note=note)

                if status in (401, 403):
                    print(f"[PROBE B] *** HTTP {status} — SESSION ISSUE, aborting everything ***", flush=True)
                    result['session_abort'] = True
                    result['stopped_reason'] = f'auth_error_{status}'
                    result['stages'].append({
                        'rate': rate, 'requests_this_stage': stage_count,
                        'stage_phase_sent': stage_sent, 'hit_429': False,
                        'latency': _stage_latency_stats(latencies)})
                    result['total_requests'] = budget.count
                    return result

                if status == 429:
                    hit_429 = True
                    result['throttle_rate_req_s'] = rate
                    result['stopped_reason'] = f'429 at {rate} req/s'
                    print(f"[PROBE B] *** 429 at {rate} req/s after {stage_count} reqs this "
                          f"stage ({stage_sent} in rate-test phase) — STOPPING PROBE B, "
                          f"no retry ***", flush=True)
                    break

                if status == 200 and n_returned < chosen:
                    result['anomalies'].append(
                        f"truncation during rate-test at {rate} req/s: "
                        f"requested {chosen}, returned {n_returned}")

                time.sleep(interval)
        except KeyboardInterrupt:
            result['interrupted'] = True
            result['stopped_reason'] = 'keyboard_interrupt'
            result['stages'].append({
                'rate': rate, 'requests_this_stage': stage_count,
                'stage_phase_sent': stage_sent, 'hit_429': hit_429,
                'latency': _stage_latency_stats(latencies)})
            result['total_requests'] = budget.count
            print("\n[PROBE B] KeyboardInterrupt — saving partial stage results", flush=True)
            return result

        result['stages'].append({
            'rate': rate, 'requests_this_stage': stage_count,
            'stage_phase_sent': stage_sent, 'hit_429': hit_429,
            'latency': _stage_latency_stats(latencies)})

        if hit_429 or cap_hit:
            break

    if result['stopped_reason'] is None:
        result['no_throttle_up_to'] = PROBE_B_STAGES[-1]
        result['stopped_reason'] = f'no throttle found up to {PROBE_B_STAGES[-1]} req/s'

    result['total_requests'] = budget.count
    return result


# ---------------------------------------------------------------------------
# Login (mirrors LiveMonitor._auto_login, standalone to avoid importing the
# heavier monitor.py module for a read-only research probe).
# ---------------------------------------------------------------------------

def login():
    _load_dotenv()
    user = os.environ.get('ZERODHA_USER_ID', '')
    pwd = os.environ.get('ZERODHA_PASSWORD', '')
    totp = os.environ.get('ZERODHA_TOTP_SECRET', '')
    if not all([user, pwd, totp]):
        raise RuntimeError(
            'Missing ZERODHA_USER_ID / ZERODHA_PASSWORD / ZERODHA_TOTP_SECRET '
            '(set as env vars or in .env)')
    print(f"Logging in as {user} ...", flush=True)
    token = get_enctoken(user, pwd, totp)
    if not token:
        raise RuntimeError('get_enctoken returned an empty token')
    print("Login OK.", flush=True)
    return token


# ---------------------------------------------------------------------------
# Reporting
# ---------------------------------------------------------------------------

def _fmt_stage_line(st):
    lat = st['latency']
    sent_key = 'total_sent' if 'total_sent' in st else 'stage_phase_sent'
    return (f"    stage {st['rate']:>4} req/s: {st['requests_this_stage']:3d} reqs"
            f"{' [429]' if st['hit_429'] else ''}"
            f" (cumulative {st.get(sent_key, '-')})"
            f" | latency mean={lat.get('mean_ms', '-')}ms p50={lat.get('p50_ms', '-')}ms "
            f"p95={lat.get('p95_ms', '-')}ms max={lat.get('max_ms', '-')}ms n={lat.get('n', 0)}")


def build_report(results):
    lines = []
    lines.append("")
    lines.append("=" * 70)
    lines.append("RATE PROBE — FINAL REPORT")
    lines.append("=" * 70)
    lines.append(f"started:  {results.get('started_at')}")
    lines.append(f"finished: {results.get('finished_at')}")
    lines.append(f"total requests used: {results.get('total_requests_used')} / {HARD_GLOBAL_CAP} hard cap")
    if results.get('aborted'):
        lines.append(f"*** ABORTED: {results.get('abort_reason')} ***")

    hp = results.get('historical_probe')
    lines.append("\n--- Historical endpoint (/oms/instruments/historical/<token>/5minute) ---")
    if hp is None:
        lines.append("  not run")
    else:
        if hp.get('throttle_rate_req_s') is not None:
            lines.append(f"  THROTTLE FOUND at {hp['throttle_rate_req_s']} req/s -> {hp.get('stopped_reason')}")
        else:
            lines.append(f"  {hp.get('stopped_reason')}")
        lines.append(f"  total requests: {hp.get('total_requests')}")
        for st in hp.get('stages', []):
            lines.append(_fmt_stage_line(st))

    qp = results.get('quote_probe')
    lines.append("\n--- Bulk quote endpoint ---")
    if qp is None:
        lines.append("  not run")
    else:
        lines.append(f"  max working (non-truncated) batch size: {qp.get('max_working_batch_size')}")
        for d in qp.get('batch_discovery', []):
            lines.append(f"    requested={d['requested']:4d}  HTTP={d['http_status']}  "
                         f"returned={d['n_returned']}  latency={d['latency_ms']}ms")
        if qp.get('throttle_rate_req_s') is not None:
            lines.append(f"  THROTTLE FOUND at {qp['throttle_rate_req_s']} req/s -> {qp.get('stopped_reason')}")
        else:
            lines.append(f"  {qp.get('stopped_reason')}")
        lines.append(f"  total requests: {qp.get('total_requests')}")
        for st in qp.get('stages', []):
            lines.append(_fmt_stage_line(st))

    if results.get('anomalies'):
        lines.append("\n--- Anomalies ---")
        for a in results['anomalies']:
            lines.append(f"  - {a}")

    lines.append("=" * 70)
    return "\n".join(lines)


def _finalize(results, budget):
    results['finished_at'] = datetime.now().isoformat(timespec='seconds')
    results['total_requests_used'] = budget.count
    RESULTS_PATH.write_text(json.dumps(results, indent=2))
    print(build_report(results))
    print(f"\nFull results written to: {RESULTS_PATH}")
    print(f"Per-request log:         {LOG_PATH}")


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main():
    parser = argparse.ArgumentParser(
        description='Zerodha unofficial API rate-limit probe (read-only).')
    parser.add_argument(
        '--i-stopped-the-monitor', action='store_true', dest='confirmed',
        help='Required. Confirms the live_monitor service on this host has '
             'already been stopped. Zerodha web sessions are single-session: '
             'logging in here creates a new enctoken and will silently kick '
             'any other active session (i.e. the running monitor).')
    args = parser.parse_args()

    if not args.confirmed:
        print(
            "Refusing to run: pass --i-stopped-the-monitor after you have "
            "stopped the live_monitor service on this host.\n"
            "Logging in here creates a new Zerodha web session and will "
            "silently invalidate the monitor's current enctoken.",
            file=sys.stderr)
        sys.exit(2)

    results = {
        'started_at': datetime.now().isoformat(timespec='seconds'),
        'finished_at': None,
        'aborted': False,
        'abort_reason': None,
        'historical_probe': None,
        'quote_probe': None,
        'total_requests_used': 0,
        'anomalies': [],
    }
    budget = Budget(HARD_GLOBAL_CAP)

    try:
        token = login()
        fetcher = ZerodhaDataFetcher(token)  # instrument-list load: unauthenticated, not budget-counted
        if not fetcher.instruments:
            raise RuntimeError('instrument map failed to load — cannot resolve symbol tokens')

        symbols_a = [s for s in NIFTY_50 if s in fetcher.instruments]
        missing = sorted(set(NIFTY_50) - set(symbols_a))
        if missing:
            print(f"[WARN] {len(missing)} NIFTY-50 symbols not in instrument map, skipping: {missing}")
        if not symbols_a:
            raise RuntimeError('no NIFTY-50 symbols resolved in instrument map')

        # ---- Probe A ----
        probe_a = run_probe_a(fetcher, budget, symbols_a)
        results['historical_probe'] = probe_a

        if probe_a.get('interrupted'):
            results['aborted'] = True
            results['abort_reason'] = 'interrupted during probe A'
            return
        if probe_a.get('session_abort'):
            results['aborted'] = True
            results['abort_reason'] = f"probe A session issue: {probe_a.get('stopped_reason')}"
            return

        # ---- Cool-down ----
        print(f"\n[COOLDOWN] sleeping {COOLDOWN_SECONDS}s before probe B ...", flush=True)
        time.sleep(COOLDOWN_SECONDS)

        # ---- Probe B ----
        probe_b = run_probe_b(fetcher, budget)
        results['quote_probe'] = probe_b
        results['anomalies'].extend(probe_b.get('anomalies', []))

        if probe_b.get('interrupted'):
            results['aborted'] = True
            results['abort_reason'] = 'interrupted during probe B'
        elif probe_b.get('session_abort'):
            results['aborted'] = True
            results['abort_reason'] = f"probe B session issue: {probe_b.get('stopped_reason')}"

    except KeyboardInterrupt:
        print("\n[INTERRUPTED] Ctrl+C — saving partial results ...", flush=True)
        results['aborted'] = True
        results['abort_reason'] = results['abort_reason'] or 'keyboard_interrupt'
    except Exception as e:
        print(f"\n[ERROR] {e}", flush=True)
        results['aborted'] = True
        results['abort_reason'] = f'unexpected error: {e}'
    finally:
        _finalize(results, budget)


if __name__ == '__main__':
    main()
