"""
Sync Release DB
================
Nightly (19:45 IST Mon-Fri via the kite-release-sync systemd timer) job that:

  (a) pulls the latest GitHub release of addyfu/zerodha-data (tag "data-NNN",
      asset "zerodha_data.db", ~500-900MB) and ATOMICALLY replaces
      data/zerodha_data.db with it: download to a temp file on the SAME
      filesystem, verify size + SQLite header magic, then os.replace()
      (atomic rename). The monitor reads this file continuously during
      market hours -- a torn/partial write here would corrupt live paper
      trading, so nothing is ever swapped in without passing verification.

  (b) appends that day's minute-interval rows for ALL symbols from the
      freshly-swapped DB into a compressed per-day parquet archive
      data/minute_archive/minute_YYYY-MM-DD.parquet. Idempotent: only rows
      with datetime strictly newer than that archive file's current
      max(datetime) get appended, so re-running the same day twice (cron
      retry, manual re-run) never duplicates rows.

  (c) prune: nothing extra needed. The atomic replace in (a) IS the prune --
      the old full DB is gone the instant the rename lands. The parquet
      archive is the permanent per-day store and this script never deletes
      from it.

SAFETY GATES (every real run, in this order):
  1. Market hours (09:00-15:45 IST Mon-Fri): refuse to run. The monitor
     scans data/zerodha_data.db continuously in that window; swapping it
     then risks a read racing a rename. --dry-run is exempt (makes no
     filesystem changes, so there's nothing to race).
  2. Disk space (shutil.disk_usage): >=3GB free on the data/ filesystem, or
     abort loudly. Checked and reported even under --dry-run.
  3. Concurrency lock (pidfile at data/.sync_release_db.lock): refuse to run
     if another sync is already in flight. --dry-run is exempt.
  4. Post-download, pre-swap: downloaded size > 500MB AND the file starts
     with the SQLite header magic, or abort loudly, delete the temp file,
     and leave the existing DB completely untouched.

On ANY failure at any gate the existing DB is left byte-for-byte untouched,
the script prints one clear line explaining why, and exits nonzero.

This script never touches Zerodha/enctoken/Telegram credentials -- it only
talks to the public GitHub API + release CDN, and only ever writes to
data/zerodha_data.db (via the atomic swap) and data/minute_archive/*.parquet.

Usage:
    python sync_release_db.py              # real run (blocked during market hours)
    python sync_release_db.py --dry-run     # release lookup + disk check only,
                                             # downloads/writes NOTHING
    KITE_ROOT=/path/to/data-root python sync_release_db.py
"""
import sys
from pathlib import Path
import os

# ---------------------------------------------------------------------------
# root / .env -- identical convention to daily_report.py / parity_monitor.py /
# report_positions.py. This script doesn't need any secrets from .env today,
# but loading it keeps every live_monitor entrypoint consistent and gives
# KITE_ROOT the same override behavior everywhere.
# ---------------------------------------------------------------------------
_CODE_ROOT = Path(__file__).resolve().parents[2]
ROOT = Path(os.environ.get('KITE_ROOT', str(_CODE_ROOT)))
sys.path.insert(0, str(_CODE_ROOT))

_env_file = _CODE_ROOT / '.env'
if _env_file.exists():
    with open(_env_file) as _f:
        for _line in _f:
            _line = _line.strip()
            if _line and not _line.startswith('#') and '=' in _line:
                _key, _, _val = _line.partition('=')
                _val = _val.strip()
                if _val.startswith(('"', "'")) and _val.endswith(_val[0]):
                    _val = _val[1:-1]
                else:
                    _val = _val.split('#')[0].strip()
                os.environ.setdefault(_key.strip(), _val)

import argparse
import shutil
import sqlite3
import time
from datetime import datetime, time as dtime
from typing import List, Optional, Tuple

import requests

from kite.live_monitor.db_manager import GITHUB_API, GITHUB_REPO  # single source of truth for the repo/API URL

try:
    sys.stdout.reconfigure(encoding='utf-8')
except (AttributeError, ValueError):
    pass

