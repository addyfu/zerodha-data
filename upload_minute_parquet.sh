#!/usr/bin/env bash
# Usage: bash upload_minute_parquet.sh <dir>
# Uploads minute_YYYY-MM-DD.parquet files to monthly releases minute-YYYY-MM.
# Needs gh and GH_TOKEN in the environment.
set -euo pipefail
DIR="${1:?usage: upload_minute_parquet.sh <dir>}"
REPO="${GITHUB_REPOSITORY:-addyfu/zerodha-data}"
shopt -s nullglob
for f in "$DIR"/minute_????-??-??.parquet; do
  base=$(basename "$f")
  month=${base#minute_}
  month=${month:0:7}
  tag="minute-$month"
  gh release view "$tag" --repo "$REPO" >/dev/null 2>&1 || \
    gh release create "$tag" --repo "$REPO" --latest=false --title "Minute history $month" \
      --notes "One Parquet file per trading day."
  gh release upload "$tag" "$f" --repo "$REPO" --clobber
done
