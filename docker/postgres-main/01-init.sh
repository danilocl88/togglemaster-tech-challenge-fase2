#!/bin/bash
set -euo pipefail

: "${SERVICE_API_KEY:?SERVICE_API_KEY deve ser definida em runtime}"

create_db_if_missing() {
  local db_name="$1"
  psql -v ON_ERROR_STOP=1 --username "$POSTGRES_USER" --dbname "$POSTGRES_DB" \
    -tc "SELECT 1 FROM pg_database WHERE datname='${db_name}'" | grep -q 1 \
    || psql -v ON_ERROR_STOP=1 --username "$POSTGRES_USER" --dbname "$POSTGRES_DB" \
       -c "CREATE DATABASE ${db_name}"
}

create_db_if_missing auth_db
create_db_if_missing flags_db

psql -v ON_ERROR_STOP=1 --username "$POSTGRES_USER" --dbname auth_db \
  -f /tmp/togglemaster-auth-init.sql

# A chave de API local vem do ambiente e apenas seu SHA-256 e persistido no banco.
api_key_hash="$(printf '%s' "$SERVICE_API_KEY" | sha256sum | awk '{print $1}')"
psql -v ON_ERROR_STOP=1 --username "$POSTGRES_USER" --dbname auth_db \
  -v api_key_hash="$api_key_hash" <<'EOSQL'
INSERT INTO api_keys (name, key_hash, is_active)
VALUES ('local-runtime-key', :'api_key_hash', true)
ON CONFLICT (key_hash) DO UPDATE
SET name = EXCLUDED.name,
    is_active = true;
EOSQL

psql -v ON_ERROR_STOP=1 --username "$POSTGRES_USER" --dbname flags_db \
  -f /tmp/togglemaster-flags-init.sql

psql -v ON_ERROR_STOP=1 --username "$POSTGRES_USER" --dbname flags_db <<'EOSQL'
INSERT INTO flags (name, description, is_enabled)
VALUES ('enable-new-dashboard', 'Flag local criada automaticamente pelo Docker Compose', true)
ON CONFLICT (name) DO UPDATE
SET description = EXCLUDED.description,
    is_enabled = EXCLUDED.is_enabled,
    updated_at = NOW();
EOSQL
