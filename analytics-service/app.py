import json
import logging
import os
import sys
import threading
import time
import uuid
from datetime import datetime, timezone

import boto3
from botocore.exceptions import ClientError
from dotenv import load_dotenv
from flask import Flask, jsonify

logging.basicConfig(level=logging.INFO, format="%(asctime)s - %(levelname)s - %(message)s")
log = logging.getLogger(__name__)
load_dotenv()

AWS_REGION = os.getenv("AWS_REGION") or os.getenv("AWS_DEFAULT_REGION") or "us-east-1"
SQS_QUEUE_URL = (os.getenv("AWS_SQS_URL") or "").strip()
DYNAMODB_TABLE_NAME = (os.getenv("AWS_DYNAMODB_TABLE") or "").strip()
SQS_ENDPOINT = (os.getenv("AWS_SQS_ENDPOINT") or "").strip() or None
DYNAMODB_ENDPOINT = (os.getenv("AWS_DYNAMODB_ENDPOINT") or "").strip() or None

sqs_client = None
dynamodb_client = None
worker_enabled = bool(SQS_QUEUE_URL)

if worker_enabled:
    if not DYNAMODB_TABLE_NAME:
        log.critical("AWS_DYNAMODB_TABLE deve ser definida quando AWS_SQS_URL estiver habilitada.")
        sys.exit(1)

    try:
        session = boto3.Session(region_name=AWS_REGION)
        sqs_client = session.client("sqs", endpoint_url=SQS_ENDPOINT)
        dynamodb_client = session.client("dynamodb", endpoint_url=DYNAMODB_ENDPOINT)
        log.info("Clientes AWS inicializados na regiao %s", AWS_REGION)
    except Exception as exc:
        log.critical("Erro ao inicializar clientes AWS: %s", exc)
        sys.exit(1)
else:
    # O compose local possui exatamente 9 containers e nao inclui um emulador de SQS.
    # Nesse modo, o health check permanece disponivel e o fluxo SQS->DynamoDB e validado na nuvem.
    log.info("AWS_SQS_URL nao definida. Worker SQS desabilitado neste ambiente.")


def process_message(message):
    """Processa uma mensagem SQS e persiste o evento no DynamoDB."""
    try:
        message_id = message.get("MessageId", "desconhecido")
        log.info("Processando mensagem ID: %s", message_id)
        body = json.loads(message["Body"])

        required = ("user_id", "flag_name", "result")
        missing = [key for key in required if key not in body]
        if missing:
            raise ValueError(f"Campos ausentes na mensagem: {', '.join(missing)}")
        if not str(body["user_id"]).strip() or not str(body["flag_name"]).strip():
            raise ValueError("user_id e flag_name nao podem ser vazios")
        if not isinstance(body["result"], bool):
            raise ValueError("result deve ser booleano")

        # O fluxo real do evaluation-service nao envia event_id. Em testes manuais,
        # um event_id opcional pode ser preservado para facilitar rastreabilidade.
        event_id = str(body.get("event_id") or uuid.uuid4())
        item = {
            "event_id": {"S": event_id},
            "user_id": {"S": str(body["user_id"])},
            "flag_name": {"S": str(body["flag_name"])},
            "result": {"BOOL": body["result"]},
            "timestamp": {"S": str(body.get("timestamp") or datetime.now(timezone.utc).isoformat())},
        }

        dynamodb_client.put_item(TableName=DYNAMODB_TABLE_NAME, Item=item)
        log.info("Evento %s (Flag: %s) salvo no DynamoDB.", event_id, body["flag_name"])

        sqs_client.delete_message(
            QueueUrl=SQS_QUEUE_URL,
            ReceiptHandle=message["ReceiptHandle"],
        )
    except json.JSONDecodeError:
        log.exception("JSON invalido na mensagem SQS")
    except (KeyError, ValueError):
        log.exception("Mensagem SQS com formato invalido")
    except ClientError:
        log.exception("Erro AWS ao processar mensagem SQS")
    except Exception:
        log.exception("Erro inesperado ao processar mensagem SQS")


def sqs_worker_loop():
    """Long polling da fila SQS."""
    log.info("Iniciando worker SQS...")
    while True:
        try:
            response = sqs_client.receive_message(
                QueueUrl=SQS_QUEUE_URL,
                MaxNumberOfMessages=10,
                WaitTimeSeconds=20,
            )
            for message in response.get("Messages", []):
                process_message(message)
        except ClientError:
            log.exception("Erro AWS no loop principal do SQS")
            time.sleep(10)
        except Exception:
            log.exception("Erro inesperado no loop principal do SQS")
            time.sleep(10)


app = Flask(__name__)


@app.route("/health")
def health():
    return jsonify({"status": "ok"})


def start_worker():
    if not worker_enabled:
        return
    worker_thread = threading.Thread(target=sqs_worker_loop, daemon=True, name="sqs-worker")
    worker_thread.start()


# O deployment/compose usa um unico worker Gunicorn para evitar consumidores duplicados.
start_worker()


if __name__ == "__main__":
    port = int(os.getenv("PORT", "8005"))
    app.run(host="0.0.0.0", port=port, debug=False)
