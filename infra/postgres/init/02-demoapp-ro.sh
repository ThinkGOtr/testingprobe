#!/usr/bin/env bash
# Boş volume'de bir kez çalışır (01-init.sh'den sonra, postgres süper kullanıcısı).
# demoapp veritabanı: uygulama rolü (demoapp) tablolarını kendisi kurar → public şemada CREATE.
# Salt okuma rolü (demoapp_ro): tutarlılık denetimi için. Tablo yetkileri (yalnızca urun, kampanya,
# ayar ve bayi'nin parola özeti dışındaki kolonları) demo-app-api tablo kurulumundan sonra verir;
# sipariş, sepet ve oturum tablolarına hiçbir zaman yetki verilmez.
set -euo pipefail

: "${DEMOAPP_RO_PASSWORD:?}"

psql -v ON_ERROR_STOP=1 --username "${POSTGRES_USER:-postgres}" --dbname postgres \
  -v demoapp_ro_pw="$DEMOAPP_RO_PASSWORD" <<'SQL'
CREATE ROLE demoapp_ro LOGIN PASSWORD :'demoapp_ro_pw'
  NOSUPERUSER NOCREATEDB NOCREATEROLE NOINHERIT;
ALTER ROLE demoapp_ro SET default_transaction_read_only = on;
ALTER ROLE demoapp_ro SET statement_timeout = '5s';
GRANT CONNECT ON DATABASE demoapp TO demoapp_ro;

\connect demoapp
REVOKE ALL ON SCHEMA public FROM PUBLIC;
GRANT USAGE, CREATE ON SCHEMA public TO demoapp;
GRANT USAGE ON SCHEMA public TO demoapp_ro;
SQL
