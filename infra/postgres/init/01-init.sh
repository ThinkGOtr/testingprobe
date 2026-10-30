#!/usr/bin/env bash
# Boş volume'de bir kez çalışır (docker-entrypoint-initdb.d, postgres süper kullanıcısı).
# Roller ve veritabanları; şema ve yetkiler core/alembic migrasyonlarında.
set -euo pipefail

: "${TP_OWNER_PASSWORD:?}" "${TP_APP_PASSWORD:?}" "${DEMOAPP_OWNER_PASSWORD:?}" "${DEMOAPP_PASSWORD:?}"

psql -v ON_ERROR_STOP=1 --username "${POSTGRES_USER:-postgres}" --dbname postgres \
  -v tp_owner_pw="$TP_OWNER_PASSWORD" \
  -v tp_app_pw="$TP_APP_PASSWORD" \
  -v demoapp_owner_pw="$DEMOAPP_OWNER_PASSWORD" \
  -v demoapp_pw="$DEMOAPP_PASSWORD" <<'SQL'
CREATE ROLE tp_owner LOGIN PASSWORD :'tp_owner_pw';
CREATE ROLE tp_app LOGIN PASSWORD :'tp_app_pw';
CREATE ROLE demoapp_owner LOGIN PASSWORD :'demoapp_owner_pw';
CREATE ROLE demoapp LOGIN PASSWORD :'demoapp_pw';

CREATE DATABASE tp OWNER tp_owner;
CREATE DATABASE demoapp OWNER demoapp_owner;

REVOKE CONNECT, TEMPORARY ON DATABASE tp FROM PUBLIC;
REVOKE CONNECT, TEMPORARY ON DATABASE demoapp FROM PUBLIC;
GRANT CONNECT ON DATABASE tp TO tp_app;
GRANT CONNECT ON DATABASE demoapp TO demoapp;
SQL
