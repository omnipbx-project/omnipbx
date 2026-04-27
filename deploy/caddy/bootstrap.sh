#!/bin/sh
set -eu

mkdir -p /srv/omnipbx/caddy

if [ ! -s /srv/omnipbx/caddy/Caddyfile ]; then
  HTTP_PORT="${OMNIPBX_PUBLIC_HTTP_PORT:-80}"
  cat > /srv/omnipbx/caddy/Caddyfile <<EOF
:${HTTP_PORT} {
  reverse_proxy app:18000
}
EOF
fi

exec caddy run --config /srv/omnipbx/caddy/Caddyfile --adapter caddyfile --watch
