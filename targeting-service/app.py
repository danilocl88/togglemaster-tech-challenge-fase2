import logging
import os
import sys
from contextlib import contextmanager
from functools import wraps

import psycopg2
import requests
from dotenv import load_dotenv
from flask import Flask, jsonify, request
from psycopg2.extras import Json, RealDictCursor
from psycopg2.pool import ThreadedConnectionPool

logging.basicConfig(level=logging.INFO)
log = logging.getLogger(__name__)
load_dotenv()

app = Flask(__name__)
DATABASE_URL = os.getenv("DATABASE_URL")
AUTH_SERVICE_URL = os.getenv("AUTH_SERVICE_URL")

if not DATABASE_URL or not AUTH_SERVICE_URL:
    log.critical("DATABASE_URL e AUTH_SERVICE_URL devem ser definidos.")
    sys.exit(1)

try:
    pool = ThreadedConnectionPool(1, 5, dsn=DATABASE_URL)
    log.info("Pool de conexoes com PostgreSQL (targeting) inicializado.")
except psycopg2.OperationalError as exc:
    log.critical("Erro fatal ao conectar ao PostgreSQL: %s", exc)
    sys.exit(1)


@contextmanager
def db_cursor(dict_rows=True):
    conn = pool.getconn()
    conn.autocommit = True
    cur = conn.cursor(cursor_factory=RealDictCursor if dict_rows else None)
    try:
        yield cur
    finally:
        cur.close()
        pool.putconn(conn)


def require_auth(func):
    @wraps(func)
    def decorated(*args, **kwargs):
        auth_header = request.headers.get("Authorization")
        if not auth_header:
            return jsonify({"error": "Authorization header obrigatorio"}), 401

        try:
            response = requests.get(
                f"{AUTH_SERVICE_URL}/validate",
                headers={"Authorization": auth_header},
                timeout=3,
            )
            if response.status_code in (401, 403):
                log.warning("Chave rejeitada pelo auth-service (status: %s)", response.status_code)
                return jsonify({"error": "Chave de API invalida"}), 401
            if response.status_code != 200:
                log.error("auth-service indisponivel ou com falha (status: %s)", response.status_code)
                return jsonify({"error": "Servico de autenticacao indisponivel"}), 503
        except requests.exceptions.Timeout:
            log.error("Timeout ao conectar com o auth-service")
            return jsonify({"error": "Servico de autenticacao indisponivel (timeout)"}), 504
        except requests.exceptions.RequestException as exc:
            log.error("Erro ao conectar com o auth-service: %s", exc)
            return jsonify({"error": "Servico de autenticacao indisponivel"}), 503

        return func(*args, **kwargs)

    return decorated


@app.route("/health")
def health():
    return jsonify({"status": "ok"})


@app.route("/rules", methods=["POST"])
@require_auth
def create_rule():
    data = request.get_json(silent=True)
    if not data or not str(data.get("flag_name", "")).strip() or "rules" not in data:
        return jsonify({"error": "'flag_name' e 'rules' (JSON) sao obrigatorios"}), 400
    if not isinstance(data["rules"], dict):
        return jsonify({"error": "'rules' deve ser um objeto JSON"}), 400

    flag_name = str(data["flag_name"]).strip()
    rules_obj = data["rules"]
    if "is_enabled" in data and not isinstance(data["is_enabled"], bool):
        return jsonify({"error": "'is_enabled' deve ser booleano"}), 400
    is_enabled = data.get("is_enabled", True)

    try:
        with db_cursor() as cur:
            cur.execute(
                "INSERT INTO targeting_rules (flag_name, is_enabled, rules, created_at, updated_at) "
                "VALUES (%s, %s, %s, NOW(), NOW()) RETURNING *",
                (flag_name, is_enabled, Json(rules_obj)),
            )
            new_rule = cur.fetchone()
        log.info("Regra para '%s' criada com sucesso.", flag_name)
        return jsonify(new_rule), 201
    except psycopg2.IntegrityError:
        log.warning("Tentativa de criar regra duplicada: '%s'", flag_name)
        return jsonify({"error": f"Regra para a flag '{flag_name}' ja existe"}), 409
    except Exception as exc:
        log.exception("Erro ao criar regra: %s", exc)
        return jsonify({"error": "Erro interno do servidor"}), 500


@app.route("/rules/<string:flag_name>", methods=["GET"])
@require_auth
def get_rule(flag_name):
    try:
        with db_cursor() as cur:
            cur.execute("SELECT * FROM targeting_rules WHERE flag_name = %s", (flag_name,))
            rule = cur.fetchone()
        if not rule:
            return jsonify({"error": "Regra nao encontrada"}), 404
        return jsonify(rule)
    except Exception as exc:
        log.exception("Erro ao buscar regra '%s': %s", flag_name, exc)
        return jsonify({"error": "Erro interno do servidor"}), 500


@app.route("/rules/<string:flag_name>", methods=["PUT"])
@require_auth
def update_rule(flag_name):
    data = request.get_json(silent=True)
    if not data:
        return jsonify({"error": "Corpo da requisicao obrigatorio"}), 400

    fields = []
    values = []
    if "rules" in data:
        if not isinstance(data["rules"], dict):
            return jsonify({"error": "'rules' deve ser um objeto JSON"}), 400
        fields.append("rules = %s")
        values.append(Json(data["rules"]))
    if "is_enabled" in data:
        if not isinstance(data["is_enabled"], bool):
            return jsonify({"error": "'is_enabled' deve ser booleano"}), 400
        fields.append("is_enabled = %s")
        values.append(data["is_enabled"])
    if not fields:
        return jsonify({"error": "Informe 'rules' e/ou 'is_enabled'"}), 400

    values.append(flag_name)
    query = f"UPDATE targeting_rules SET {', '.join(fields)} WHERE flag_name = %s RETURNING *"

    try:
        with db_cursor() as cur:
            cur.execute(query, tuple(values))
            updated_rule = cur.fetchone()
        if not updated_rule:
            return jsonify({"error": "Regra nao encontrada"}), 404
        log.info("Regra para '%s' atualizada com sucesso.", flag_name)
        return jsonify(updated_rule), 200
    except Exception as exc:
        log.exception("Erro ao atualizar regra '%s': %s", flag_name, exc)
        return jsonify({"error": "Erro interno do servidor"}), 500


@app.route("/rules/<string:flag_name>", methods=["DELETE"])
@require_auth
def delete_rule(flag_name):
    try:
        with db_cursor(dict_rows=False) as cur:
            cur.execute("DELETE FROM targeting_rules WHERE flag_name = %s", (flag_name,))
            deleted = cur.rowcount
        if deleted == 0:
            return jsonify({"error": "Regra nao encontrada"}), 404
        log.info("Regra para '%s' deletada com sucesso.", flag_name)
        return "", 204
    except Exception as exc:
        log.exception("Erro ao deletar regra '%s': %s", flag_name, exc)
        return jsonify({"error": "Erro interno do servidor"}), 500


if __name__ == "__main__":
    port = int(os.getenv("PORT", "8003"))
    app.run(host="0.0.0.0", port=port, debug=False)
