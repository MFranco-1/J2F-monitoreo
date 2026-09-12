"""
app/__init__.py - Flask Application Factory para J2F Monitoreo
"""

from flask import Flask, jsonify, request
from flask_sqlalchemy import SQLAlchemy
from flask_jwt_extended import JWTManager
from flask_cors import CORS
from sqlalchemy.exc import IntegrityError, DataError, SQLAlchemyError
from werkzeug.exceptions import HTTPException, BadRequest

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

    # Registrar Blueprints (vistas/rutas)
    _register_blueprints(app)

    from app.controllers.auth_controller import is_token_revoked

    @jwt.token_in_blocklist_loader
    def token_is_revoked(_header, payload):
        return is_token_revoked(payload)

    @jwt.revoked_token_loader
    def revoked_token(_header, _payload):
        return jsonify({"error": "La sesión terminó o la cuenta cambió. Inicia sesión nuevamente."}), 401

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
        return jsonify({"error": "Datos duplicados, inválidos o relacionados con otros registros"}), 409

    @app.errorhandler(SQLAlchemyError)
    def database_error(error):
        db.session.rollback()
        app.logger.error("Error al acceder a PostgreSQL: %s", type(error).__name__)
        return jsonify({"error": "No se pudo acceder a los datos. Contacta al administrador del sistema."}), 503

    # Solo las pruebas crean tablas y datos en su base aislada.
    if app.config.get("TESTING"):
        with app.app_context():
            db.create_all()
            _seed_initial_data()

    return app


def _register_blueprints(app: Flask) -> None:
    """Registrar todos los blueprints de rutas."""
    from app.views.auth_routes import auth_bp
    from app.views.user_routes import user_bp
    from app.views.profile_routes import profile_bp
    from app.views.menu_routes import menu_bp
    from app.views.alert_routes import alert_bp
    from app.views.assignment_routes import assignment_bp
    from app.views.report_routes import report_bp
    from app.views.master_data_routes import master_data_bp

    app.register_blueprint(auth_bp, url_prefix="/api/auth")
    app.register_blueprint(user_bp, url_prefix="/api/users")
    app.register_blueprint(profile_bp, url_prefix="/api/profiles")
    app.register_blueprint(menu_bp, url_prefix="/api/menu-options")
    app.register_blueprint(alert_bp, url_prefix="/api/alerts")
    app.register_blueprint(assignment_bp, url_prefix="/api/assignments")
    app.register_blueprint(report_bp, url_prefix="/api/reports")
    app.register_blueprint(master_data_bp, url_prefix="/api/master-data")


