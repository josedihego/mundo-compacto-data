#!/usr/bin/env bash
# Alternative to GitHub Actions: run the pipeline on your own server.
#   crontab:  7 * * * *  /path/to/repo/scripts/run_hourly.sh /var/www/mundo-compacto >> /var/log/mundo.log 2>&1
# Arg 1: directory served by your web server (gets data/latest.json and lists/).
set -euo pipefail
cd "$(dirname "$0")/.."
PUBLISH_DIR="${1:?usage: run_hourly.sh PUBLISH_DIR}"

[ -d .venv ] || { python3 -m venv .venv && .venv/bin/pip install -q -r requirements.txt; }

status=0
.venv/bin/python -m pipeline.build || status=$?

if command -v gh >/dev/null && [ -n "${GH_TOKEN:-}" ]; then
  .venv/bin/python scripts/feed_issues.py state/feed_alerts.json || true
fi

if [ "$status" -eq 0 ]; then
  mkdir -p "$PUBLISH_DIR/data" "$PUBLISH_DIR/lists"
  cp data/latest.json "$PUBLISH_DIR/data/latest.json.tmp"
  mv "$PUBLISH_DIR/data/latest.json.tmp" "$PUBLISH_DIR/data/latest.json"
  cp config/stopwords.txt config/crime_terms.txt config/aliases.json config/feeds.json "$PUBLISH_DIR/lists/"
fi
exit "$status"
