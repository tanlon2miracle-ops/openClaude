#!/usr/bin/env bash
set -euo pipefail

INSTALL_DIR="/opt/claude-code"
BIN_LINK="/usr/local/bin/claude"
MIN_NODE_VERSION=18
MIN_DISK_MB=1000

log()  { printf '\033[1;32m>>>\033[0m %s\n' "$*"; }
warn() { printf '\033[1;33mWRN\033[0m %s\n' "$*"; }
err()  { printf '\033[1;31mERR\033[0m %s\n' "$*" >&2; exit 1; }

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
ACTION="install"

usage() {
  cat <<EOF
Usage: $0 [OPTIONS]

OPTIONS:
  --prefix <path>   Installation directory (default: $INSTALL_DIR)
  --bin <path>      Symlink path for claude command (default: $BIN_LINK)
  --uninstall       Remove existing installation
  -h, --help        Show this help
EOF
  exit 0
}

while [[ $# -gt 0 ]]; do
  case "$1" in
    --prefix)    INSTALL_DIR="$2"; shift 2 ;;
    --bin)       BIN_LINK="$2"; shift 2 ;;
    --uninstall) ACTION="uninstall"; shift ;;
    -h|--help)   usage ;;
    *) err "Unknown option: $1" ;;
  esac
done

do_uninstall() {
  log "Uninstalling claude-code ..."
  [[ -L "$BIN_LINK" ]] && rm -f "$BIN_LINK" && log "Removed $BIN_LINK"
  [[ -d "$INSTALL_DIR" ]] && rm -rf "$INSTALL_DIR" && log "Removed $INSTALL_DIR"
  log "Uninstall complete."
  exit 0
}

check_env() {
  # Root check
  [[ $EUID -ne 0 ]] && err "Please run as root (sudo ./deploy.sh)"

  # Architecture
  local arch; arch="$(uname -m)"
  log "Architecture: $arch"

  # Node.js
  if ! command -v node &>/dev/null; then
    err "Node.js not found. Install Node.js >= $MIN_NODE_VERSION first."
  fi
  local node_ver; node_ver="$(node -v | sed 's/v//' | cut -d. -f1)"
  if [[ "$node_ver" -lt "$MIN_NODE_VERSION" ]]; then
    err "Node.js v${node_ver} too old. Need >= $MIN_NODE_VERSION."
  fi
  log "Node.js: $(node -v)"

  # Disk space
  local avail_mb; avail_mb="$(df -Pm "$(dirname "$INSTALL_DIR")" | awk 'NR==2{print $4}')"
  if [[ "$avail_mb" -lt "$MIN_DISK_MB" ]]; then
    err "Insufficient disk: ${avail_mb}MB available, need ${MIN_DISK_MB}MB."
  fi
  log "Disk: ${avail_mb}MB available"
}

