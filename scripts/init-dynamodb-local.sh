#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "$0")/.." && pwd)"
if [ -f "$ROOT_DIR/.env" ]; then
  set -a
  # shellcheck disable=SC1091
  . "$ROOT_DIR/.env"
  set +a
fi

: "${DYNAMODB_LOCAL_ACCESS_KEY_ID:?DYNAMODB_LOCAL_ACCESS_KEY_ID deve ser definida em .env ou no ambiente}"
: "${DYNAMODB_LOCAL_SECRET_ACCESS_KEY:?DYNAMODB_LOCAL_SECRET_ACCESS_KEY deve ser definida em .env ou no ambiente}"

export AWS_ACCESS_KEY_ID="$DYNAMODB_LOCAL_ACCESS_KEY_ID"
export AWS_SECRET_ACCESS_KEY="$DYNAMODB_LOCAL_SECRET_ACCESS_KEY"
export AWS_DEFAULT_REGION="${AWS_DEFAULT_REGION:-us-east-1}"

ENDPOINT="${DYNAMODB_LOCAL_ENDPOINT:-http://127.0.0.1:8000}"
REGION="$AWS_DEFAULT_REGION"
TABLE_NAME="${DYNAMODB_TABLE_NAME:-ToggleMasterAnalytics}"

echo "Validando DynamoDB Local em ${ENDPOINT} ..."
aws dynamodb list-tables --endpoint-url "$ENDPOINT" --region "$REGION" >/dev/null

if aws dynamodb describe-table --endpoint-url "$ENDPOINT" --region "$REGION" --table-name "$TABLE_NAME" >/dev/null 2>&1; then
  echo "Tabela ${TABLE_NAME} ja existe."
else
  echo "Criando tabela ${TABLE_NAME} ..."
  aws dynamodb create-table \
    --endpoint-url "$ENDPOINT" \
    --region "$REGION" \
    --table-name "$TABLE_NAME" \
    --attribute-definitions AttributeName=event_id,AttributeType=S \
    --key-schema AttributeName=event_id,KeyType=HASH \
    --billing-mode PAY_PER_REQUEST >/dev/null

  aws dynamodb wait table-exists \
    --endpoint-url "$ENDPOINT" \
    --region "$REGION" \
    --table-name "$TABLE_NAME"
fi

aws dynamodb list-tables --endpoint-url "$ENDPOINT" --region "$REGION"