def _seed_initial_data() -> None:
    """Datos de demostración exclusivos del entorno aislado de pruebas."""
    from app.models.state import State
    from app.models.profile import Profile
    from app.models.user import User
    from app.models.menu_option import MenuOption
    from app.models.master_data import EventType

    # Solo insertar si no existen datos
    if State.query.first():
        return

    # Estados base
    states = [
        State(name="Activo", type="user", description="Usuario activo en el sistema"),
        State(name="Inactivo", type="user", description="Usuario inactivo en el sistema"),
        State(name="Abierto", type="alert", description="Alerta nueva sin atender"),
        State(name="En Progreso", type="alert", description="Alerta siendo atendida"),
        State(name="Cerrado", type="alert", description="Alerta resuelta y cerrada"),
        State(name="Escalado", type="alert", description="Alerta escalada a nivel superior"),
    ]
    db.session.add_all(states)
    db.session.flush()

    # Perfil administrador
    admin_profile = Profile(
        name="Administrador",
        description="Acceso completo al sistema",
        state_id=states[0].id,
    )
    db.session.add(admin_profile)
    db.session.flush()

    technician_profile = Profile(
        name="Técnico", description="Atención operativa de alertas", state_id=states[0].id
    )
    db.session.add(technician_profile)
    db.session.flush()

    operator_profile = Profile(
        name="Operador", description="Revisión y asignación de alertas", state_id=states[0].id
    )
    db.session.add(operator_profile)
    db.session.flush()

    supervisor_profile = Profile(
        name="Supervisor", description="Supervisión y asignación de alertas", state_id=states[0].id
    )
    db.session.add(supervisor_profile)
    db.session.flush()

    # Usuario administrador por defecto
    admin_user = User(
        dni="00000000",
        full_name="Administrador J2F",
        email="admin@j2f.com",
        profile_id=admin_profile.id,
        state_id=states[0].id,
    )
    admin_user.set_password("Admin@J2F2024")
    admin_user.profiles = [admin_profile]
    db.session.add(admin_user)

    # El entorno de pruebas refleja las secciones y opciones registradas en Neon
    # mediante j2f_modulo_usuarios.sql.
    sections = {
        "MONITOREO": MenuOption(name="MONITOREO", icon="folder", order=0, state_id=states[0].id),
        "SEGUIMIENTO": MenuOption(name="SEGUIMIENTO", icon="folder", order=40, state_id=states[0].id),
        "ADMINISTRACIÓN": MenuOption(name="ADMINISTRACIÓN", icon="folder", order=60, state_id=states[0].id),
    }
    menu_options = [
        MenuOption(name="Panel de control", url="/dashboard", icon="dashboard", order=10,
                   state_id=states[0].id, parent=sections["MONITOREO"]),
        MenuOption(name="Alertas", url="/alerts", icon="alerts", order=20,
                   state_id=states[0].id, parent=sections["MONITOREO"]),
        MenuOption(name="Asignaciones", url="/assignments", icon="assignments", order=30,
                   state_id=states[0].id, parent=sections["MONITOREO"]),
        MenuOption(name="Historial", url="/history", icon="history", order=40,
                   state_id=states[0].id, parent=sections["SEGUIMIENTO"]),
        MenuOption(name="Reportes", url="/reports", icon="reports", order=50,
                   state_id=states[0].id, parent=sections["SEGUIMIENTO"]),
        MenuOption(name="Usuarios", url="/admin/users", icon="users", order=60,
                   state_id=states[0].id, parent=sections["ADMINISTRACIÓN"]),
        MenuOption(name="Perfiles", url="/admin/profiles", icon="profiles", order=70,
                   state_id=states[0].id, parent=sections["ADMINISTRACIÓN"]),
        MenuOption(name="Opciones de menú", url="/admin/menu-options", icon="menu", order=80,
                   state_id=states[0].id, parent=sections["ADMINISTRACIÓN"]),
        MenuOption(name="Datos maestros", url="/master-data", icon="database", order=90,
                   state_id=states[0].id, parent=sections["ADMINISTRACIÓN"]),
    ]
    for option in [*sections.values(), *menu_options]:
        option.profiles = [admin_profile]
    db.session.add_all([*sections.values(), *menu_options])
    for option in menu_options:
        if option.url in {"/dashboard", "/alerts", "/assignments", "/history"}:
            option.profiles.append(technician_profile)
            option.parent.profiles.append(technician_profile) if technician_profile not in option.parent.profiles else None
            option.profiles.append(operator_profile)
            option.parent.profiles.append(operator_profile) if operator_profile not in option.parent.profiles else None
        if option.url in {"/dashboard", "/alerts", "/assignments", "/history", "/reports", "/master-data"}:
            option.profiles.append(supervisor_profile)
            option.parent.profiles.append(supervisor_profile) if supervisor_profile not in option.parent.profiles else None
    event_seed = [
        ("SOS", "Botón de pánico o SOS", "critical", True),
        ("SPEEDING", "Exceso de velocidad", "high", True),
        ("GEOFENCE_EXIT", "Salida de geocerca", "high", True),
        ("GEOFENCE_ENTRY", "Ingreso a geocerca", "low", False),
        ("GPS_SIGNAL_LOSS", "Pérdida de señal GPS", "high", True),
        ("POWER_CUT", "Corte de alimentación del dispositivo", "critical", True),
        ("LOW_BATTERY", "Batería baja", "medium", True),
        ("DEVICE_TAMPER", "Manipulación o desconexión del dispositivo", "critical", True),
        ("UNAUTHORIZED_MOVEMENT", "Movimiento no autorizado", "critical", True),
        ("OUT_OF_HOURS_IGNITION", "Encendido fuera del horario permitido", "high", True),
        ("PROLONGED_STOP", "Parada o inactividad prolongada", "medium", False),
        ("COMMUNICATION_FAILURE", "Falla de comunicación del dispositivo", "high", True),
    ]
    db.session.add_all([EventType(code=code, name=name, description=name,
                    default_priority=priority, generates_alert=generates,
                    expected_action="Aplicar el protocolo operativo vigente", state_id=states[0].id)
                    for code, name, priority, generates in event_seed])
    db.session.commit()
