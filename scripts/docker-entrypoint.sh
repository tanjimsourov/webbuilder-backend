#!/bin/sh
set -eu

wait_args=""
if [ "${DJANGO_WAIT_FOR_DB:-0}" = "1" ]; then
  wait_args="$wait_args --db"
fi
if [ "${DJANGO_WAIT_FOR_CACHE:-0}" = "1" ]; then
  wait_args="$wait_args --cache"
fi

if [ -n "$wait_args" ]; then
  # shellcheck disable=SC2086
  python manage.py wait_for_services $wait_args --timeout "${DJANGO_STARTUP_MAX_WAIT_SECONDS:-60}" --sleep 2
fi

if [ "${DJANGO_RUN_MIGRATIONS:-1}" = "1" ]; then
  python manage.py migrate --noinput
fi

if [ "${DJANGO_COLLECTSTATIC:-1}" = "1" ]; then
  if [ "${DJANGO_COLLECTSTATIC_CLEAR:-0}" = "1" ]; then
    python manage.py collectstatic --noinput --clear
  else
    python manage.py collectstatic --noinput
  fi
fi

exec "$@"
