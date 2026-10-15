# shellcheck shell=bash
# Sourced by the sclorg PostgreSQL image after each start, once the database
# exists (as the postgres superuser): enable pgvector, idempotently.
psql -v ON_ERROR_STOP=1 -d "$POSTGRESQL_DATABASE" -c 'CREATE EXTENSION IF NOT EXISTS vector;'
