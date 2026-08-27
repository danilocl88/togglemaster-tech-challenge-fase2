#!/bin/bash
set -euo pipefail

psql -v ON_ERROR_STOP=1 --username "$POSTGRES_USER" --dbname "$POSTGRES_DB" \
  -tc "SELECT 1 FROM pg_database WHERE datname='targeting_db'" | grep -q 1 \
  || psql -v ON_ERROR_STOP=1 --username "$POSTGRES_USER" --dbname "$POSTGRES_DB" \
     -c "CREATE DATABASE targeting_db"

psql -v ON_ERROR_STOP=1 --username "$POSTGRES_USER" --dbname targeting_db \
  -f /tmp/togglemaster-targeting-init.sql

psql -v ON_ERROR_STOP=1 --username "$POSTGRES_USER" --dbname targeting_db <<'EOSQL'
INSERT INTO targeting_rules (flag_name, is_enabled, rules)
VALUES ('enable-new-dashboard', true, '{"type":"PERCENTAGE","value":50}'::jsonb)
ON CONFLICT (flag_name) DO UPDATE
SET is_enabled = EXCLUDED.is_enabled,
    rules = EXCLUDED.rules,
    updated_at = NOW();
EOSQL
