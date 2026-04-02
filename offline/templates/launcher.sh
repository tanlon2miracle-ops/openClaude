#!/usr/bin/env bash
# MyAI Launcher - reads config from ~/.myai/api.env

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
CLI="$SCRIPT_DIR/dist/cli.js"

export CLAUDE_CONFIG_DIR="$HOME/.__BRAND_LOWER__"
mkdir -p "$CLAUDE_CONFIG_DIR"

# Create default api.env if not exists
API_ENV="$CLAUDE_CONFIG_DIR/api.env"
if [[ ! -f "$API_ENV" ]]; then
  cat > "$API_ENV" <<'DEFAULTS'
# __BRAND__ API Configuration
# Edit this file to change API endpoint and key without rebuilding.
API_BASE_URL="__API_BASE_URL__"
API_KEY="__API_KEY__"
DEFAULTS
  echo "Created config: $API_ENV"
fi

source "$API_ENV"

export ANTHROPIC_AUTH_TOKEN="${API_KEY}"
export ANTHROPIC_BASE_URL="${API_BASE_URL}"
export ANTHROPIC_API_KEY=""
export ENABLE_TOOL_SEARCH=false
export CLAUDE_CODE_DISABLE_NONESSENTIAL_TRAFFIC=1

if [[ ! -f "$CLI" ]]; then
  echo "Error: cli.js not found at $CLI" >&2
  exit 1
fi

exec node "$CLI" "$@"
