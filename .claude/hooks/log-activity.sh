#!/usr/bin/env bash
# Claude Code Hook: Log all tool activity for interview preparation reports.
# Receives JSON on stdin with tool_name, tool_input, session_id, etc.
# Writes structured JSONL to logs/activity.jsonl

set -euo pipefail

PROJECT_DIR="$(cd "$(dirname "$0")/../.." && pwd)"
LOG_DIR="$PROJECT_DIR/logs"
LOG_FILE="$LOG_DIR/activity.jsonl"

mkdir -p "$LOG_DIR"

# Read stdin (hook input JSON)
INPUT=$(cat)

# Extract fields and write structured log entry
echo "$INPUT" | jq -c '{
  timestamp: (now | todate),
  session_id: .session_id,
  event: .hook_event_name,
  tool: .tool_name,
  tool_input: .tool_input
}' >> "$LOG_FILE" 2>/dev/null

exit 0
