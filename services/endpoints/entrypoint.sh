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
    return 204;
  }
  return 301 /${name}/?\$args;
}

location ^~ /${name}/ {
  if (\$request_method = 'OPTIONS') {
    return 204;
  }

  proxy_set_header Host \$host;
  proxy_set_header X-Real-IP \$remote_addr;
  proxy_set_header X-Forwarded-For \$proxy_add_x_forwarded_for;
  proxy_set_header X-Forwarded-Proto \$scheme;

  rewrite ^/${name}/?(.*)$ /api/\$1 break;
  proxy_pass http://qlever:${port};
}
EOF
  done
} > "$OUT_CONF"

exec "$@"