#!/usr/bin/env bash
set -euo pipefail

PR_HOST="${PR_HOST:-0.0.0.0}"
PR_PORT="${PR_PORT:-8101}"
OUTREACH_HOST="${OUTREACH_HOST:-0.0.0.0}"
OUTREACH_PORT="${OUTREACH_PORT:-8102}"
PYTHON_BIN="${PYTHON_BIN:-./venv/bin/python}"
PR_INGEST_ENABLE_SCHEDULER="${PR_INGEST_ENABLE_SCHEDULER:-true}"
OUTREACH_SCHEDULE_ENABLE_RUNNER="${OUTREACH_SCHEDULE_ENABLE_RUNNER:-true}"

INGEST_ENABLE_SCHEDULER="${PR_INGEST_ENABLE_SCHEDULER}" \
"${PYTHON_BIN}" -m uvicorn pr_monitor_app.main:app --host "${PR_HOST}" --port "${PR_PORT}" &
PR_PID=$!

SCHEDULE_ENABLE_RUNNER="${OUTREACH_SCHEDULE_ENABLE_RUNNER}" \
"${PYTHON_BIN}" -m uvicorn outreach_app.main:app --host "${OUTREACH_HOST}" --port "${OUTREACH_PORT}" &
OUTREACH_PID=$!

cleanup() {
  kill "${PR_PID}" "${OUTREACH_PID}" 2>/dev/null || true
}
trap cleanup EXIT INT TERM

echo "pr_monitor_app running on http://${PR_HOST}:${PR_PORT}"
echo "outreach_app running on http://${OUTREACH_HOST}:${OUTREACH_PORT}"

wait -n "${PR_PID}" "${OUTREACH_PID}"
