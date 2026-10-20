#!/bin/sh
set -eu

# Runs only when Docker initializes an empty PostgreSQL data volume.
# psql variables quote the password as an SQL literal, never as SQL code.
psql -v ON_ERROR_STOP=1 --username "$POSTGRES_USER" --dbname "$POSTGRES_DB" \
  --set=app_password="$SEAT_STORE_DB_PASSWORD" <<'SQL'
CREATE ROLE seat_store LOGIN PASSWORD :'app_password';
ALTER DATABASE seat_booking OWNER TO seat_store;
GRANT ALL ON SCHEMA public TO seat_store;
CREATE DATABASE seat_booking_test OWNER seat_store;
SQL

