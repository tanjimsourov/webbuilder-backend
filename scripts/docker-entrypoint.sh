#!/bin/sh
set -eu

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
