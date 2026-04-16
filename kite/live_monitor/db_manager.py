# kite/live_monitor/db_manager.py
"""
DBManager
=========
Manages the local SQLite DB of OHLCV data.
"""
import os
import logging
import requests
from pathlib import Path
from datetime import datetime, timezone
from typing import Optional

logger = logging.getLogger(__name__)

DB_PATH = Path(__file__).parent.parent.parent / 'data' / 'zerodha_data.db'
GITHUB_REPO = 'addyfu/zerodha-data'
GITHUB_API = f'https://api.github.com/repos/{GITHUB_REPO}/releases/latest'


class DBManager:
    def __init__(self, db_path: Path = DB_PATH):
        self.db_path = db_path
        self.db_path.parent.mkdir(parents=True, exist_ok=True)

    def _get_latest_release_info(self) -> Optional[dict]:
        """Return {'tag': str, 'published_at': datetime, 'download_url': str} or None."""
        try:
            resp = requests.get(
                GITHUB_API,
                headers={'Accept': 'application/vnd.github+json'},
                timeout=15
            )
            if resp.status_code != 200:
                logger.warning(f"GitHub API returned {resp.status_code}")
                return None
            data = resp.json()
            tag = data['tag_name']
            published_at = datetime.fromisoformat(
                data['published_at'].replace('Z', '+00:00')
            )
            # Find zerodha_data.db asset
            download_url = None
            for asset in data.get('assets', []):
                if asset['name'] == 'zerodha_data.db':
                    download_url = asset['browser_download_url']
                    break
            if not download_url:
                logger.warning("No zerodha_data.db asset in latest release")
                return None
            return {'tag': tag, 'published_at': published_at, 'download_url': download_url}
        except Exception as e:
            logger.error(f"Failed to fetch release info: {e}")
            return None

    def _download_release(self, release: dict) -> bool:
        """Download DB from a pre-fetched release dict. Returns True on success."""
        url = release['download_url']
        logger.info(f"Downloading DB from {url} ...")
        tmp_path = self.db_path.with_suffix('.tmp')

        try:
            with requests.get(url, stream=True, timeout=300) as resp:
                resp.raise_for_status()
                total = int(resp.headers.get('content-length', 0))
                downloaded = 0
                last_pct_logged = -1
                with open(tmp_path, 'wb') as f:
                    for chunk in resp.iter_content(chunk_size=8 * 1024 * 1024):
                        f.write(chunk)
                        downloaded += len(chunk)
                        if total:
                            pct = downloaded / total * 100
                            pct_bucket = int(pct // 10) * 10
                            if pct_bucket > last_pct_logged:
                                logger.info(f"  Download: {pct:.0f}% ({downloaded/1e6:.0f}/{total/1e6:.0f} MB)")
                                last_pct_logged = pct_bucket

            # Atomic replace
            tmp_path.replace(self.db_path)
            logger.info(f"DB downloaded to {self.db_path} ({self.db_path.stat().st_size/1e6:.0f} MB)")
            return True

        except Exception as e:
            logger.error(f"Download failed: {e}")
            try:
                tmp_path.unlink(missing_ok=True)
            except OSError:
                pass
            return False

    def ensure_seeded(self) -> bool:
        """Check if local DB needs update and download if so. Returns True if DB is ready."""
        if not self.db_path.exists():
            logger.info("Local DB not found — will download from GitHub")
            release = self._get_latest_release_info()
            if release is None:
                logger.error("DB download failed and no local DB exists — cannot proceed")
                return False
            return self._download_release(release)

        release = self._get_latest_release_info()
        if release is None:
            logger.warning("Could not check GitHub release — using existing local DB")
            return True

        local_mtime = datetime.fromtimestamp(self.db_path.stat().st_mtime, tz=timezone.utc)
        if release['published_at'] > local_mtime:
            logger.info(f"GitHub release {release['tag']} is newer — updating DB")
            self._download_release(release)
        else:
            logger.info(f"Local DB is up to date (release: {release['tag']})")
        return self.db_path.exists()
