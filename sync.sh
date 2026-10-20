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

wacli --json auth status >/dev/null
printf '%s\n' 'Ready. Run wacli-pair in the Railway SSH terminal to link your phone.'
trap 'exit 0' INT TERM

until wacli --read-only --json auth status | jq -e '.data.authenticated == true' >/dev/null; do
  sleep 5 &
  wait "$!"
done

printf '%s\n' 'WhatsApp session found. Starting continuous sync.'
exec wacli --lock-wait 2m sync --follow
