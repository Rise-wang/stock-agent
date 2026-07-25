#!/usr/bin/env bash
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
DATE_ARG="${1:-}"
WATCHLIST_ARG="${WATCHLIST:-}"
WATCHLIST_FILE_ARG="${WATCHLIST_FILE:-}"

CMD=(python3 "$ROOT/scripts/daily_report.py")

if [[ -n "$DATE_ARG" ]]; then
  CMD+=("$DATE_ARG")
fi
if [[ -n "$WATCHLIST_ARG" ]]; then
  CMD+=(--watchlist "$WATCHLIST_ARG")
fi
if [[ -n "$WATCHLIST_FILE_ARG" ]]; then
  CMD+=(--watchlist-file "$WATCHLIST_FILE_ARG")
fi

REPORT_PATH="$("${CMD[@]}")"

JSON_PATH="${REPORT_PATH%.md}.json"
python3 "$ROOT/scripts/validate_report.py" "$JSON_PATH"

echo "$REPORT_PATH"
echo "$JSON_PATH"
