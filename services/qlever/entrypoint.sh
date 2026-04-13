#!/bin/sh
set -eu

RESTART_FLAG="/index/.restart-qlever"

start_qlever() {
  qlever start \
    --name rds \
    --description "RDS Qlever instance" \
    --system native \
    --port 7001 \
    --access-token "$QLEVER_ACCESS_TOKEN" &
  QLEVER_PID=$!
}

stop_qlever() {
  qlever stop --name rds --port 7001 --no-containers || true

  if kill -0 "$QLEVER_PID" 2>/dev/null; then
    wait "$QLEVER_PID" || true
  fi
}

handle_term() {
  stop_qlever
  exit 0
}

trap handle_term INT TERM

rm -f "$RESTART_FLAG"
start_qlever

while true; do
  if [ -f "$RESTART_FLAG" ]; then
    rm -f "$RESTART_FLAG"
    stop_qlever
    start_qlever
  fi

  if ! kill -0 "$QLEVER_PID" 2>/dev/null; then
    wait "$QLEVER_PID" || true
    exit 1
  fi

  sleep 1
done
