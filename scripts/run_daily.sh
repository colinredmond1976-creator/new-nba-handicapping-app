#!/bin/bash
set -euo pipefail

PROJECT_DIR="/Users/credmond/Documents/Documents - Colin’s Mac Mini/ChatGPT/New NBA Handicapping App"
export TZ="America/Toronto"
cd "$PROJECT_DIR"

if [ "$(git branch --show-current)" != "main" ]; then
  printf '%s\n' 'Daily pipeline requires the main branch.' >&2
  exit 1
fi

source .venv/bin/activate
export PYTHONPATH="$PROJECT_DIR/src${PYTHONPATH:+:$PYTHONPATH}"
.venv/bin/python -m nba_handicap.cli --date "$(date +%Y%m%d)"
git add -- data/dashboard_payload.json
if ! git diff --cached --quiet -- data/dashboard_payload.json; then
  git commit --only -m "auto: daily pipeline update $(date +%Y-%m-%d)" -- data/dashboard_payload.json
fi
git push origin main
