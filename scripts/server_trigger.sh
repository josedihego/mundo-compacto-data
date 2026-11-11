#!/usr/bin/env bash
# Starts the public Mundo Compacto pipeline on GitHub Actions (GitHub cron is unreliable).
# Token: fine-grained PAT, repo josedihego/mundo-compacto-data only, "Actions: read and write".
set -euo pipefail
TOKEN_FILE="$HOME/.config/mundo/token"
[ -s "$TOKEN_FILE" ] || { echo "$(date -u +%FT%TZ) no token yet"; exit 0; }
code=$(curl -s -o /dev/null -w "%{http_code}" -X POST \
  -H "Authorization: Bearer $(tr -d "[:space:]" < "$TOKEN_FILE")" -H "Accept: application/vnd.github+json" \
  https://api.github.com/repos/josedihego/mundo-compacto-data/actions/workflows/hourly.yml/dispatches \
  -d "{\"ref\":\"main\"}")
echo "$(date -u +%FT%TZ) dispatch HTTP $code"
[ "$code" = 204 ]
