"""Una sola configuración PostgreSQL para Flask e init_db.py."""
import os
from datetime import timedelta
from sqlalchemy.engine import URL, make_url
from sqlalchemy.exc import ArgumentError


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
        except ArgumentError:
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
                         port=int(os.environ.get("PGPORT", "5432")),
                         database=os.environ.get("PGDATABASE", "j2f_monitoreo"))
    if url.get_backend_name() != "postgresql" or not url.database:
        raise RuntimeError("DATABASE_URL debe indicar una base de datos PostgreSQL")
    return url


class BaseConfig:
    SQLALCHEMY_TRACK_MODIFICATIONS = False
    JSON_SORT_KEYS = False
    JWT_ACCESS_TOKEN_EXPIRES = timedelta(hours=8)
    JWT_REFRESH_TOKEN_EXPIRES = timedelta(days=30)


class DevelopmentConfig(BaseConfig):
    DEBUG = True
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
    cfg.SECRET_KEY = os.environ.get("SECRET_KEY", "j2f-dev-secret-key-cambiar-en-produccion")
    cfg.JWT_SECRET_KEY = os.environ.get("JWT_SECRET_KEY", "j2f-jwt-secret-cambiar-en-produccion")
    cfg.CORS_ORIGINS = [origin.strip() for origin in os.environ.get(
        "CORS_ORIGINS", "http://localhost:4200").split(",") if origin.strip()]
    if cfg.ENV != "testing":
        cfg.SQLALCHEMY_DATABASE_URI = database_url()
    if cfg.ENV == "production" and any(not os.environ.get(key) for key in
                                      ("SECRET_KEY", "JWT_SECRET_KEY", "DATABASE_URL")):
        raise RuntimeError("Producción requiere SECRET_KEY, JWT_SECRET_KEY y DATABASE_URL")
    return cfg
