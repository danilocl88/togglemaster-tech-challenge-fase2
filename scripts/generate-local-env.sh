#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "$0")/.." && pwd)"
ENV_FILE="$ROOT_DIR/.env"

if [ -e "$ENV_FILE" ] && [ "${1:-}" != "--force" ]; then
  echo "ERRO: $ENV_FILE ja existe. Use --force para substituir." >&2
  exit 1
fi

random_hex() {
  local bytes="$1"
  if command -v openssl >/dev/null 2>&1; then
    openssl rand -hex "$bytes"
  elif command -v python3 >/dev/null 2>&1; then
    python3 - "$bytes" <<'PY'
import secrets, sys
print(secrets.token_hex(int(sys.argv[1])))
PY
  else
    echo "ERRO: openssl ou python3 e necessario para gerar valores aleatorios." >&2
    exit 1
  fi
}

umask 077
POSTGRES_PASSWORD="$(random_hex 24)"
MASTER_KEY="$(random_hex 32)"
SERVICE_API_KEY="tm_key_$(random_hex 32)"
DYNAMODB_LOCAL_ACCESS_KEY_ID="local_$(random_hex 12)"
DYNAMODB_LOCAL_SECRET_ACCESS_KEY="$(random_hex 32)"

cat > "$ENV_FILE" <<EOF_ENV
POSTGRES_PASSWORD=$POSTGRES_PASSWORD
MASTER_KEY=$MASTER_KEY
SERVICE_API_KEY=$SERVICE_API_KEY
DYNAMODB_LOCAL_ACCESS_KEY_ID=$DYNAMODB_LOCAL_ACCESS_KEY_ID
DYNAMODB_LOCAL_SECRET_ACCESS_KEY=$DYNAMODB_LOCAL_SECRET_ACCESS_KEY
EOF_ENV

chmod 600 "$ENV_FILE"
echo "Arquivo .env criado com valores aleatorios e permissao 600. Os valores nao foram exibidos."
