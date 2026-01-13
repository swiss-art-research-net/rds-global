#!/usr/bin/env bash
set -euo pipefail

CSV_PATH="${CSV_PATH:-/etc/nginx/endpoints.csv}"
OUT_DIR="/etc/nginx/includes"
OUT_CONF="${OUT_DIR}/services.conf"

mkdir -p "$OUT_DIR"

{
  echo "# generated from ${CSV_PATH}"
  tail -n +2 "$CSV_PATH" | while IFS=, read -r name port || [ -n "$name$port" ]; do
    name="$(echo "$name" | xargs)"
    port="$(echo "$port" | xargs)"
    [ -z "$name" ] && continue
    [ -z "$port" ] && continue

    cat <<EOF

location = /${name} {
  if (\$request_method = 'OPTIONS') {
    add_header Access-Control-Allow-Origin "*" always;
    add_header Access-Control-Allow-Methods "GET, POST, OPTIONS" always;
    add_header Access-Control-Allow-Headers "*" always;
    return 204;
  }
  proxy_pass http://qlever-datasets:${port};
}

location ^~ /${name}/ {
    proxy_pass http://qlever-datasets:${port}/;
}
EOF
  done
} > "$OUT_CONF"

exec "$@"