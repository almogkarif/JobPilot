#!/usr/bin/env bash
set -euo pipefail
cd "$(dirname "$0")"
if [ ! -d .venv ]; then
  python3 -m venv .venv
  source .venv/bin/activate
  python -m pip install --upgrade pip
  python -m pip install -r requirements.txt
else
  source .venv/bin/activate
fi
[ -f .env ] && set -a && source .env && set +a
if [ "${JOBPILOT_AGENT_TOKEN:-change-me}" = "change-me" ]; then
  echo "The Agent token is still the insecure default."
  echo "Stop the running server and run ./start.sh once to generate a secure shared token."
  exit 1
fi
JOBPILOT_PROFILE_DIR="${JOBPILOT_BROWSER_PROFILE:-$(pwd)/agent/browser-profile}"
JOBPILOT_LOCK="${JOBPILOT_PROFILE_DIR}/SingletonLock"
if [ -L "${JOBPILOT_LOCK}" ]; then
  JOBPILOT_LOCK_TARGET="$(readlink "${JOBPILOT_LOCK}" || true)"
  JOBPILOT_BROWSER_PID="${JOBPILOT_LOCK_TARGET##*-}"
  if [ -n "${JOBPILOT_BROWSER_PID}" ] && kill -0 "${JOBPILOT_BROWSER_PID}" 2>/dev/null; then
    echo "The JobPilot browser profile is already open in PID ${JOBPILOT_BROWSER_PID}."
    echo "Close the existing 'Chrome for Testing' window, then run ./start-agent.sh again."
    exit 1
  fi
  rm -f "${JOBPILOT_PROFILE_DIR}/SingletonLock" "${JOBPILOT_PROFILE_DIR}/SingletonCookie" "${JOBPILOT_PROFILE_DIR}/SingletonSocket"
  echo "Removed stale Chromium profile locks."
fi
python -m playwright install chromium
exec python -m agent.run_agent
