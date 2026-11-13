#!/bin/sh
set -eu
case "${APP_POSTGRES_PASSWORD:-}" in
  ''|*[!A-Za-z0-9_-]*) printf '%s\n' 'Invalid application database credential format' >&2; exit 1 ;;
esac
if [ "${#APP_POSTGRES_PASSWORD}" -lt 32 ]; then
  printf '%s\n' 'Application database credential is too short' >&2
  exit 1
fi
psql --set=ON_ERROR_STOP=1 --username "$POSTGRES_USER" --dbname "$POSTGRES_DB" <<SQL
CREATE ROLE livekit_lab WITH LOGIN PASSWORD '${APP_POSTGRES_PASSWORD}' NOSUPERUSER NOCREATEDB NOCREATEROLE NOREPLICATION;
REVOKE CREATE ON SCHEMA public FROM PUBLIC;
GRANT CONNECT ON DATABASE livekit_lab TO livekit_lab;
GRANT USAGE ON SCHEMA public TO livekit_lab;
SQL
