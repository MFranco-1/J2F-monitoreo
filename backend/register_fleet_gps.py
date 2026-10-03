"""Registros GPS solicitados para la flota; no configura equipos físicos.

Identificadores sintéticos, con prefijo 00 (sin TAC de fabricante).
Por defecto solo muestra el plan; --apply inserta dentro de una transacción.
No ejecuta migraciones ni modifica vehículos, alertas o GPS anteriores.
"""
import argparse
import sys
from sqlalchemy import create_engine, select
from sqlalchemy.exc import SQLAlchemyError
from app.config import database_url
from app.models.master_data import Vehicle, GpsDevice
from app.models.state import State


def generated_imei(vehicle_id):
    """15 dígitos con control Luhn; no es el IMEI de un dispositivo real."""
    if isinstance(vehicle_id, bool) or not isinstance(vehicle_id, int) or not 0 < vehicle_id < 10**12:
        raise ValueError("Identificador de vehículo fuera de rango")
    base = "00" + str(vehicle_id).zfill(12)
    total = 0
    for index, digit in enumerate(reversed(base)):
        value = int(digit) * (2 if index % 2 == 0 else 1)
        total += value // 10 + value % 10
    return base + str((-total) % 10)


def register_missing_gps(connection, *, apply=False):
    vehicles, devices, states = Vehicle.__table__, GpsDevice.__table__, State.__table__
    query = (select(vehicles.c.id, vehicles.c.plate, vehicles.c.state_id)
             .join(states, vehicles.c.state_id == states.c.id)
             .where(states.c.name == "Activo", states.c.type == "user")
             .order_by(vehicles.c.id))
    if apply:
        query = query.with_for_update(of=vehicles)
    units = connection.execute(query).mappings().all()
    existing = connection.execute(select(devices.c.vehicle_id, devices.c.imei, devices.c.serial_number)).all()
    linked = {item.vehicle_id for item in existing}
    used_imeis = {item.imei for item in existing}
    used_serials = {item.serial_number for item in existing}
    plan = []
    for unit in units:
        if unit.id in linked:
            continue
        imei, serial = generated_imei(unit.id), "GPS-" + unit.plate
        if imei in used_imeis or serial in used_serials:
            raise ValueError("Hay un identificador GPS ocupado; no se modifica su vinculación")
        plan.append({"vehicle_id": unit.id, "plate": unit.plate, "imei": imei,
                     "serial_number": serial, "model": "GPS J2F", "state_id": unit.state_id})
    if apply:
        for item in plan:
            connection.execute(devices.insert().values(**{key:value for key,value in item.items() if key != "plate"}))
    return plan


def main():
    parser = argparse.ArgumentParser(description="Vincula registros GPS generados a vehículos activos sin equipo registrado")
    parser.add_argument("--apply", action="store_true", help="Aplicar el plan sin borrar ni sustituir registros")
    args = parser.parse_args()
    engine = None
    try:
        engine = create_engine(database_url(), connect_args={"connect_timeout":5})
        with engine.begin() as connection:
            plan = register_missing_gps(connection, apply=args.apply)
        print("Registros GPS con identificadores generados; no hay conexión con equipos físicos.")
        for item in plan:
            print(f"{item['plate']}: {item['serial_number']} / {item['imei']}")
        print(f"{'Creados' if args.apply else 'Pendientes de aplicar'}: {len(plan)}")
        return 0
    except (SQLAlchemyError, RuntimeError, ValueError):
        print("No se pudo completar el registro. Revisa conexión, esquema o identificadores duplicados; no se aplicaron cambios parciales.", file=sys.stderr)
        return 1
    finally:
        if engine is not None:
            engine.dispose()


if __name__ == "__main__":
    raise SystemExit(main())
