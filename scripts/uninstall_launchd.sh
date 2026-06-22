#!/bin/zsh
set -euo pipefail

LABEL="${NEWSMD_LAUNCHD_LABEL:-com.newsmd.twicedaily}"
PLIST="${HOME}/Library/LaunchAgents/${LABEL}.plist"

launchctl bootout "gui/$(id -u)" "${PLIST}" 2>/dev/null || true
rm -f "${PLIST}"

echo "Removed LaunchAgent: ${LABEL}"
echo "Project files and news_raw output were not deleted."
