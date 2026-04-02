#!/usr/bin/env bash
# Claude Code Hook: On conversation stop, append a summary marker to the activity log.
# This lets the report generator segment logs by conversation turn.

set -euo pipefail

PROJECT_DIR="$(cd "$(dirname "$0")/../.." && pwd)"
LOG_DIR="$PROJECT_DIR/logs"
LOG_FILE="$LOG_DIR/activity.jsonl"

mkdir -p "$LOG_DIR"

INPUT=$(cat)

echo "$INPUT" | jq -c '{
  timestamp: (now | todate),
  session_id: .session_id,
  event: "ConversationStop",
  tool: null,
  tool_input: null
}' >> "$LOG_FILE" 2>/dev/null

exit 0
