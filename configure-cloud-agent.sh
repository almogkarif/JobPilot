#!/usr/bin/env bash
set -euo pipefail
cd "$(dirname "$0")"

BASE_URL="${1:-}"
if [ -z "$BASE_URL" ]; then
  read -r -p "JobPilot cloud URL (https://...): " BASE_URL
fi
BASE_URL="${BASE_URL%/}"
if [[ ! "$BASE_URL" =~ ^https?:// ]]; then
  echo "The JobPilot URL must start with https:// or http://"
  exit 1
fi

read -r -s -p "Paste the one-time Agent token: " AGENT_TOKEN
echo
if [[ ! "$AGENT_TOKEN" =~ ^jp_agent_ ]]; then
  echo "That does not look like a JobPilot device token (expected jp_agent_...)."
  exit 1
fi

[ -f .env ] || cp .env.example .env
python3 - "$BASE_URL" "$AGENT_TOKEN" <<'PY'
from pathlib import Path
import sys

path = Path('.env')
base_url, token = sys.argv[1:3]
lines = path.read_text().splitlines() if path.exists() else []
updates = {
    'JOBPILOT_BASE_URL': base_url,
    'JOBPILOT_AGENT_TOKEN': token,
}
seen = set()
out = []
for line in lines:
    key = line.split('=', 1)[0].strip() if '=' in line and not line.lstrip().startswith('#') else ''
    if key in updates:
        if key not in seen:
            out.append(f'{key}={updates[key]}')
            seen.add(key)
    else:
        out.append(line)
for key, value in updates.items():
    if key not in seen:
        out.append(f'{key}={value}')
path.write_text('\n'.join(out).rstrip() + '\n')
PY
chmod 600 .env 2>/dev/null || true

echo "Cloud Agent configured for: $BASE_URL"
echo "The token was written to .env and was not placed in the shell command history."
echo "Start it with: ./start-agent.sh"
