#!/usr/bin/env bash
set -euo pipefail
cd "$(dirname "$0")"
JOBPILOT_START_PORT="${JOBPILOT_PORT:-8000}"
if command -v lsof >/dev/null 2>&1; then
  JOBPILOT_LISTENER="$(lsof -tiTCP:"${JOBPILOT_START_PORT}" -sTCP:LISTEN 2>/dev/null | head -n 1 || true)"
  if [ -n "${JOBPILOT_LISTENER}" ]; then
    echo "JobPilot cannot start: port ${JOBPILOT_START_PORT} is already in use by PID ${JOBPILOT_LISTENER}."
    echo "Open http://127.0.0.1:${JOBPILOT_START_PORT} if JobPilot is already running."
    echo "Alternatively run on another port: JOBPILOT_PORT=8001 ./start.sh"
    exit 1
  fi
fi
if [ ! -d .venv ]; then
  python3 -m venv .venv
fi
source .venv/bin/activate
python -m pip install --upgrade pip
python -m pip install -r requirements.txt
[ -f .env ] || cp .env.example .env
if grep -q '^JOBPILOT_AGENT_TOKEN=change-me$' .env; then
  if command -v openssl >/dev/null 2>&1; then
    JOBPILOT_NEW_TOKEN="$(openssl rand -hex 32)"
    awk -v token="${JOBPILOT_NEW_TOKEN}" '
      /^JOBPILOT_AGENT_TOKEN=change-me$/ { print "JOBPILOT_AGENT_TOKEN=" token; next }
      { print }
    ' .env > .env.jobpilot-new
    mv .env.jobpilot-new .env
    echo "Generated a secure local Agent token in .env."
  else
    echo "Warning: JOBPILOT_AGENT_TOKEN is still set to the insecure default 'change-me'."
  fi
fi
exec python run.py
