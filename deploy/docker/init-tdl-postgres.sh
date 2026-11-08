#!/usr/bin/env bash
set -euo pipefail
# Entrypoint runs this only for a new, empty TDL volume.
psql --username "$POSTGRES_USER" --dbname postgres --set ON_ERROR_STOP=1 <<'SQL'
\getenv tdl_password TDL_POSTGRES_PASSWORD
CREATE ROLE tdl LOGIN PASSWORD :'tdl_password' NOSUPERUSER NOCREATEDB NOCREATEROLE NOREPLICATION;
CREATE DATABASE tdl OWNER tdl;
REVOKE ALL ON DATABASE tdl FROM PUBLIC;
SQL
