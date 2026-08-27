#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "$0")/.." && pwd)"
if [ -f "$ROOT_DIR/.env" ]; then
  set -a
  # shellcheck disable=SC1091
  . "$ROOT_DIR/.env"
  set +a
fi

: "${SERVICE_API_KEY:?SERVICE_API_KEY deve ser definida em .env ou no ambiente}"
API_KEY="$SERVICE_API_KEY"
EXPECTED_CONTAINERS=9

cd "$ROOT_DIR"

echo "=== CONTAINERS ==="
docker compose ps

running_count=$(docker ps --filter "name=togglemaster" --format '{{.Names}}' | wc -l | tr -d ' ')
if [ "$running_count" -ne "$EXPECTED_CONTAINERS" ]; then
  echo "ERRO: esperado $EXPECTED_CONTAINERS containers ToggleMaster em execucao; encontrado $running_count." >&2
  exit 1
fi
echo "OK: $running_count containers em execucao."

echo
echo "=== HEALTH CHECKS ==="
for port in 8001 8002 8003 8004 8005; do
  printf 'porta %s: ' "$port"
  curl -fsS "http://127.0.0.1:${port}/health"
  echo
done

echo
echo "=== REDIS ==="
docker exec togglemaster-redis redis-cli ping | grep -q '^PONG$'
echo "Redis: PONG"

echo
echo "=== DYNAMODB LOCAL ==="
"$(dirname "$0")/init-dynamodb-local.sh" >/dev/null
aws dynamodb describe-table \
  --endpoint-url http://127.0.0.1:8000 \
  --region us-east-1 \
  --table-name ToggleMasterAnalytics \
  --query 'Table.TableStatus' \
  --output text

echo
echo "=== API KEY ==="
curl -fsS "http://127.0.0.1:8001/validate" \
  -H "Authorization: Bearer ${API_KEY}"
echo

echo
echo "=== FLAG ==="
curl -fsS "http://127.0.0.1:8002/flags" \
  -H "Authorization: Bearer ${API_KEY}"
echo

echo
echo "=== TARGETING ==="
curl -fsS "http://127.0.0.1:8003/rules/enable-new-dashboard" \
  -H "Authorization: Bearer ${API_KEY}"
echo

echo
echo "=== EVALUATION ==="
curl -fsS "http://127.0.0.1:8004/evaluate?user_id=user-123&flag_name=enable-new-dashboard"
echo

echo
echo "OK: validacao local concluida."
