#!/bin/bash
set -euo pipefail

# Only run in remote (Claude Code on the web) environments
if [ "${CLAUDE_CODE_REMOTE:-}" != "true" ]; then
  exit 0
fi

# This is a data-only repository (CSV/text files) with no runtime dependencies.
# The hook ensures basic tools are available for working with the data files.
echo "dotgov-data session initialized"
