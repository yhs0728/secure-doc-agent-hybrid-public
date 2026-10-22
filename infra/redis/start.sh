#!/bin/sh
set -eu
umask 077
case "${REDIS_PASSWORD:-}" in
  ''|*[!A-Za-z0-9_-]*) echo 'REDIS_PASSWORD must be a nonempty URL-safe secret' >&2; exit 1 ;;
esac
if [ "${#REDIS_PASSWORD}" -lt 32 ]; then
  echo 'REDIS_PASSWORD must contain at least 32 characters' >&2; exit 1
fi
cat /etc/secure-doc-redis/redis.conf > /tmp/secure-doc-redis.conf
printf '\nrequirepass %s\n' "$REDIS_PASSWORD" >> /tmp/secure-doc-redis.conf
exec redis-server /tmp/secure-doc-redis.conf
