#!/bin/bash
set -euo pipefail

# Only run in remote (cloud) sessions
if [ "${CLAUDE_CODE_REMOTE:-}" != "true" ]; then
  exit 0
fi

PROJECT="${CLAUDE_PROJECT_DIR:-$(cd "$(dirname "$0")/../.." && pwd)}"

# Install Python dependencies
if [ -f "$PROJECT/requirements.txt" ]; then
    pip install -q -r "$PROJECT/requirements.txt"
fi

# Load Hive lessons into session context
python3 "$PROJECT/scripts/lesson_loader.py"

# Load materialized project entities into session context
python3 "$PROJECT/scripts/entity_loader.py"
