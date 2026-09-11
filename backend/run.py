"""
run.py - Punto de entrada para ejecutar el servidor Flask de J2F Monitoreo
"""

from app import create_app

app = create_app()

if __name__ == "__main__":
    from init_db import main as verify_database
    if verify_database() != 0:
        raise SystemExit(1)
    app.run(
        host="0.0.0.0",
        port=5000,
        debug=app.config["DEBUG"],
    )
