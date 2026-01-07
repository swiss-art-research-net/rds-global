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
  proxy_pass http://qlever:${port};
}

location ^~ /${name}/ {
    set \$final_content_type \$http_content_type;
    if (\$final_content_type = "") {
        set \$final_content_type "application/x-www-form-urlencoded";
    }
    proxy_set_header Content-Type \$final_content_type;
    proxy_pass http://qlever:${port}/;
}
EOF
  done
} > "$OUT_CONF"

exec "$@"