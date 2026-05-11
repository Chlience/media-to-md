#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR=$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)
BACKEND_HOST=${MEDIA_TO_MD_BACKEND_HOST:-0.0.0.0}
BACKEND_PORT=${MEDIA_TO_MD_BACKEND_PORT:-8001}
FRONTEND_HOST=${MEDIA_TO_MD_FRONTEND_HOST:-0.0.0.0}
FRONTEND_PORT=${MEDIA_TO_MD_FRONTEND_PORT:-5173}
LOG_DIR=${MEDIA_TO_MD_DEV_LOG_DIR:-${ROOT_DIR}/.data/dev-logs}

usage() {
  cat <<'MSG'
Usage:
  ./scripts/start-dev.sh [backend-port] [frontend-port]
  ./scripts/start-dev.sh --backend-port 8001 --frontend-port 5173

Defaults:
  backend port:  8001
  frontend port: 5173

Environment overrides:
  MEDIA_TO_MD_BACKEND_HOST
  MEDIA_TO_MD_BACKEND_PORT
  MEDIA_TO_MD_FRONTEND_HOST
  MEDIA_TO_MD_FRONTEND_PORT
  MEDIA_TO_MD_API_BASE_URL
  MEDIA_TO_MD_DEV_LOG_DIR
  MEDIA_TO_MD_BACKEND_LOG
  MEDIA_TO_MD_FRONTEND_LOG
MSG
}

die() {
  printf 'Error: %s\n' "$1" >&2
  usage >&2
  exit 2
}

require_value() {
  local option=$1
  local value=${2:-}
  [[ -n "${value}" ]] || die "${option} requires a value"
}

positional=()
while [[ $# -gt 0 ]]; do
  case "$1" in
    --backend-port)
      require_value "$1" "${2:-}"
      BACKEND_PORT=$2
      shift 2
      ;;
    --backend-port=*)
      BACKEND_PORT=${1#*=}
      shift
      ;;
    --frontend-port)
      require_value "$1" "${2:-}"
      FRONTEND_PORT=$2
      shift 2
      ;;
    --frontend-port=*)
      FRONTEND_PORT=${1#*=}
      shift
      ;;
    --backend-host)
      require_value "$1" "${2:-}"
      BACKEND_HOST=$2
      shift 2
      ;;
    --backend-host=*)
      BACKEND_HOST=${1#*=}
      shift
      ;;
    --frontend-host)
      require_value "$1" "${2:-}"
      FRONTEND_HOST=$2
      shift 2
      ;;
    --frontend-host=*)
      FRONTEND_HOST=${1#*=}
      shift
      ;;
    -h|--help)
      usage
      exit 0
      ;;
    --)
      shift
      positional+=("$@")
      break
      ;;
    -* )
      die "unknown option: $1"
      ;;
    *)
      positional+=("$1")
      shift
      ;;
  esac
done

case ${#positional[@]} in
  0)
    ;;
  1)
    BACKEND_PORT=${positional[0]}
    ;;
  2)
    BACKEND_PORT=${positional[0]}
    FRONTEND_PORT=${positional[1]}
    ;;
  *)
    die "too many positional arguments"
    ;;
esac

[[ "${BACKEND_PORT}" =~ ^[0-9]+$ ]] || die "backend port must be numeric"
[[ "${FRONTEND_PORT}" =~ ^[0-9]+$ ]] || die "frontend port must be numeric"

API_BASE_URL=${MEDIA_TO_MD_API_BASE_URL:-http://localhost:${BACKEND_PORT}/api}
BACKEND_LOG=${MEDIA_TO_MD_BACKEND_LOG:-${LOG_DIR}/backend-${BACKEND_PORT}.log}
FRONTEND_LOG=${MEDIA_TO_MD_FRONTEND_LOG:-${LOG_DIR}/frontend-${FRONTEND_PORT}.log}

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
  exec npm run dev -- --host "${FRONTEND_HOST}" --port "${FRONTEND_PORT}"
) >> "${FRONTEND_LOG}" 2>&1 &
frontend_pid=$!

cat <<MSG
Media-to-MD dev servers started
Backend:  host=${BACKEND_HOST} port=${BACKEND_PORT} url=http://localhost:${BACKEND_PORT} -> ${BACKEND_LOG}
Frontend: host=${FRONTEND_HOST} port=${FRONTEND_PORT} url=http://localhost:${FRONTEND_PORT} -> ${FRONTEND_LOG}
API URL:  ${API_BASE_URL}
Press Ctrl-C to stop both processes
MSG

set +e
wait -n "${backend_pid}" "${frontend_pid}"
exit_code=$?
set -e

printf 'A dev server stopped, shutting down the other process\n' >&2
exit "${exit_code}"
