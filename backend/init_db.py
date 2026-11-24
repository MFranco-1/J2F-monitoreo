"""Aplica SQL versionado. Es instalador, no contiene consultas de negocio."""
import argparse
from pathlib import Path
import psycopg2
from app.config import database_url

if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--existing", action="store_true", help="Actualizar una BD existente sin recrear tablas")
    args = parser.parse_args()
    directory = Path(__file__).resolve().parents[1] / "database"
    scripts = (["01_esquema.sql"] if not args.existing else []) + ["02_catalogos.sql", "03_funciones.sql", "04_facturacion.sql", "05_servicios.sql", "06_venta_placas.sql", "07_planes_vendidos.sql"]
    with psycopg2.connect(database_url().set(drivername="postgresql").render_as_string(hide_password=False)) as conn:
        for name in scripts:
            with conn.cursor() as cursor:
                cursor.execute((directory / name).read_text(encoding="utf-8"))
            print("Aplicado:", name)
