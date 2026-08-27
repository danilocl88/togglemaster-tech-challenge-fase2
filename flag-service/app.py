import logging
import os
import sys
from contextlib import contextmanager
from functools import wraps

import psycopg2
import requests
from dotenv import load_dotenv
from flask import Flask, jsonify, request
from psycopg2.extras import RealDictCursor
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
    log.info("Pool de conexoes com PostgreSQL inicializado.")
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


@app.route("/flags", methods=["POST"])
@require_auth
def create_flag():
    data = request.get_json(silent=True)
    if not data or not str(data.get("name", "")).strip():
        return jsonify({"error": "'name' e obrigatorio"}), 400

    name = str(data["name"]).strip()
    description = str(data.get("description", ""))
    if "is_enabled" in data and not isinstance(data["is_enabled"], bool):
        return jsonify({"error": "'is_enabled' deve ser booleano"}), 400
    is_enabled = data.get("is_enabled", False)

    try:
        with db_cursor() as cur:
            cur.execute(
                "INSERT INTO flags (name, description, is_enabled, created_at, updated_at) "
                "VALUES (%s, %s, %s, NOW(), NOW()) RETURNING *",
                (name, description, is_enabled),
            )
            new_flag = cur.fetchone()
        log.info("Flag '%s' criada com sucesso.", name)
        return jsonify(new_flag), 201
    except psycopg2.IntegrityError:
        log.warning("Tentativa de criar flag duplicada: '%s'", name)
        return jsonify({"error": f"Flag '{name}' ja existe"}), 409
    except Exception as exc:
        log.exception("Erro ao criar flag: %s", exc)
        return jsonify({"error": "Erro interno do servidor"}), 500


@app.route("/flags", methods=["GET"])
@require_auth
def get_flags():
    try:
        with db_cursor() as cur:
            cur.execute("SELECT * FROM flags ORDER BY name")
            return jsonify(cur.fetchall())
    except Exception as exc:
        log.exception("Erro ao buscar flags: %s", exc)
        return jsonify({"error": "Erro interno do servidor"}), 500


@app.route("/flags/<string:name>", methods=["GET"])
@require_auth
def get_flag(name):
    try:
        with db_cursor() as cur:
            cur.execute("SELECT * FROM flags WHERE name = %s", (name,))
            flag = cur.fetchone()
        if not flag:
            return jsonify({"error": "Flag nao encontrada"}), 404
        return jsonify(flag)
    except Exception as exc:
        log.exception("Erro ao buscar flag '%s': %s", name, exc)
        return jsonify({"error": "Erro interno do servidor"}), 500


@app.route("/flags/<string:name>", methods=["PUT"])
@require_auth
def update_flag(name):
    data = request.get_json(silent=True)
    if not data:
        return jsonify({"error": "Corpo da requisicao obrigatorio"}), 400

    fields = []
    values = []
    if "description" in data:
        fields.append("description = %s")
        values.append(str(data["description"]))
    if "is_enabled" in data:
        if not isinstance(data["is_enabled"], bool):
            return jsonify({"error": "'is_enabled' deve ser booleano"}), 400
        fields.append("is_enabled = %s")
        values.append(data["is_enabled"])
    if not fields:
        return jsonify({"error": "Informe 'description' e/ou 'is_enabled'"}), 400

    values.append(name)
    query = f"UPDATE flags SET {', '.join(fields)} WHERE name = %s RETURNING *"

    try:
        with db_cursor() as cur:
            cur.execute(query, tuple(values))
            updated_flag = cur.fetchone()
        if not updated_flag:
            return jsonify({"error": "Flag nao encontrada"}), 404
        log.info("Flag '%s' atualizada com sucesso.", name)
        return jsonify(updated_flag), 200
    except Exception as exc:
        log.exception("Erro ao atualizar flag '%s': %s", name, exc)
        return jsonify({"error": "Erro interno do servidor"}), 500


@app.route("/flags/<string:name>", methods=["DELETE"])
@require_auth
def delete_flag(name):
    try:
        with db_cursor(dict_rows=False) as cur:
            cur.execute("DELETE FROM flags WHERE name = %s", (name,))
            deleted = cur.rowcount
        if deleted == 0:
            return jsonify({"error": "Flag nao encontrada"}), 404
        log.info("Flag '%s' deletada com sucesso.", name)
        return "", 204
    except Exception as exc:
        log.exception("Erro ao deletar flag '%s': %s", name, exc)
        return jsonify({"error": "Erro interno do servidor"}), 500


if __name__ == "__main__":
    port = int(os.getenv("PORT", "8002"))
    app.run(host="0.0.0.0", port=port, debug=False)