# ---------------------------------------------------------------------------
# constants / paths
# ---------------------------------------------------------------------------
DATA_DIR = ROOT / 'data'
DB_PATH = DATA_DIR / 'zerodha_data.db'
TMP_PATH = DATA_DIR / 'zerodha_data.db.download'  # same dir as DB_PATH -> same filesystem -> atomic rename
ARCHIVE_DIR = DATA_DIR / 'minute_archive'
LOCK_PATH = DATA_DIR / '.sync_release_db.lock'

ASSET_NAME = 'zerodha_data.db'
MIN_FREE_BYTES = 3 * 1024 ** 3       # 3GB disk-safety gate
MIN_ASSET_BYTES = 500_000_000        # 500MB floor before a download is trusted enough to swap in
SQLITE_MAGIC = b'SQLite format 3\x00'  # first 16 bytes of every valid SQLite file
STALE_LOCK_SECONDS = 6 * 3600        # a real sync never legitimately takes this long


# ---------------------------------------------------------------------------
# safety gates
# ---------------------------------------------------------------------------
def is_market_hours(now: Optional[datetime] = None) -> bool:
    """Mon-Fri 09:00-15:45. Same naive-IST-wall-clock convention as
    monitor.py's is_market_hours() -- the deployment box's system tz is
    Asia/Kolkata, so no explicit tz conversion is done here either."""
    now = now or datetime.now()
    if now.weekday() >= 5:
        return False
    return dtime(9, 0) <= now.time() <= dtime(15, 45)


def check_disk_space(check_path: Path, min_bytes: int) -> Tuple[bool, int]:
    usage = shutil.disk_usage(check_path if check_path.exists() else check_path.parent)
    return usage.free >= min_bytes, usage.free


class SyncLock:
    """Pidfile-based mutual exclusion so two syncs can't overlap and race
    the atomic swap. Deliberately NOT fcntl.flock: this script's --dry-run
    path must be exercisable on any platform (including local Windows
    testing) without depending on a POSIX-only module, and a oneshot nightly
    systemd job has no need for kernel-level lock semantics -- a pidfile
    with a liveness check plus an age-based staleness backstop is enough.
    """

    def __init__(self, path: Path):
        self.path = path
        self.acquired = False

    @staticmethod
    def _pid_alive(pid: int) -> bool:
        try:
            os.kill(pid, 0)
            return True
        except ProcessLookupError:
            return False
        except OSError:
            # Includes PermissionError (process exists but owned by another
            # user -- treat as alive/locked, the conservative choice) vs.
            # other platform quirks; either way this is a rare edge case for
            # a single-user Oracle box, so fail toward "locked" here and let
            # the age-based staleness check in acquire() be the real backstop.
            return True

    def acquire(self) -> Optional[str]:
        """Returns None on success, or a human-readable reason string if
        another sync appears to hold the lock."""
        if self.path.exists():
            try:
                old_pid = int(self.path.read_text().strip())
            except (ValueError, OSError):
                old_pid = None
            try:
                age = time.time() - self.path.stat().st_mtime
            except OSError:
                age = 0.0
            stale = age > STALE_LOCK_SECONDS
            if old_pid is not None and not stale and self._pid_alive(old_pid):
                return (f"another sync (pid {old_pid}) appears to be running "
                        f"(lockfile {self.path}, age {age / 60:.0f}min)")
            # Stale or dead -- reclaim.
        try:
            self.path.parent.mkdir(parents=True, exist_ok=True)
            self.path.write_text(str(os.getpid()))
        except OSError as e:
            return f"could not create lockfile {self.path}: {e}"
        self.acquired = True
        return None

    def release(self):
        if self.acquired:
            try:
                self.path.unlink(missing_ok=True)
            except OSError:
                pass
            self.acquired = False


