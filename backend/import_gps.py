"""Importa un CSV con datos REALES usando el API almacenado y un administrador."""
import argparse
import csv
from getpass import getpass
from werkzeug.security import check_password_hash
from app import create_app
from app.database import invoke

if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("csv_file", help="CSV UTF-8: vehicle_id,imei,serial_number,model,provider,sim_number")
    args = parser.parse_args()
    with create_app().app_context():
        user = invoke("j2f_auth", "lookup", {"identifier": input("Correo/DNI del administrador: ").strip()})
        if not user or not check_password_hash(user["password_hash"], getpass("Contraseña: ")):
            raise SystemExit("Credenciales inválidas")
        status = invoke("j2f_auth", "status", {"user_id": user["id"]})
        profile = next((p for p in status["user"]["profiles"] if "admin" in p["permissions"]), None)
        if not profile:
            raise SystemExit("Se requiere permiso de administración")
        with open(args.csv_file, newline="", encoding="utf-8-sig") as stream:
            for row_number, data in enumerate(csv.DictReader(stream), start=2):
                if not data.get("imei") or not data.get("model") or not data.get("vehicle_id"):
                    raise SystemExit(f"Fila {row_number}: faltan IMEI, modelo o vehículo")
                result = invoke("j2f_api", "gps-devices", "create", None, data, {}, user["id"], profile["id"])
                print("Fila", row_number, "GPS registrado:", result["record"]["id"])
