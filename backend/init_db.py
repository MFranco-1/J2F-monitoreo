"""Comprueba la base actual. No crea ni modifica bases, tablas o registros."""
import sys
from sqlalchemy import create_engine, inspect, text
from sqlalchemy.exc import SQLAlchemyError
from app import db
from app import models
from app.config import database_url


def main():
    engine = None
    try:
        engine = create_engine(database_url(), connect_args={"connect_timeout": 5})
        with engine.connect() as connection:
            connection.execute(text("SET TRANSACTION READ ONLY"))
            name = connection.scalar(text("SELECT current_database()"))
            print(f"Base conectada: {name}")
            inspector = inspect(connection)
            existing = set(inspector.get_table_names())
            missing = []
            for table in db.metadata.sorted_tables:
                if table.name not in existing:
                    missing.append(f"Tabla faltante: {table.name}")
                    continue
                columns = {c["name"] for c in inspector.get_columns(table.name)}
                for column in table.columns:
                    if column.name not in columns:
                        missing.append(f"Columna faltante: {table.name}.{column.name}")
            if missing:
                print("La estructura actual no coincide con los modelos:", file=sys.stderr)
                for item in missing:
                    print(item, file=sys.stderr)
                print("No se ha modificado la base de datos.", file=sys.stderr)
                return 1
        print("Conexión correcta. Las 9 tablas y sus columnas requeridas existen. No se modificaron datos.")
        return 0
    except (SQLAlchemyError, RuntimeError, ValueError):
        print("No se pudo verificar PostgreSQL. Revisa el servicio, la base y las variables de conexión.", file=sys.stderr)
        return 1
    finally:
        if engine is not None:
            engine.dispose()


if __name__ == "__main__":
    raise SystemExit(main())