# ---------------------------------------------------------------------------
# GitHub release lookup (public repo -- no auth, no gh CLI)
# ---------------------------------------------------------------------------
def get_latest_release() -> Optional[dict]:
    """{'tag', 'published_at' (datetime), 'asset_name', 'download_url',
    'asset_size' (bytes, from the API response itself -- no extra HEAD
    request needed)} or None on any failure."""
    try:
        resp = requests.get(GITHUB_API, headers={'Accept': 'application/vnd.github+json'}, timeout=15)
    except requests.exceptions.RequestException as e:
        print(f"ERROR: GitHub API request to {GITHUB_API} failed: {e}")
        return None
    if resp.status_code != 200:
        print(f"ERROR: GitHub API returned HTTP {resp.status_code} for {GITHUB_API}")
        return None
    try:
        data = resp.json()
        tag = data['tag_name']
        published_at = datetime.fromisoformat(data['published_at'].replace('Z', '+00:00'))
    except (KeyError, ValueError, TypeError) as e:
        print(f"ERROR: malformed GitHub API response: {e}")
        return None

    assets = data.get('assets', []) or []
    asset = next((a for a in assets if a.get('name') == ASSET_NAME), None)
    if asset is None:
        # Naming drift fallback -- any *.db asset, same spirit as
        # db_manager.py's exact-match-first approach.
        asset = next((a for a in assets if (a.get('name') or '').endswith('.db')), None)
    if asset is None:
        print(f"ERROR: no {ASSET_NAME} (or *.db) asset in latest release {tag!r}")
        return None

    return {
        'tag': tag,
        'published_at': published_at,
        'asset_name': asset.get('name'),
        'download_url': asset.get('browser_download_url'),
        'asset_size': asset.get('size'),
    }


