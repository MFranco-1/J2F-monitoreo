"""
app/__init__.py - Flask Application Factory para J2F Monitoreo
"""

from flask import Flask, jsonify, request
from flask_cors import CORS
from flask_jwt_extended import JWTManager
from flask_sqlalchemy import SQLAlchemy
from sqlalchemy.exc import DataError, IntegrityError, SQLAlchemyError
from werkzeug.exceptions import BadRequest, HTTPException

from app.config import get_config

# Extensiones globales (sin vincular aún a una app)
db = SQLAlchemy()
jwt = JWTManager()


def create_app(env: str = None) -> Flask:
    """
    Factory de la aplicación Flask.
    Registra extensiones, blueprints y configuración.
    """
    app = Flask(__name__)
    cfg = get_config(env)
    app.config.from_object(cfg)

    # Inicializar extensiones
    db.init_app(app)
    jwt.init_app(app)
    CORS(app, origins=app.config.get("CORS_ORIGINS", ["http://localhost:4200"]))

    @app.after_request
    def response_security(response):
        response.headers.setdefault("X-Content-Type-Options", "nosniff")
        if request.path.startswith("/api/"):
            response.headers.setdefault("Cache-Control", "no-store")
        return response

    # Registrar Blueprints (vistas/rutas)
    _register_blueprints(app)

    from app.controllers.auth_controller import is_token_revoked

    @jwt.token_in_blocklist_loader
    def token_is_revoked(_header, payload):
        return is_token_revoked(payload)

    @jwt.revoked_token_loader
    def revoked_token(_header, _payload):
        return jsonify(
            {"error": "La sesión terminó o la cuenta cambió. Inicia sesión nuevamente."}
        ), 401

    @app.before_request
    def validate_json_body():
        if request.path.startswith("/api/") and request.method in {"POST", "PUT", "PATCH"}:
            if request.content_length and not isinstance(request.get_json(silent=True), dict):
                raise BadRequest("Envía un objeto JSON válido")

    @app.errorhandler(HTTPException)
    def http_error(error):
        db.session.rollback()
        return jsonify({"error": error.description}), error.code

    @app.errorhandler(IntegrityError)
    @app.errorhandler(DataError)
    def database_input_error(error):
        db.session.rollback()
        app.logger.warning("Datos rechazados: %s", type(error).__name__)
        return jsonify(
            {"error": "Datos duplicados, inválidos o relacionados con otros registros"}
        ), 409

    @app.errorhandler(SQLAlchemyError)
    def database_error(error):
        db.session.rollback()
        app.logger.error("Error al acceder a PostgreSQL: %s", type(error).__name__)
        return jsonify(
            {"error": "No se pudo acceder a los datos. Contacta al administrador del sistema."}
        ), 503

    # Solo las pruebas crean tablas y datos en su base aislada.
    if app.config.get("TESTING"):
        from app.testing_fixtures import seed_testing_data

        with app.app_context():
            if db.engine.dialect.name != "sqlite":
                db.engine.dispose()
                raise RuntimeError("Las pruebas requieren una base SQLite aislada")
            db.create_all()
            seed_testing_data()

    return app


def _register_blueprints(app: Flask) -> None:
    """Registrar todos los blueprints de rutas."""
    from app.views.alert_routes import alert_bp
    from app.views.assignment_routes import assignment_bp
    from app.views.auth_routes import auth_bp
    from app.views.master_data_routes import master_data_bp
    from app.views.menu_routes import menu_bp
    from app.views.profile_routes import profile_bp
    from app.views.report_routes import report_bp
    from app.views.user_routes import user_bp

    app.register_blueprint(auth_bp, url_prefix="/api/auth")
    app.register_blueprint(user_bp, url_prefix="/api/users")
    app.register_blueprint(profile_bp, url_prefix="/api/profiles")
    app.register_blueprint(menu_bp, url_prefix="/api/menu-options")
    app.register_blueprint(alert_bp, url_prefix="/api/alerts")
    app.register_blueprint(assignment_bp, url_prefix="/api/assignments")
    app.register_blueprint(report_bp, url_prefix="/api/reports")
    app.register_blueprint(master_data_bp, url_prefix="/api/master-data")
