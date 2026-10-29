"""Reconciliación explícita de estados heredados de flota (HU-05).

Por defecto solo consulta. --apply conserva un respaldo de los estados previos
antes de actualizar; nunca borra registros ni modifica alertas o historial.
"""

import argparse
import json
import sys
from datetime import datetime, timezone
from pathlib import Path

from sqlalchemy import create_engine, or_, select, update
from sqlalchemy.exc import SQLAlchemyError

from app.config import database_url
from app.models.alert import TERMINAL_ALERT_STATES, Alert
from app.models.master_data import Client, EventType, GpsDevice, Vehicle
from app.models.state import State


def reconciliation_plan(connection, *, lock=False):
    clients, vehicles, devices, states = (
        Client.__table__,
        Vehicle.__table__,
        GpsDevice.__table__,
        State.__table__,
    )
    client_state, vehicle_state, gps_state = (
        states.alias("cs"),
        states.alias("vs"),
        states.alias("gs"),
    )
    inactive = connection.execute(
        select(states.c.id).where(states.c.name == "Inactivo", states.c.type == "user")
    ).scalar_one()
    vehicle_query = (
        select(vehicles.c.id, vehicles.c.state_id, vehicles.c.updated_at)
        .join(vehicle_state, vehicle_state.c.id == vehicles.c.state_id)
        .join(clients, clients.c.id == vehicles.c.client_id)
        .join(client_state, client_state.c.id == clients.c.state_id)
        .where(vehicle_state.c.name == "Activo", client_state.c.name == "Inactivo")
        .order_by(vehicles.c.id)
    )
    gps_query = (
        select(devices.c.id, devices.c.state_id, devices.c.updated_at)
        .join(gps_state, gps_state.c.id == devices.c.state_id)
        .join(vehicles, vehicles.c.id == devices.c.vehicle_id)
        .join(vehicle_state, vehicle_state.c.id == vehicles.c.state_id)
        .join(clients, clients.c.id == vehicles.c.client_id)
        .join(client_state, client_state.c.id == clients.c.state_id)
        .where(
            gps_state.c.name == "Activo",
            or_(vehicle_state.c.name == "Inactivo", client_state.c.name == "Inactivo"),
        )
        .order_by(devices.c.id)
    )
    if lock:
        vehicle_query = vehicle_query.with_for_update(of=(vehicles, clients))
        gps_query = gps_query.with_for_update(of=(devices, vehicles, clients))
    units = [dict(row) for row in connection.execute(vehicle_query).mappings()]
    equipment = [dict(row) for row in connection.execute(gps_query).mappings()]
    vehicle_ids = [row["id"] for row in units]
    alerts, events = Alert.__table__, EventType.__table__
    pending = (
        connection.execute(
            select(alerts.c.id)
            .join(states, states.c.id == alerts.c.state_id)
            .join(events, events.c.id == alerts.c.event_type_id)
            .where(
                alerts.c.vehicle_id.in_(vehicle_ids),
                events.c.code == "LOW_FUEL",
                states.c.name.not_in(TERMINAL_ALERT_STATES),
            )
        )
        .scalars()
        .all()
        if vehicle_ids
        else []
    )
    return {
        "inactive_state_id": inactive,
        "vehicles": units,
        "gps_devices": equipment,
        "blocked_alerts": list(pending),
    }


def apply_reconciliation(connection, plan):
    if plan["blocked_alerts"]:
        raise ValueError(
            "Existe combustible pendiente: completar o anular con motivo antes de desactivar vehículos"
        )
    now = datetime.now(timezone.utc).replace(tzinfo=None)
    for model, key in ((Vehicle, "vehicles"), (GpsDevice, "gps_devices")):
        ids = [row["id"] for row in plan[key]]
        if ids:
            connection.execute(
                update(model.__table__)
                .where(model.id.in_(ids))
                .values(state_id=plan["inactive_state_id"], updated_at=now)
            )


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--apply", action="store_true", help="Aplicar con respaldo previo de estados"
    )
    args = parser.parse_args()
    engine = None
    try:
        engine = create_engine(database_url(), connect_args={"connect_timeout": 5})
        with engine.begin() as connection:
            if not args.apply and connection.dialect.name == "postgresql":
                connection.exec_driver_sql("SET TRANSACTION READ ONLY")
            plan = reconciliation_plan(connection, lock=args.apply)
            print(
                f"Vehículos por desactivar: {len(plan['vehicles'])}; GPS por desactivar: {len(plan['gps_devices'])}"
            )
            if plan["blocked_alerts"]:
                print("Operación bloqueada por combustible pendiente. No se modificaron datos.")
                return 1
            if args.apply and (plan["vehicles"] or plan["gps_devices"]):
                backup_dir = Path(__file__).resolve().parent / "backups"
                backup_dir.mkdir(exist_ok=True)
                backup = backup_dir / (
                    "fleet-states-"
                    + datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S%fZ")
                    + ".json"
                )
                with backup.open("x", encoding="utf-8") as output:
                    json.dump(
                        {"purpose": "HU-05: estados previos a reconciliación", **plan},
                        output,
                        ensure_ascii=False,
                        indent=2,
                        default=str,
                    )
                apply_reconciliation(connection, plan)
                print("Respaldo de estados previos: " + str(backup))
        print(
            "Reconciliación completada."
            if args.apply
            else "Solo consulta. Usa --apply para aplicar el plan con respaldo."
        )
        return 0
    except (SQLAlchemyError, RuntimeError, ValueError, OSError):
        print(
            "No se aplicó la reconciliación. Revisa conexión, permisos, estados y respaldo; la transacción se revierte.",
            file=sys.stderr,
        )
        return 1
    finally:
        if engine is not None:
            engine.dispose()


if __name__ == "__main__":
    raise SystemExit(main())
