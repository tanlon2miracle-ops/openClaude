#!/usr/bin/env bash
# openClaude Provider Server - 启动/停止/状态
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
PROXY_DIR="$SCRIPT_DIR"
PID_FILE="$PROXY_DIR/.provider.pid"
LOG_FILE="$PROXY_DIR/provider.log"
DEFAULT_PORT=8082

usage() {
  cat <<EOF
Usage: $0 <start|stop|status|restart> [OPTIONS]

Commands:
  start     Start the provider server
  stop      Stop the provider server
  status    Check if the server is running
  restart   Restart the server

Options:
  --port <port>     Server port (default: $DEFAULT_PORT)
  --config <path>   Config file path (default: config.yaml)
  -h, --help        Show this help
EOF
  exit 0
}

[[ $# -eq 0 ]] && usage
CMD="$1"; shift

PORT="$DEFAULT_PORT"
CONFIG="config.yaml"

while [[ $# -gt 0 ]]; do
  case "$1" in
    --port)   PORT="$2"; shift 2 ;;
    --config) CONFIG="$2"; shift 2 ;;
    -h|--help) usage ;;
    *) shift ;;
  esac
done

do_start() {
  if [[ -f "$PID_FILE" ]] && kill -0 "$(cat "$PID_FILE")" 2>/dev/null; then
    echo "Provider already running (PID $(cat "$PID_FILE"))"
    return 0
  fi

  # Check venv
  if [[ ! -d "$PROXY_DIR/.venv" ]]; then
    echo "Creating virtual environment ..."
    python3 -m venv "$PROXY_DIR/.venv"
    source "$PROXY_DIR/.venv/bin/activate"
    pip install -q fastapi uvicorn httpx pyyaml tiktoken
  else
    source "$PROXY_DIR/.venv/bin/activate"
  fi

  # Check config
  if [[ ! -f "$PROXY_DIR/$CONFIG" ]]; then
    if [[ -f "$PROXY_DIR/config.example.yaml" ]]; then
      cp "$PROXY_DIR/config.example.yaml" "$PROXY_DIR/$CONFIG"
      echo "Created $CONFIG from example. Edit it with your API settings."
    else
      echo "Error: No $CONFIG found." >&2
      exit 1
    fi
  fi

  echo "Starting provider on port $PORT ..."
  cd "$PROXY_DIR"
  nohup "$PROXY_DIR/.venv/bin/uvicorn" proxy.server:app \
    --host 0.0.0.0 --port "$PORT" \
    > "$LOG_FILE" 2>&1 &
  echo $! > "$PID_FILE"
  sleep 1

  if kill -0 "$(cat "$PID_FILE")" 2>/dev/null; then
    echo "Provider started (PID $(cat "$PID_FILE"), port $PORT)"
    echo "Log: $LOG_FILE"
    echo "Health: http://localhost:$PORT/health"
  else
    echo "Failed to start. Check $LOG_FILE"
    rm -f "$PID_FILE"
    exit 1
  fi
}

do_stop() {
  if [[ ! -f "$PID_FILE" ]]; then
    echo "Provider not running."
    return 0
  fi
  local pid; pid="$(cat "$PID_FILE")"
  if kill -0 "$pid" 2>/dev/null; then
    kill "$pid"
    echo "Provider stopped (PID $pid)"
  else
    echo "Provider not running (stale PID file)."
  fi
  rm -f "$PID_FILE"
}

do_status() {
  if [[ -f "$PID_FILE" ]] && kill -0 "$(cat "$PID_FILE")" 2>/dev/null; then
    echo "Provider running (PID $(cat "$PID_FILE"))"
    curl -s "http://localhost:$PORT/health" 2>/dev/null && echo "" || echo "Health check failed"
  else
    echo "Provider not running."
  fi
}

case "$CMD" in
  start)   do_start ;;
  stop)    do_stop ;;
  status)  do_status ;;
  restart) do_stop; sleep 1; do_start ;;
  *) usage ;;
esac
