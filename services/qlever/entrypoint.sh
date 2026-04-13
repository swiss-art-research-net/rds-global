#!/bin/sh
set -eu

RESTART_FLAG="/index/.restart-qlever"
INDEX_READY_FILE="/index/rds.meta-data.json"
QLEVER_PID=""

start_qlever() {
  if [ ! -f "$INDEX_READY_FILE" ]; then
    return 1
  fi

  qlever start \
    --name rds \
    --description "RDS Qlever instance" \
    --system native \
    --port 7001 \
    --run-in-foreground \
    --access-token "$QLEVER_ACCESS_TOKEN" &
  QLEVER_PID=$!
}

stop_qlever() {
  qlever stop --name rds --port 7001 --no-containers || true

  if [ -n "$QLEVER_PID" ] && kill -0 "$QLEVER_PID" 2>/dev/null; then
    wait "$QLEVER_PID" || true
  fi

  QLEVER_PID=""
}

ensure_qlever_running() {
  if [ -n "$QLEVER_PID" ] && kill -0 "$QLEVER_PID" 2>/dev/null; then
    return 0
  fi

  QLEVER_PID=""

  if [ -f "$INDEX_READY_FILE" ]; then
    start_qlever || true
  fi
}

handle_term() {
  stop_qlever
  exit 0
}

trap handle_term INT TERM

rm -f "$RESTART_FLAG"
ensure_qlever_running

while true; do
  if [ -f "$RESTART_FLAG" ]; then
    rm -f "$RESTART_FLAG"
    stop_qlever
    ensure_qlever_running
  fi

  if [ -n "$QLEVER_PID" ] && ! kill -0 "$QLEVER_PID" 2>/dev/null; then
    wait "$QLEVER_PID" || true
    QLEVER_PID=""
  fi

  ensure_qlever_running
  sleep 1
done
