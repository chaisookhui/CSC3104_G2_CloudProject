#!/bin/sh
set -eu

# Only initializes a NEW main-project volume. Each service owns its own database.
psql -v ON_ERROR_STOP=1 --username "$POSTGRES_USER" --dbname postgres \
  --set=app_password="$APP_DATABASE_PASSWORD" <<'SQL'
CREATE ROLE seat_service LOGIN PASSWORD :'app_password';
CREATE ROLE allocation_service LOGIN PASSWORD :'app_password';
CREATE ROLE dispatcher_service LOGIN PASSWORD :'app_password';
CREATE ROLE payment_service LOGIN PASSWORD :'app_password';
CREATE DATABASE seats OWNER seat_service;
CREATE DATABASE allocation OWNER allocation_service;
CREATE DATABASE dispatcher OWNER dispatcher_service;
CREATE DATABASE payment OWNER payment_service;
SQL
