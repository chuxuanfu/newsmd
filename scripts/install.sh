#!/bin/zsh
set -euo pipefail

export PATH="/opt/homebrew/bin:/usr/local/bin:/usr/bin:/bin:/usr/sbin:/sbin"

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
PROJECT_ROOT="$(cd "${SCRIPT_DIR}/.." && pwd)"
LABEL="${NEWSMD_LAUNCHD_LABEL:-com.newsmd.twicedaily}"
PLIST="${HOME}/Library/LaunchAgents/${LABEL}.plist"
MODEL="${NEWSMD_MODEL:-qwen3.6:35b}"
PYTHON_BIN="${NEWSMD_SYSTEM_PYTHON:-python3}"

say_step() {
  printf "\n==> %s\n" "$1"
}

say_step "Checking macOS command line tools"
if ! xcode-select -p >/dev/null 2>&1; then
  echo "Xcode Command Line Tools are required."
  echo "A system installer window will open. Finish it, then rerun this script:"
  echo "  ${PROJECT_ROOT}/scripts/install.sh"
  xcode-select --install || true
  exit 1
fi

say_step "Checking Homebrew"
if ! command -v brew >/dev/null 2>&1; then
  echo "Homebrew is not installed. Installing Homebrew now."
  /bin/bash -c "$(curl -fsSL https://raw.githubusercontent.com/Homebrew/install/HEAD/install.sh)"
fi

if [ -x "/opt/homebrew/bin/brew" ]; then
  eval "$(/opt/homebrew/bin/brew shellenv)"
elif [ -x "/usr/local/bin/brew" ]; then
  eval "$(/usr/local/bin/brew shellenv)"
fi

say_step "Installing system dependencies"
brew list python >/dev/null 2>&1 || brew install python
brew list ollama >/dev/null 2>&1 || brew install ollama

say_step "Creating Python virtual environment"
"${PYTHON_BIN}" -m venv "${PROJECT_ROOT}/.venv"
"${PROJECT_ROOT}/.venv/bin/python3" -m pip install --upgrade pip
"${PROJECT_ROOT}/.venv/bin/python3" -m pip install -r "${PROJECT_ROOT}/requirements.txt"

say_step "Preparing runtime directories"
mkdir -p "${PROJECT_ROOT}/news_raw" "${PROJECT_ROOT}/logs" "${PROJECT_ROOT}/run" "${HOME}/Library/LaunchAgents"
chmod +x "${PROJECT_ROOT}/scripts/run_news_twice_daily.sh"

say_step "Starting Ollama and pulling model: ${MODEL}"
if ! curl -fsS "http://localhost:11434/api/tags" >/dev/null 2>&1; then
  /usr/bin/open -gja "Ollama" >/dev/null 2>&1 || true
  nohup ollama serve >> "${PROJECT_ROOT}/logs/ollama.log" 2>&1 &
  for _ in {1..24}; do
    sleep 5
    if curl -fsS "http://localhost:11434/api/tags" >/dev/null 2>&1; then
      break
    fi
  done
fi

if ! curl -fsS "http://localhost:11434/api/tags" >/dev/null 2>&1; then
  echo "Ollama did not start. Open Ollama manually or run 'ollama serve', then rerun install.sh."
  exit 1
fi

ollama pull "${MODEL}"

say_step "Writing LaunchAgent: ${PLIST}"
cat > "${PLIST}" <<PLIST
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN"
  "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
  <key>Label</key>
  <string>${LABEL}</string>

  <key>ProgramArguments</key>
  <array>
    <string>${PROJECT_ROOT}/scripts/run_news_twice_daily.sh</string>
  </array>

  <key>StartCalendarInterval</key>
  <array>
    <dict>
      <key>Hour</key>
      <integer>8</integer>
      <key>Minute</key>
      <integer>0</integer>
    </dict>
    <dict>
      <key>Hour</key>
      <integer>20</integer>
      <key>Minute</key>
      <integer>0</integer>
    </dict>
  </array>

  <key>RunAtLoad</key>
  <false/>

  <key>StandardOutPath</key>
  <string>${PROJECT_ROOT}/logs/launchd.out.log</string>

  <key>StandardErrorPath</key>
  <string>${PROJECT_ROOT}/logs/launchd.err.log</string>
</dict>
</plist>
PLIST

plutil -lint "${PLIST}"

say_step "Loading LaunchAgent"
launchctl bootout "gui/$(id -u)" "${PLIST}" 2>/dev/null || true
launchctl bootstrap "gui/$(id -u)" "${PLIST}"
launchctl enable "gui/$(id -u)/${LABEL}"

say_step "Install complete"
echo "LaunchAgent label: ${LABEL}"
echo "Project root: ${PROJECT_ROOT}"
echo "Output dir: ${PROJECT_ROOT}/news_raw"
echo "Logs dir: ${PROJECT_ROOT}/logs"
echo ""
echo "Run a small test:"
echo "  NEWSMD_TOTAL_LIMIT=3 ${PROJECT_ROOT}/scripts/run_news_twice_daily.sh"
echo ""
echo "Check launchd:"
echo "  launchctl print gui/\$(id -u)/${LABEL}"
