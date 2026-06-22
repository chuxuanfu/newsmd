#!/bin/zsh
set -u

export PATH="/opt/homebrew/bin:/usr/local/bin:/usr/bin:/bin:/usr/sbin:/sbin"

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
PROJECT_ROOT="$(cd "${SCRIPT_DIR}/.." && pwd)"

FETCHER="${PROJECT_ROOT}/scripts/rss_news_fetcher.py"
PYTHON="${NEWSMD_PYTHON:-${PROJECT_ROOT}/.venv/bin/python3}"
NEWS_RAW="${NEWSMD_OUTPUT_ROOT:-${PROJECT_ROOT}/news_raw}"
LOG_DIR="${NEWSMD_LOG_DIR:-${PROJECT_ROOT}/logs}"
LOCK_DIR="${PROJECT_ROOT}/run/news_pipeline.lock"
OLLAMA_URL="${NEWSMD_OLLAMA_URL:-http://localhost:11434}"
MODEL="${NEWSMD_MODEL:-qwen3.6:35b}"
TOPICS="${NEWSMD_TOPICS:-headlines tech finance}"
MAX_PER_FEED="${NEWSMD_MAX_PER_FEED:-10}"
TOTAL_LIMIT="${NEWSMD_TOTAL_LIMIT:-}"

mkdir -p "${LOG_DIR}" "${PROJECT_ROOT}/run" "${NEWS_RAW}"

slot_for_now() {
  local hour
  hour="$(date +%H)"
  if [ "${hour}" -lt 14 ]; then
    echo "8am"
  else
    echo "8pm"
  fi
}

RUN_DATE="${NEWSMD_DATE:-$(date +%m%d%Y)}"
RUN_SLOT="${NEWSMD_SLOT:-$(slot_for_now)}"
OUTPUT_DIR="${NEWS_RAW}/${RUN_DATE}-${RUN_SLOT}"
LOG_FILE="${LOG_DIR}/news_${RUN_DATE}-${RUN_SLOT}_$(date +%H%M%S).log"

exec >> "${LOG_FILE}" 2>&1

echo "============================================================"
echo "newsmd run started: $(date '+%Y-%m-%d %H:%M:%S %Z')"
echo "Project root: ${PROJECT_ROOT}"
echo "Output: ${OUTPUT_DIR}"
echo "Model: ${MODEL}"
echo "Topics: ${TOPICS}"
echo "Max per feed: ${MAX_PER_FEED}"
if [ -n "${TOTAL_LIMIT}" ]; then
  echo "Total limit: ${TOTAL_LIMIT}"
fi
echo "Log: ${LOG_FILE}"
echo "============================================================"

if ! mkdir "${LOCK_DIR}" 2>/dev/null; then
  echo "Another newsmd run is already active: ${LOCK_DIR}"
  exit 0
fi

cleanup() {
  rmdir "${LOCK_DIR}" 2>/dev/null || true
}
trap cleanup EXIT INT TERM

if [ ! -f "${FETCHER}" ]; then
  echo "Missing fetcher: ${FETCHER}"
  exit 1
fi

if [ ! -x "${PYTHON}" ]; then
  echo "Missing Python venv: ${PYTHON}"
  echo "Run: ${PROJECT_ROOT}/scripts/install.sh"
  exit 1
fi

CERT_FILE="$("${PYTHON}" -m certifi 2>/dev/null || true)"
if [ -n "${CERT_FILE}" ] && [ -f "${CERT_FILE}" ]; then
  export SSL_CERT_FILE="${CERT_FILE}"
  export REQUESTS_CA_BUNDLE="${CERT_FILE}"
  echo "CA bundle: ${CERT_FILE}"
fi

if ! curl -fsS "${OLLAMA_URL}/api/tags" >/dev/null 2>&1; then
  echo "Ollama is not responding; trying to start it."
  /usr/bin/open -gja "Ollama" >/dev/null 2>&1 || true
  if command -v ollama >/dev/null 2>&1; then
    nohup ollama serve >> "${LOG_DIR}/ollama.log" 2>&1 &
  fi
  for _ in {1..24}; do
    sleep 5
    if curl -fsS "${OLLAMA_URL}/api/tags" >/dev/null 2>&1; then
      break
    fi
  done
fi

if ! curl -fsS "${OLLAMA_URL}/api/tags" >/dev/null 2>&1; then
  echo "Ollama is still unavailable after waiting."
  exit 1
fi

fetch_cmd=(
  "${PYTHON}" "${FETCHER}"
  --topics ${(z)TOPICS}
  --max "${MAX_PER_FEED}"
  --model "${MODEL}"
  --output "${OUTPUT_DIR}"
)

if [ -n "${TOTAL_LIMIT}" ]; then
  fetch_cmd+=(--total-limit "${TOTAL_LIMIT}")
fi

"${fetch_cmd[@]}"

run_status=$?
echo "newsmd run finished with status ${run_status}: $(date '+%Y-%m-%d %H:%M:%S %Z')"
exit "${run_status}"
