"""Una sola configuración PostgreSQL para Flask e init_db.py."""
import os
import secrets
from functools import lru_cache
from datetime import timedelta
from urllib.parse import urlsplit
from sqlalchemy.engine import URL, make_url
from sqlalchemy.exc import ArgumentError


def integer_setting(name, default, minimum, maximum):
    """Falla con un mensaje útil, sin revelar otros valores de configuración."""
    try:
        value = int(os.environ.get(name, str(default)))
    except (TypeError, ValueError):
        raise RuntimeError(f"{name} debe ser un número entero") from None
    if not minimum <= value <= maximum:
        raise RuntimeError(f"{name} debe estar entre {minimum} y {maximum}")
    return value


@lru_cache(maxsize=1)
def development_keys():
    # Nunca usar claves públicas conocidas. Son estables en este proceso;
    # configura las variables privadas para conservar sesiones entre reinicios.
    return secrets.token_urlsafe(48), secrets.token_urlsafe(48)


def secret_setting(name, fallback, production=False):
    value = os.environ.get(name, '').strip()
    if not value and not production:
        return fallback
    if (len(value) < 32 or value.startswith(('GENERAR_', 'CAMBIAR_', 'j2f-dev-', 'j2f-jwt-'))):
        raise RuntimeError(f"{name} debe ser una clave privada de al menos 32 caracteres, no una plantilla")
    return value


def database_url():
    value = os.environ.get("DATABASE_URL", "").strip()
    if value:
        # SQLAlchemy 2 no acepta el alias historico postgres://. Neon puede
        # entregarlo en algunas integraciones; solo se normaliza el esquema y
        # se conservan intactos el host, las credenciales y todos los parametros.
        if value.startswith("postgres://"):
            value = "postgresql://" + value[len("postgres://"):]
        try:
            url = make_url(value)
        except (ArgumentError, ValueError):
            # Se elimina el contexto de la excepcion para que un traceback no
            # pueda incluir accidentalmente el valor recibido.
            raise RuntimeError("DATABASE_URL no tiene un formato valido") from None
        if url.drivername == "postgresql":
            url = url.set(drivername="postgresql+psycopg2")
    else:
        password = os.environ.get("PGPASSWORD")
        if not password:
            raise RuntimeError("Configura PGPASSWORD o DATABASE_URL antes de iniciar PostgreSQL. Consulta README.md.")
        url = URL.create("postgresql+psycopg2", username=os.environ.get("PGUSER", "postgres"),
                         password=password, host=os.environ.get("PGHOST", "localhost"),
                         port=integer_setting("PGPORT", 5432, 1, 65535),
                         database=os.environ.get("PGDATABASE", "j2f_monitoreo"))
    if url.get_backend_name() != "postgresql" or not url.database:
        raise RuntimeError("DATABASE_URL debe indicar una base de datos PostgreSQL")
    return url


class BaseConfig:
    SQLALCHEMY_TRACK_MODIFICATIONS = False
    JSON_SORT_KEYS = False
    JWT_ACCESS_TOKEN_EXPIRES = timedelta(hours=8)
    JWT_REFRESH_TOKEN_EXPIRES = timedelta(days=30)
    MAX_CONTENT_LENGTH = 1024 * 1024


class DevelopmentConfig(BaseConfig):
    DEBUG = False
    ENV = "development"


class ProductionConfig(BaseConfig):
    DEBUG = False
    ENV = "production"
    JWT_ACCESS_TOKEN_EXPIRES = timedelta(hours=4)


class TestingConfig(BaseConfig):
    TESTING = True
    DEBUG = False
    ENV = "testing"
    SQLALCHEMY_DATABASE_URI = "sqlite:///:memory:"
    JWT_ACCESS_TOKEN_EXPIRES = timedelta(minutes=5)


config_map = {"development": DevelopmentConfig, "production": ProductionConfig,
              "testing": TestingConfig, "default": DevelopmentConfig}


def get_config(env=None):
    env = env or os.environ.get("FLASK_ENV", "development")
    if env not in config_map:
        raise RuntimeError("FLASK_ENV inválido: usa development, testing o production")
    cfg = config_map[env]()
    production = cfg.ENV == 'production'
    fallback_secret, fallback_jwt = development_keys()
    cfg.SECRET_KEY = secret_setting('SECRET_KEY', fallback_secret, production)
    cfg.JWT_SECRET_KEY = secret_setting('JWT_SECRET_KEY', fallback_jwt, production)
    if production and cfg.SECRET_KEY == cfg.JWT_SECRET_KEY:
        raise RuntimeError('SECRET_KEY y JWT_SECRET_KEY deben ser diferentes')
    cfg.HOST = os.environ.get('HOST', '127.0.0.1').strip()
    cfg.PORT = integer_setting('PORT', 5000, 1, 65535)
    cfg.MAP_SERVICE_TIMEOUT = integer_setting('MAP_SERVICE_TIMEOUT', 12, 1, 60)
    cfg.OVERPASS_API_URL = os.environ.get('OVERPASS_API_URL', 'https://overpass-api.de/api/interpreter')
    cfg.ROUTING_API_URL = os.environ.get('ROUTING_API_URL', 'https://router.project-osrm.org')
    cfg.CORS_ORIGINS = [origin.strip() for origin in os.environ.get(
        "CORS_ORIGINS", "http://localhost:4200").split(",") if origin.strip()]
    for origin in cfg.CORS_ORIGINS:
        try:
            parsed = urlsplit(origin)
            parsed.port  # Valida también un puerto mal formado sin imprimir el origen.
        except ValueError:
            raise RuntimeError('CORS_ORIGINS contiene un origen inválido') from None
        if (parsed.scheme not in {'http', 'https'} or not parsed.netloc or '*' in parsed.netloc
                or parsed.username or parsed.password or parsed.path or parsed.query or parsed.fragment):
            raise RuntimeError('CORS_ORIGINS requiere orígenes explícitos, sin comodines ni rutas')
    if cfg.ENV != "testing":
        cfg.SQLALCHEMY_DATABASE_URI = database_url()
    if production and not os.environ.get('DATABASE_URL'):
        raise RuntimeError('Producción requiere DATABASE_URL')
    return cfg
