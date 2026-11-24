"""Flask conserva HTTP, JWT, contraseñas e integraciones; PostgreSQL opera los datos."""
from flask import Flask, jsonify
from flask_cors import CORS
from flask_jwt_extended import JWTManager
from psycopg2 import Error
from sqlalchemy import create_engine
from werkzeug.exceptions import HTTPException
from app.config import get_config

jwt = JWTManager()

def create_app(env=None):
    app = Flask(__name__)
    app.url_map.redirect_defaults = False
    app.config.from_object(get_config(env))
    app.extensions["postgres_engine"] = create_engine(
        app.config["SQLALCHEMY_DATABASE_URI"], pool_pre_ping=True, pool_timeout=10,
    )
    jwt.init_app(app)
    CORS(app, origins=app.config["CORS_ORIGINS"])
    from app.api import api, revoked
    app.register_blueprint(api, url_prefix="/api")
    from app.billing import billing
    app.register_blueprint(billing, url_prefix="/api/billing")
    jwt.token_in_blocklist_loader(lambda header, payload: revoked(payload))

    @app.errorhandler(HTTPException)
    def http_error(error):
        return jsonify(error=error.description), error.code

    @app.errorhandler(Error)
    def database_error(error):
        code = getattr(error, "pgcode", None)
        if code == "42501":
            return jsonify(error="El perfil activo no tiene acceso a esta operación"), 403
        if code == "P0002":
            return jsonify(error="Registro no encontrado"), 404
        if code and (code.startswith("23") or code == "P0001"):
            message = error.diag.message_primary if code == "P0001" else "Datos duplicados, inválidos o relacionados con otros registros"
            return jsonify(error=message), 409
        if code and code.startswith("22"):
            return jsonify(error="Datos con formato o longitud inválidos"), 400
        app.logger.error("PostgreSQL: %s", code or type(error).__name__)
        return jsonify(error="No se pudo acceder a PostgreSQL; comprueba la instalación SQL"), 503

    @app.after_request
    def headers(response):
        response.headers["X-Content-Type-Options"] = "nosniff"
        response.headers["Cache-Control"] = "no-store"
        return response
    return app
