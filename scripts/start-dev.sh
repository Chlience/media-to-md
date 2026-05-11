#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR=$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)
BACKEND_HOST=${MEDIA_TO_MD_BACKEND_HOST:-0.0.0.0}
BACKEND_PORT=${MEDIA_TO_MD_BACKEND_PORT:-8001}
API_BASE_URL=${MEDIA_TO_MD_API_BASE_URL:-http://localhost:${BACKEND_PORT}/api}
LOG_DIR=${MEDIA_TO_MD_DEV_LOG_DIR:-${ROOT_DIR}/.data/dev-logs}
BACKEND_LOG=${MEDIA_TO_MD_BACKEND_LOG:-${LOG_DIR}/backend-${BACKEND_PORT}.log}
FRONTEND_LOG=${MEDIA_TO_MD_FRONTEND_LOG:-${LOG_DIR}/frontend.log}

backend_pid=""
frontend_pid=""

cleanup() {
  trap - INT TERM EXIT
  for pid in "${backend_pid}" "${frontend_pid}"; do
    if [[ -n "${pid}" ]] && kill -0 "${pid}" 2>/dev/null; then
      kill "${pid}" 2>/dev/null || true
    fi
  done
  wait "${backend_pid}" "${frontend_pid}" 2>/dev/null || true
}

mkdir -p "${LOG_DIR}"
: > "${BACKEND_LOG}"
: > "${FRONTEND_LOG}"

trap cleanup INT TERM EXIT

(
  cd "${ROOT_DIR}/backend"
  exec uv run uvicorn app.main:app --host "${BACKEND_HOST}" --port "${BACKEND_PORT}"
) >> "${BACKEND_LOG}" 2>&1 &
backend_pid=$!

(
  cd "${ROOT_DIR}/frontend"
  export MEDIA_TO_MD_API_BASE_URL="${API_BASE_URL}"
  exec npm run dev
) >> "${FRONTEND_LOG}" 2>&1 &
frontend_pid=$!

cat <<MSG
Media-to-MD dev servers started
Backend:  http://${BACKEND_HOST}:${BACKEND_PORT}  -> ${BACKEND_LOG}
Frontend: Vite default port             -> ${FRONTEND_LOG}
API URL:  ${API_BASE_URL}
Press Ctrl-C to stop both processes
MSG

set +e
wait -n "${backend_pid}" "${frontend_pid}"
exit_code=$?
set -e

printf 'A dev server stopped, shutting down the other process\n' >&2
exit "${exit_code}"
