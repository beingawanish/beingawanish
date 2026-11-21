#!/usr/bin/env bash
# Creates one database and one owner role per service (database-per-service, ADR-003),
# a least-privilege "debezium" replication role, and a "temporal" role for the optional
# Temporal profile. Runs once, on the first start of an empty data volume.
#
# Dev-only credentials: every password equals its role name. Real environments inject secrets.
set -euo pipefail

SERVICES="catalog checkout order payment inventory fulfilment shipping notification returns"

psql -v ON_ERROR_STOP=1 --username "$POSTGRES_USER" --dbname postgres <<-SQL
  CREATE ROLE debezium WITH LOGIN REPLICATION PASSWORD 'debezium';
  CREATE ROLE temporal WITH LOGIN CREATEDB PASSWORD 'temporal';
SQL

for svc in $SERVICES; do
  role="${svc}_svc"
  db="${svc}_db"
  echo "creating ${db} owned by ${role}"
  psql -v ON_ERROR_STOP=1 --username "$POSTGRES_USER" --dbname postgres <<-SQL
    CREATE ROLE ${role} WITH LOGIN PASSWORD '${role}';
    CREATE DATABASE ${db} OWNER ${role};
    REVOKE ALL ON DATABASE ${db} FROM PUBLIC;
    GRANT CONNECT ON DATABASE ${db} TO ${role};
    GRANT CONNECT ON DATABASE ${db} TO debezium;
SQL
  # The service role owns the public schema so its migrations can create tables and the publication.
  psql -v ON_ERROR_STOP=1 --username "$POSTGRES_USER" --dbname "${db}" <<-SQL
    ALTER SCHEMA public OWNER TO ${role};
    GRANT USAGE ON SCHEMA public TO debezium;
SQL
done
