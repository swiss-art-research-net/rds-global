#!/usr/bin/env bash
set -euo pipefail

CSV_PATH="${CSV_PATH:-/etc/nginx/endpoints.csv}"
OUT_DIR="/etc/nginx/includes"
OUT_CONF="${OUT_DIR}/services.conf"

mkdir -p "$OUT_DIR"

{
  echo "# generated from ${CSV_PATH}"
  tail -n +2 "$CSV_PATH" | while IFS=, read -r name port; do
    name="$(echo "$name" | xargs)"
    port="$(echo "$port" | xargs)"
    [ -z "$name" ] && continue
    [ -z "$port" ] && port="7001"

    cat <<EOF

location = /${name} {
  if (\$request_method = 'OPTIONS') {
    add_header Access-Control-Allow-Origin "*" always;
    add_header Access-Control-Allow-Methods "GET, POST, OPTIONS" always;
    add_header Access-Control-Allow-Headers "*" always;
    return 204;
  }
  return 301 /${name}/;
}

location ^~ /${name}/ {
  if (\$request_method = 'OPTIONS') {
    add_header Access-Control-Allow-Origin "*" always;
    add_header Access-Control-Allow-Methods "GET, POST, OPTIONS" always;
    add_header Access-Control-Allow-Headers "*" always;
    return 204;
  }

  proxy_http_version 1.1;
  proxy_set_header Upgrade \$http_upgrade;
  proxy_set_header Connection "upgrade";
  
  proxy_set_header Host \$host;
  proxy_set_header X-Real-IP \$remote_addr;
  proxy_set_header X-Forwarded-For \$proxy_add_x_forwarded_for;
  proxy_set_header X-Forwarded-Proto \$scheme;

  proxy_set_header Content-Type \$http_content_type;
  proxy_pass_request_headers on;

  proxy_pass http://qlever:${port}/;
  
  proxy_buffering off;
  proxy_read_timeout 300s;
}
EOF
  done
} > "$OUT_CONF"

exec "$@"