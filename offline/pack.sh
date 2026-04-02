#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
source "$SCRIPT_DIR/config.env"

WORK_DIR="$SCRIPT_DIR/.work"
OUTPUT_DIR="$SCRIPT_DIR/dist"

log()  { printf '\033[1;32m>>>\033[0m %s\n' "$*"; }
err()  { printf '\033[1;31mERR\033[0m %s\n' "$*" >&2; exit 1; }

usage() {
  cat <<EOF
Usage: $0 [OPTIONS]

OPTIONS:
  --arch <x86_64|aarch64|both>    Target CPU architecture (default: auto-detect)
  --os <linux|darwin>             Target OS (default: auto-detect)
  --clean                         Remove work directory before packing
  -h, --help                      Show this help
EOF
  exit 0
}

TARGET_ARCH="${ARCH:-}"
TARGET_OS=""
CLEAN=false

while [[ $# -gt 0 ]]; do
  case "$1" in
    --arch)   TARGET_ARCH="$2"; shift 2 ;;
    --os)     TARGET_OS="$2"; shift 2 ;;
    --clean)  CLEAN=true; shift ;;
    -h|--help) usage ;;
    *) err "Unknown option: $1" ;;
  esac
done

detect_arch() {
  local a; a="$(uname -m)"
  case "$a" in
    x86_64|amd64) echo "x86_64" ;;
    aarch64|arm64) echo "aarch64" ;;
    *) err "Unsupported architecture: $a" ;;
  esac
}

[[ -z "$TARGET_ARCH" ]] && TARGET_ARCH="$(detect_arch)"

detect_os() {
  local s; s="$(uname -s)"
  case "$s" in
    Linux)  echo "linux" ;;
    Darwin) echo "darwin" ;;
    *) err "Unsupported OS: $s" ;;
  esac
}

[[ -z "$TARGET_OS" ]] && TARGET_OS="$(detect_os)"

bun_download_url() {
  local arch="$1" os="$2"
  local bun_arch bun_os
  case "$arch" in
    x86_64)  bun_arch="x64" ;;
    aarch64) bun_arch="aarch64" ;;
  esac
  case "$os" in
    linux)  bun_os="linux" ;;
    darwin) bun_os="darwin" ;;
  esac
  echo "https://github.com/oven-sh/bun/releases/download/bun-v${BUN_VERSION}/bun-${bun_os}-${bun_arch}.zip"
}