do_install() {
  check_env

  # Detect whitelabel mode
  local IS_BRANDED=false
  local BRAND_NAME="" BRAND_LOWER="" API_BASE_URL="" API_KEY="" PRE_BUILT=""
  if [[ -f "$SCRIPT_DIR/brand.env" ]]; then
    source "$SCRIPT_DIR/brand.env"
    IS_BRANDED=true
    log "Whitelabel mode: $BRAND_NAME"
  fi

  # Clean previous installation
  if [[ -d "$INSTALL_DIR" ]]; then
    warn "Existing installation found at $INSTALL_DIR, removing ..."
    rm -rf "$INSTALL_DIR"
  fi

  # Copy files
  log "Installing to $INSTALL_DIR ..."
  mkdir -p "$INSTALL_DIR"

  if [[ "$PRE_BUILT" == "true" && -f "$SCRIPT_DIR/dist/cli.js" ]]; then
    # Pre-built + patched: just copy dist and node_modules
    cp -a "$SCRIPT_DIR/dist"           "$INSTALL_DIR/"
    cp -a "$SCRIPT_DIR/node_modules"   "$INSTALL_DIR/"
    cp "$SCRIPT_DIR/package.json"      "$INSTALL_DIR/"
    log "Copied pre-built artifacts."
  else
    # Need to build on target
    cp -a "$SCRIPT_DIR/src"          "$INSTALL_DIR/"
    cp -a "$SCRIPT_DIR/vendor"       "$INSTALL_DIR/"
    cp -a "$SCRIPT_DIR/scripts"      "$INSTALL_DIR/"
    cp -a "$SCRIPT_DIR/node_modules" "$INSTALL_DIR/"
    cp "$SCRIPT_DIR/package.json"    "$INSTALL_DIR/"
    cp "$SCRIPT_DIR/build.ts"        "$INSTALL_DIR/"
    cp "$SCRIPT_DIR/tsconfig.json"   "$INSTALL_DIR/"
    [[ -f "$SCRIPT_DIR/bunfig.toml" ]] && cp "$SCRIPT_DIR/bunfig.toml" "$INSTALL_DIR/"

    local bun_bin="$SCRIPT_DIR/bun/bun"
    [[ ! -x "$bun_bin" ]] && err "Bun binary not found at $bun_bin"
    log "Building with bundled Bun ..."

    cd "$INSTALL_DIR"
    "$bun_bin" run build
    log "Build complete: dist/cli.js ($(du -sh dist/cli.js | cut -f1))"

    # Cleanup build artifacts
    rm -rf "$INSTALL_DIR/src" "$INSTALL_DIR/vendor" "$INSTALL_DIR/scripts"
    rm -f "$INSTALL_DIR/build.ts" "$INSTALL_DIR/tsconfig.json" "$INSTALL_DIR/bunfig.toml"
    log "Build artifacts cleaned."
  fi

  # Create launcher/wrapper
  local cmd_name="claude"
  if $IS_BRANDED && [[ -n "$BRAND_LOWER" ]]; then
    cmd_name="$BRAND_LOWER"
    BIN_LINK="$(dirname "$BIN_LINK")/$cmd_name"
  fi

  mkdir -p "$(dirname "$BIN_LINK")"
  if $IS_BRANDED; then
    # Create api.env config file (editable without rebuild)
    local config_dir="\$HOME/.${BRAND_LOWER}"
    local api_env_default="$INSTALL_DIR/api.env.default"
    cat > "$api_env_default" <<APIENV
# ${BRAND_NAME} API Configuration
# Edit ~/.${BRAND_LOWER}/api.env to change without rebuilding.
API_BASE_URL="${API_BASE_URL}"
API_KEY="${API_KEY}"
APIENV

    cat > "$BIN_LINK" <<WRAPPER
#!/usr/bin/env bash
export CLAUDE_CONFIG_DIR="\$HOME/.${BRAND_LOWER}"
mkdir -p "\$CLAUDE_CONFIG_DIR"
API_ENV="\$CLAUDE_CONFIG_DIR/api.env"
if [[ ! -f "\$API_ENV" ]]; then
  cp "$INSTALL_DIR/api.env.default" "\$API_ENV"
  echo "Created config: \$API_ENV"
fi
source "\$API_ENV"
export ANTHROPIC_AUTH_TOKEN="\${API_KEY}"
export ANTHROPIC_BASE_URL="\${API_BASE_URL}"
export ANTHROPIC_API_KEY=""
export CLAUDE_CODE_DISABLE_NONESSENTIAL_TRAFFIC=1
exec node "$INSTALL_DIR/dist/cli.js" "\$@"
WRAPPER
  else
    cat > "$BIN_LINK" <<WRAPPER
#!/usr/bin/env bash
exec node "$INSTALL_DIR/dist/cli.js" "\$@"
WRAPPER
  fi
  chmod +x "$BIN_LINK"
  log "Command installed: $BIN_LINK"

  # Verify
  local ver
  if ver="$("$BIN_LINK" --version 2>/dev/null)"; then
    log "Verification passed: $cmd_name $ver"
  else
    warn "$cmd_name --version did not return cleanly (may need API key to fully start)."
  fi

  log "=============================="
  log "Installation complete!"
  log "  Command:  $BIN_LINK"
  log "  Install:  $INSTALL_DIR"
  log "  Run:      $cmd_name"
  log "=============================="
}

case "$ACTION" in
  install)   do_install ;;
  uninstall) do_uninstall ;;
esac