# ---------------------------------------------------------------------------
# download / verify / swap
# ---------------------------------------------------------------------------
def download_asset(url: str, tmp_path: Path) -> Tuple[bool, str]:
    """Streams the asset to tmp_path with redirect-following (requests
    follows redirects by default), which is all 'curl -L'/gh CLI would buy
    us here -- so no external binary dependency. On ANY failure the partial
    tmp file is removed and the existing DB is never touched."""
    try:
        downloaded = 0
        last_pct = -1
        with requests.get(url, stream=True, timeout=300) as resp:
            resp.raise_for_status()
            total = int(resp.headers.get('content-length', 0))
            with open(tmp_path, 'wb') as f:
                for chunk in resp.iter_content(chunk_size=8 * 1024 * 1024):
                    f.write(chunk)
                    downloaded += len(chunk)
                    if total:
                        pct = int(downloaded / total * 100 // 10) * 10
                        if pct > last_pct:
                            print(f"  download: {pct}% ({downloaded / 1e6:.0f}/{total / 1e6:.0f} MB)")
                            last_pct = pct
        return True, f"downloaded {downloaded / 1e6:.0f} MB to {tmp_path.name}"
    except Exception as e:
        try:
            tmp_path.unlink(missing_ok=True)
        except OSError:
            pass
        return False, f"download failed ({e}) -- temp file removed, existing DB untouched"


def verify_db_file(path: Path) -> Tuple[bool, str]:
    """Size + SQLite header magic. Both must pass before this file is
    trusted enough to become the live DB."""
    try:
        size = path.stat().st_size
    except OSError as e:
        return False, f"could not stat downloaded file: {e}"
    if size <= MIN_ASSET_BYTES:
        return False, f"size {size / 1e6:.1f}MB <= {MIN_ASSET_BYTES / 1e6:.0f}MB floor -- refusing to swap"
    try:
        with open(path, 'rb') as f:
            magic = f.read(16)
    except OSError as e:
        return False, f"could not read file for header check: {e}"
    if magic != SQLITE_MAGIC:
        return False, f"not a valid SQLite file (header magic was {magic!r})"
    return True, f"size {size / 1e6:.1f}MB, valid SQLite header"


def atomic_swap(tmp_path: Path, final_path: Path) -> Tuple[bool, str]:
    """os.replace() is an atomic rename on the same filesystem (POSIX
    rename(2); Windows ReplaceFile via CPython's os.replace) -- the monitor
    never sees a partially-written file, only the old version or the new
    one, never something in between."""
    try:
        os.replace(str(tmp_path), str(final_path))
        return True, f"swapped into {final_path}"
    except OSError as e:
        return False, f"atomic replace failed ({e}) -- old DB may still be intact if the rename never started"


def verify_after_swap(db_path: Path) -> List[str]:
    """Read-only sanity check on the DB that's now live: max(datetime) and
    row count per interval."""
    lines: List[str] = []
    try:
        conn = sqlite3.connect(f"file:{db_path}?mode=ro", uri=True)
        try:
            rows = conn.execute(
                "SELECT interval, MAX(datetime), COUNT(*) FROM ohlcv GROUP BY interval"
            ).fetchall()
        finally:
            conn.close()
        if not rows:
            lines.append("  (ohlcv table has zero rows)")
        for interval, max_dt, count in rows:
            lines.append(f"  interval={interval!r}: max(datetime)={max_dt}  rows={count:,}")
    except sqlite3.Error as e:
        lines.append(f"  WARNING: post-swap verification query failed: {e}")
    return lines


# ---------------------------------------------------------------------------
# minute-archive append (idempotent per calendar day)
# ---------------------------------------------------------------------------
def append_minute_archive(db_path: Path, archive_dir: Path, date_str: str) -> str:
    """Appends date_str's minute-interval rows for ALL symbols from db_path
    into archive_dir/minute_{date_str}.parquet.

    Idempotency: if that day's archive file already exists, only rows with
    datetime STRICTLY newer than the file's current max(datetime) are
    pulled from the DB and appended -- re-running this function twice on
    the same day (retry, manual re-run) never duplicates a row. A
    belt-and-suspenders drop_duplicates(subset=[symbol, datetime]) covers
    the rare case of two rows sharing the exact same watermark timestamp.

    datetime stays a plain string throughout (matches the DB's own storage
    format, e.g. '2026-06-16 15:25:00+05:30') rather than being parsed --
    the format is fixed-width and lexicographically sortable, so string
    comparison is both correct and avoids any timezone-parsing pitfalls.
    """
    import pandas as pd

    archive_dir.mkdir(parents=True, exist_ok=True)
    archive_path = archive_dir / f"minute_{date_str}.parquet"

    existing = None
    watermark = None
    if archive_path.exists():
        try:
            existing = pd.read_parquet(archive_path)
            if len(existing) and 'datetime' in existing.columns:
                watermark = existing['datetime'].max()
        except Exception as e:
            print(f"  WARNING: could not read existing archive {archive_path} ({e}) -- "
                  f"treating it as absent for this run")
            existing = None

    conn = sqlite3.connect(f"file:{db_path}?mode=ro", uri=True)
    try:
        query = ("SELECT symbol, datetime, open, high, low, close, volume, oi "
                  "FROM ohlcv WHERE interval='minute' AND substr(datetime,1,10)=?")
        params: list = [date_str]
        if watermark is not None:
            query += " AND datetime > ?"
            params.append(watermark)
        new_rows = pd.read_sql(query, conn, params=params)
    finally:
        conn.close()

    # Nothing new past the watermark -- skip the rewrite entirely (an
    # unchanged multi-MB parquet file has no reason to be re-encoded).
    if new_rows.empty:
        if existing is not None and len(existing):
            return f"no new rows past watermark {watermark!r} -- archive unchanged ({len(existing)} rows)"
        return f"no minute rows found for {date_str} in the DB -- archive not created"

    if existing is not None and len(existing):
        combined = pd.concat([existing, new_rows], ignore_index=True)
    else:
        combined = new_rows

    combined = combined.drop_duplicates(subset=['symbol', 'datetime'], keep='last')
    combined = combined.sort_values(['symbol', 'datetime']).reset_index(drop=True)
    combined.to_parquet(archive_path, engine='pyarrow', compression='zstd', index=False)

    return (f"{archive_path.name}: {len(new_rows)} new row(s) appended, {len(combined)} total rows, "
            f"{archive_path.stat().st_size / 1e6:.1f}MB on disk")


def archive_dir_total_size(archive_dir: Path) -> int:
    if not archive_dir.exists():
        return 0
    return sum(p.stat().st_size for p in archive_dir.glob('*.parquet'))


# ---------------------------------------------------------------------------
# main
# ---------------------------------------------------------------------------
def main():
    parser = argparse.ArgumentParser(
        description=f'Sync data/zerodha_data.db from the latest {GITHUB_REPO} GitHub release, '
                     'then archive the day\'s minute bars to parquet.')
    parser.add_argument('--dry-run', action='store_true',
                         help='Look up the latest release, print its tag/asset size, and check disk '
                              'space -- downloads and writes NOTHING. Exempt from the market-hours '
                              'and concurrency-lock gates (it makes no changes, so nothing to guard).')
    args = parser.parse_args()

    print("=" * 78)
    print(f"SYNC RELEASE DB{'  [DRY RUN]' if args.dry_run else ''} "
          f"-- {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    print("=" * 78)

    # Gate 1: market hours (real runs only -- dry-run changes nothing, so it's
    # always safe to run for a status check even mid-session).
    if not args.dry_run and is_market_hours():
        print("ABORT: refusing to run 09:00-15:45 IST Mon-Fri (market hours) -- the monitor "
              "reads data/zerodha_data.db continuously in this window. Re-run after close, "
              "or via the 19:45 IST kite-release-sync.timer.")
        sys.exit(1)

    # Gate 2: disk space -- always checked and reported (dry-run included per spec),
    # only fatal on a real run.
    ok_disk, free_bytes = check_disk_space(DATA_DIR, MIN_FREE_BYTES)
    print(f"Disk free on {DATA_DIR}: {free_bytes / 1e9:.2f} GB "
          f"({'OK' if ok_disk else f'BELOW {MIN_FREE_BYTES / 1e9:.0f}GB FLOOR'})")
    if not args.dry_run and not ok_disk:
        print(f"ABORT: less than {MIN_FREE_BYTES / 1e9:.0f}GB free -- refusing to download a "
              f"~500-900MB asset.")
        sys.exit(1)

    # Release lookup -- needed by both dry-run and real run.
    release = get_latest_release()
    if release is None:
        print("ABORT: could not determine the latest GitHub release (see error above).")
        sys.exit(1)
    size_mb = (release['asset_size'] or 0) / 1e6
    print(f"Latest release: {release['tag']}  (published {release['published_at'].isoformat()})")
    print(f"Asset: {release['asset_name']}  {size_mb:.0f} MB")
    print(f"URL: {release['download_url']}")

    if args.dry_run:
        print("-" * 78)
        print("DRY RUN complete -- downloaded nothing, DB untouched, archive untouched.")
        print("=" * 78)
        return

    # Gate 3: concurrency lock (real runs only).
    lock = SyncLock(LOCK_PATH)
    lock_reason = lock.acquire()
    if lock_reason:
        print(f"ABORT: {lock_reason}")
        sys.exit(1)

    try:
        ok, msg = download_asset(release['download_url'], TMP_PATH)
        print(f"Download: {msg}")
        if not ok:
            print("ABORT: download failed -- existing DB untouched.")
            sys.exit(1)

        # Gate 4: post-download verification.
        ok, msg = verify_db_file(TMP_PATH)
        print(f"Verify: {msg}")
        if not ok:
            try:
                TMP_PATH.unlink(missing_ok=True)
            except OSError:
                pass
            print("ABORT: verification failed -- existing DB untouched, temp file removed.")
            sys.exit(1)

        ok, msg = atomic_swap(TMP_PATH, DB_PATH)
        print(f"Swap: {msg}")
        if not ok:
            print("ABORT: atomic swap failed.")
            sys.exit(1)

        print("Post-swap verification:")
        for line in verify_after_swap(DB_PATH):
            print(line)

        date_str = datetime.now().strftime('%Y-%m-%d')
        try:
            archive_msg = append_minute_archive(DB_PATH, ARCHIVE_DIR, date_str)
            print(f"Archive: {archive_msg}")
        except Exception as e:
            # The DB swap already succeeded and is the safety-critical part;
            # an archive failure is logged loudly but must not be reported as
            # an overall sync failure (exit 0) -- the monitor is fine either way.
            print(f"WARNING: minute-archive append failed ({e}) -- DB swap already "
                  f"succeeded and is unaffected.")

        total_archive = archive_dir_total_size(ARCHIVE_DIR)
        print(f"Archive dir total size: {total_archive / 1e6:.1f} MB ({ARCHIVE_DIR})")
    finally:
        lock.release()

    print("=" * 78)
    print("SYNC COMPLETE")
    print("=" * 78)


if __name__ == '__main__':
    main()
