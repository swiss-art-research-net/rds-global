#!/bin/sh
set -eu

RESTART_FLAG="/index/.restart-qlever"
INDEX_READY_FILE="/index/rds.meta-data.json"
DATASET_NAME="rds"
PORT="7001"
START_ARGS="
  --name ${DATASET_NAME}
  --description RDS Qlever instance
  --system native
  --port ${PORT}
  --access-token ${QLEVER_ACCESS_TOKEN}
"

is_index_ready() {
  [ -f "$INDEX_READY_FILE" ]
}

is_server_running() {
  qlever status 2>/dev/null | grep -q " ${DATASET_NAME} "
}

start_server() {
  if ! is_index_ready; then
    return 0
  fi

  if is_server_running; then
    return 0
  fi

  qlever start $START_ARGS --no-warmup
}

stop_server() {
  qlever stop --name "$DATASET_NAME" --port "$PORT" --no-containers || true
}

restart_server() {
  stop_server

  for _ in 1 2 3 4 5 6 7 8 9 10; do
    if ! is_server_running; then
      break
    fi
    sleep 1
  done

  start_server
}

handle_term() {
  stop_server
  exit 0
}

trap handle_term INT TERM

rm -f "$RESTART_FLAG"

while true; do
  if [ -f "$RESTART_FLAG" ]; then
    rm -f "$RESTART_FLAG"
    restart_server
  else
    start_server
  fi

  sleep 2
done
