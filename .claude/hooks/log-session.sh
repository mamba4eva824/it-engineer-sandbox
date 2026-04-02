#!/usr/bin/env bash
# Claude Code Hook: Log session start/end events.
# Captures when work sessions begin and end for time tracking.

set -euo pipefail

PROJECT_DIR="$(cd "$(dirname "$0")/../.." && pwd)"
LOG_DIR="$PROJECT_DIR/logs"
LOG_FILE="$LOG_DIR/sessions.jsonl"

mkdir -p "$LOG_DIR"

INPUT=$(cat)

echo "$INPUT" | jq -c '{
  timestamp: (now | todate),
  session_id: .session_id,
  event: .hook_event_name,
  cwd: .cwd
}' >> "$LOG_FILE" 2>/dev/null

exit 0