check_deps() {
  local missing=()
  for cmd in git curl unzip; do
    command -v "$cmd" &>/dev/null || missing+=("$cmd")
  done
  if [[ ${#missing[@]} -gt 0 ]]; then
    err "Missing required tools: ${missing[*]}"
  fi
}

pack_for_arch() {
  local arch="$1"
  local os="$TARGET_OS"
  local arch_work="$WORK_DIR/${os}-${arch}"

  log "Packing for ${os}-${arch} ..."

  # 1. Clone source
  if [[ ! -d "$arch_work/source" ]]; then
    log "Cloning $REPO_URL ($REPO_BRANCH) ..."
    git clone --depth 1 --branch "$REPO_BRANCH" "$REPO_URL" "$arch_work/source"
  else
    log "Source already cloned, skipping."
  fi

  # 2. Download Bun binary for target arch
  local bun_dir="$arch_work/bun"
  if [[ ! -x "$bun_dir/bun" ]]; then
    log "Downloading Bun v${BUN_VERSION} for ${os}-${arch} ..."
    mkdir -p "$bun_dir"
    local url; url="$(bun_download_url "$arch" "$os")"
    local tmp_zip="$arch_work/bun.zip"
    curl -fSL "$url" -o "$tmp_zip"
    unzip -o "$tmp_zip" -d "$arch_work/_bun_tmp"
    mv "$arch_work"/_bun_tmp/bun-*/bun "$bun_dir/bun"
    chmod +x "$bun_dir/bun"
    rm -rf "$tmp_zip" "$arch_work/_bun_tmp"
  else
    log "Bun binary exists, skipping download."
  fi

  # 3. Install dependencies (use local or downloaded Bun)
  log "Installing npm dependencies ..."
  local bun_bin
  if command -v bun &>/dev/null; then
    bun_bin="$(command -v bun)"
  else
    # If current machine matches target arch, use the downloaded one
    local host_arch; host_arch="$(detect_arch)"
    if [[ "$host_arch" == "$arch" ]]; then
      bun_bin="$bun_dir/bun"
    else
      err "Bun not found in PATH and host arch ($host_arch) != target ($arch). Install Bun first or pack on matching architecture."
    fi
  fi

  cd "$arch_work/source"
  "$bun_bin" install --frozen-lockfile 2>/dev/null || "$bun_bin" install
  # Ensure postinstall runs (creates stubs + patches commander)
  node scripts/postinstall.js 2>/dev/null || log "postinstall.js already applied."
  # Fix incomplete stubs: add render() methods to prevent runtime crash
  local cdnapi="$arch_work/source/node_modules/color-diff-napi/index.js"
  if [[ -f "$cdnapi" ]] && ! grep -q "render()" "$cdnapi"; then
    sed -i.bak 's/constructor() {}/constructor() {} render() { return null; }/g' "$cdnapi"
    rm -f "$cdnapi.bak"
    log "Patched color-diff-napi stub (added render method)."
  fi
  log "Dependencies installed."

  # 4. Assemble output
  local staging="$arch_work/claude-code-offline"
  rm -rf "$staging"
  mkdir -p "$staging"

  cp -a "$arch_work/source/src"       "$staging/src"
  cp -a "$arch_work/source/vendor"    "$staging/vendor"
  cp -a "$arch_work/source/scripts"   "$staging/scripts"
  cp -a "$arch_work/source/node_modules" "$staging/node_modules"
  cp "$arch_work/source/package.json"  "$staging/"
  cp "$arch_work/source/build.ts"      "$staging/"
  cp "$arch_work/source/tsconfig.json" "$staging/"
  [[ -f "$arch_work/source/bunfig.toml" ]] && cp "$arch_work/source/bunfig.toml" "$staging/"

  mkdir -p "$staging/bun"
  cp "$bun_dir/bun" "$staging/bun/bun"

  cp "$SCRIPT_DIR/deploy.sh" "$staging/deploy.sh"
  chmod +x "$staging/deploy.sh"

  # 4b. Whitelabel patch (optional, requires brand.env)
  if [[ -f "$SCRIPT_DIR/brand.env" ]]; then
    source "$SCRIPT_DIR/brand.env"
    log "Applying whitelabel patch: $BRAND_NAME ..."

    # Build first so we have dist/cli.js to patch
    log "Building before patch ..."
    cd "$staging"
    "$staging/bun/bun" run build 2>/dev/null || "$bun_bin" run build
    cd "$SCRIPT_DIR"

    # Run patch
    node "$SCRIPT_DIR/scripts/patch.js" \
      "$staging/dist/cli.js" \
      "$BRAND_NAME" "${API_BASE_URL:-}" "${BRAND_RGB:-}" \
      "${LOGO_STYLE:-default}" "${ENABLE_I18N:-false}" "${DISABLE_TELEMETRY:-true}"

    # Generate launcher from template
    if [[ -f "$SCRIPT_DIR/templates/launcher.sh" ]]; then
      sed -e "s|__BRAND__|${BRAND_NAME}|g" \
          -e "s|__BRAND_LOWER__|${BRAND_LOWER:-$(echo "$BRAND_NAME" | tr '[:upper:]' '[:lower:]')}|g" \
          -e "s|__API_KEY__|${API_KEY:-}|g" \
          -e "s|__API_BASE_URL__|${API_BASE_URL:-}|g" \
          "$SCRIPT_DIR/templates/launcher.sh" > "$staging/${BRAND_LOWER:-$(echo "$BRAND_NAME" | tr '[:upper:]' '[:lower:]')}.sh"
      chmod +x "$staging/${BRAND_LOWER:-$(echo "$BRAND_NAME" | tr '[:upper:]' '[:lower:]')}.sh"
      log "Generated launcher: ${BRAND_LOWER:-$(echo "$BRAND_NAME" | tr '[:upper:]' '[:lower:]')}.sh"
    fi

    # Store brand info for deploy.sh
    cat > "$staging/brand.env" <<BENV
BRAND_NAME="${BRAND_NAME}"
BRAND_LOWER="${BRAND_LOWER:-$(echo "$BRAND_NAME" | tr '[:upper:]' '[:lower:]')}"
API_BASE_URL="${API_BASE_URL:-}"
API_KEY="${API_KEY:-}"
PRE_BUILT="true"
BENV
    log "Whitelabel patch complete."
  fi

  # 5. Tar
  mkdir -p "$OUTPUT_DIR"
  local tarball="$OUTPUT_DIR/claude-code-offline-${os}-${arch}.tar.gz"
  log "Creating $tarball ..."
  tar -czf "$tarball" -C "$arch_work" "claude-code-offline"

  local size; size="$(du -sh "$tarball" | cut -f1)"
  log "Done: $tarball ($size)"
}

# Main
check_deps
[[ "$CLEAN" == "true" ]] && rm -rf "$WORK_DIR"
mkdir -p "$WORK_DIR"

if [[ "$TARGET_ARCH" == "both" ]]; then
  pack_for_arch "x86_64"
  pack_for_arch "aarch64"
else
  pack_for_arch "$TARGET_ARCH"
fi

log "All packages created in $OUTPUT_DIR/"
