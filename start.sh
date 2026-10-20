#!/bin/sh
set -eu
umask 077

if [ "$(id -u)" = 0 ]; then
  install -d -o wacli -g wacli -m 700 /data "$WACLI_STORE_DIR" "$XDG_CACHE_HOME" "$XDG_CONFIG_HOME" "$XDG_STATE_HOME"
  exec gosu wacli "$0" "$@"
fi

if [ "$#" -gt 0 ]; then
  exec "$@"
fi

case "$PORT" in
'' | *[!0-9]*)
  printf '%s\n' 'PORT must be an integer between 1 and 65535.' >&2
  exit 1
  ;;
esac
if [ "$PORT" -lt 1 ] || [ "$PORT" -gt 65535 ]; then
  printf '%s\n' 'PORT must be an integer between 1 and 65535.' >&2
  exit 1
fi

exec /opt/venv/bin/python -m uvicorn api:app --host 0.0.0.0 --port "$PORT" --workers 1 --no-access-log
