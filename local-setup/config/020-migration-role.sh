#!/bin/sh
# Run explicitly after PostgreSQL health, for both fresh and retained volumes.
# Never source this script: the bootstrap credential stays in this container.
set +x
set -eu
# Fixed hosts and credentials below must not be redirected through libpq service
# files or an inherited hostaddr that takes precedence over the selected host.
unset PGHOSTADDR PGSERVICE PGSERVICEFILE PGPASSFILE
export LC_ALL=C

fail() {
  printf '%s\n' "$1" >&2
  exit 1
}

if [ "${POSTGRES_USER:-}" != livekit_lab_admin ] || [ "${POSTGRES_DB:-}" != livekit_lab ]; then
  fail 'PostgreSQL bootstrap identity does not match the local database contract'
fi
for credential in "${POSTGRES_PASSWORD:-}" "${APP_POSTGRES_PASSWORD:-}" "${MIGRATION_POSTGRES_PASSWORD:-}"; do
  case "$credential" in
    ''|*[!A-Za-z0-9_-]*) fail 'Invalid PostgreSQL credential format' ;;
  esac
  if [ "${#credential}" -lt 32 ] || [ "${#credential}" -gt 128 ]; then
    fail 'Invalid PostgreSQL credential length'
  fi
done
unset credential

# All SQL is fixed. \password encrypts the new password in psql before sending
# ALTER ROLE, avoiding cleartext credentials in server statement/error logs.
# A private command file leaves stdin available for the two password prompts.
umask 077
script=$(mktemp /tmp/continuity-postgres-bootstrap.XXXXXXXX)
trap 'rm -f "$script"' EXIT HUP INT TERM
cat >"$script" <<'SQL'
\set ON_ERROR_STOP on
\set QUIET on
SELECT pg_advisory_lock(184341, 1);
DO $bootstrap$
BEGIN
  IF current_database() <> 'livekit_lab' OR current_user <> 'livekit_lab_admin' THEN
    RAISE EXCEPTION 'unexpected database bootstrap identity';
  END IF;
  IF EXISTS (SELECT 1 FROM pg_hba_file_rules WHERE error IS NOT NULL
             OR (type LIKE 'host%' AND auth_method <> 'scram-sha-256')) THEN
    RAISE EXCEPTION 'database host authentication must require SCRAM';
  END IF;
  IF NOT EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'livekit_lab'
                 AND rolcanlogin AND NOT rolsuper AND NOT rolcreatedb
                 AND NOT rolcreaterole AND NOT rolreplication AND NOT rolbypassrls)
     OR EXISTS (SELECT 1 FROM pg_auth_members WHERE member = 'livekit_lab'::regrole) THEN
    RAISE EXCEPTION 'runtime role does not match the restricted role contract';
  END IF;
  IF NOT EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'continuity_migrator') THEN
    CREATE ROLE continuity_migrator LOGIN NOSUPERUSER NOCREATEDB NOCREATEROLE
      NOREPLICATION NOBYPASSRLS CONNECTION LIMIT 4;
    COMMENT ON ROLE continuity_migrator IS 'continuity-migrator-v1-pending';
  ELSIF NOT EXISTS (
    SELECT 1 FROM pg_roles WHERE rolname = 'continuity_migrator'
      AND rolcanlogin AND NOT rolsuper AND NOT rolcreatedb AND NOT rolcreaterole
      AND NOT rolreplication AND NOT rolbypassrls AND rolconnlimit = 4
      AND shobj_description(oid, 'pg_authid') IN (
        'continuity-migrator-v1-pending', 'continuity-migrator-v1-ready'
      )
  ) OR EXISTS (
    SELECT 1 FROM pg_auth_members WHERE member = 'continuity_migrator'::regrole
  ) THEN
    RAISE EXCEPTION 'existing migration role does not match the managed role contract';
  END IF;
  IF EXISTS (SELECT 1 FROM pg_authid WHERE rolname = 'continuity_migrator'
              AND rolpassword IS NULL
              AND shobj_description(oid, 'pg_authid') <> 'continuity-migrator-v1-pending') THEN
    RAISE EXCEPTION 'migration role credential is missing outside pending bootstrap';
  END IF;
END
$bootstrap$;
SELECT rolpassword IS NULL AS needs_password
FROM pg_authid WHERE rolname = 'continuity_migrator' \gset
\if :needs_password
\password continuity_migrator
\endif
-- Keep this advisory lock until both real TCP authentication probes finish.
-- Socket trust cannot prove that a retained role matches the retained secret.
\! PGPASSWORD="$MIGRATION_POSTGRES_PASSWORD" psql -X -q --no-password --host=127.0.0.1 --port=5432 --username=continuity_migrator --dbname=livekit_lab --command='SELECT 1' >/dev/null 2>&1
\if :SHELL_ERROR
SELECT 1 / 0;
\endif
\! PGPASSWORD="$APP_POSTGRES_PASSWORD" psql -X -q --no-password --host=127.0.0.1 --port=5432 --username=livekit_lab --dbname=livekit_lab --command='SELECT 1' >/dev/null 2>&1
\if :SHELL_ERROR
SELECT 1 / 0;
\endif
BEGIN;
REVOKE CREATE, TEMPORARY ON DATABASE livekit_lab FROM PUBLIC, livekit_lab, continuity_migrator;
REVOKE CREATE ON SCHEMA public FROM PUBLIC, livekit_lab, continuity_migrator;
GRANT CONNECT ON DATABASE livekit_lab TO livekit_lab;
GRANT CONNECT, CREATE ON DATABASE livekit_lab TO continuity_migrator;
DO $privileges$
BEGIN
  IF has_database_privilege('livekit_lab', 'livekit_lab', 'CREATE')
     OR has_database_privilege('livekit_lab', 'livekit_lab', 'TEMPORARY')
     OR EXISTS (SELECT 1 FROM pg_namespace WHERE
       nspname !~ '^pg_' AND nspname <> 'information_schema'
       AND (nspowner = 'livekit_lab'::regrole
            OR has_schema_privilege('livekit_lab', oid, 'CREATE')))
     OR EXISTS (SELECT 1 FROM pg_class WHERE relowner = 'livekit_lab'::regrole) THEN
    RAISE EXCEPTION 'runtime role retains schema or table administration privileges';
  END IF;
END
$privileges$;
COMMENT ON ROLE continuity_migrator IS 'continuity-migrator-v1-ready';
COMMIT;
SELECT pg_advisory_unlock(184341, 1);
SQL

export PGCONNECT_TIMEOUT=3
export PGOPTIONS='-c statement_timeout=5000 -c lock_timeout=1000 -c idle_in_transaction_session_timeout=10000'
# No password occurs in the command argv or SQL file. Existing non-null role
# credentials are verified and never rotated; a pending NULL role can resume.
if ! printf '%s\n%s\n' "$MIGRATION_POSTGRES_PASSWORD" "$MIGRATION_POSTGRES_PASSWORD" |
  PGPASSWORD="$POSTGRES_PASSWORD" psql -X -q --no-password --host=/var/run/postgresql \
    --port=5432 --username=livekit_lab_admin --dbname=livekit_lab --file="$script" >/dev/null 2>&1; then
  fail 'PostgreSQL migration role preparation failed; inspect role policy and retained credentials'
fi
printf '%s\n' 'PostgreSQL migration role prepared; existing credentials preserved'
