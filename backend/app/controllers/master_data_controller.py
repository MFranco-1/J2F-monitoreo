"""CRUD validado de los cuatro datos maestros del monitoreo."""
from flask import jsonify
from werkzeug.exceptions import BadRequest
from sqlalchemy import func
from app import db
from app.models.state import State
from app.models.master_data import Client, Vehicle, GpsDevice, EventType
from app.validation import text_value, integer, user_state, priority_value, validate_email


MODELS = {"clients": Client, "vehicles": Vehicle, "gps-devices": GpsDevice,
          "event-types": EventType}


def _dict(kind, record):
    return record.to_dict(include_client=True) if kind == "vehicles" else (
        record.to_dict(include_vehicle=True) if kind == "gps-devices" else record.to_dict())


def _state(value):
    if value is None:
        state = State.query.filter_by(name="Activo", type="user").first()
        if not state:
            raise BadRequest("No está configurado el estado Activo")
        return state
    return user_state(value)


def list_records(kind, filters):
    model = MODELS[kind]
    query = model.query
    if filters.get("active") == "true":
        query = query.join(State).filter(State.name == "Activo")
    if kind == "vehicles" and filters.get("client_id"):
        query = query.filter(Vehicle.client_id == integer(filters["client_id"], "client_id"))
    if kind == "gps-devices" and filters.get("vehicle_id"):
        query = query.filter(GpsDevice.vehicle_id == integer(filters["vehicle_id"], "vehicle_id"))
    records = query.order_by(model.id).all()
    return jsonify({kind.replace("-", "_"): [_dict(kind, r) for r in records]}), 200


def get_record(kind, record_id):
    record = MODELS[kind].query.get_or_404(record_id, description="Registro no encontrado")
    return jsonify({kind.rstrip("s").replace("-", "_"): _dict(kind, record)}), 200


def _unique(model, field, value, record_id=None):
    if not value:
        return
    query = model.query.filter(func.lower(getattr(model, field)) == value.casefold())
    if record_id:
        query = query.filter(model.id != record_id)
    if query.first():
        raise BadRequest(f"{field} ya se encuentra registrado")


def _apply(kind, record, data, creating=False):
    if "state_id" in data or creating:
        record.state = _state(data.get("state_id"))
    if kind == "clients":
        fields = [("document_type", 20, True), ("document_number", 30, True),
                  ("business_name", 180, True), ("contact_name", 150, False),
                  ("phone", 30, False), ("email", 150, False), ("address", 255, False)]
        for field, limit, required in fields:
            if creating or field in data:
                value = text_value(data, field, required=required, limit=limit)
                if field == "email" and value:
                    value = validate_email(value)
                if field == "document_number":
                    _unique(Client, field, value, record.id)
                setattr(record, field, value)
    elif kind == "vehicles":
        if creating or "client_id" in data:
            client = db.session.get(Client, integer(data.get("client_id"), "client_id"))
            if not client:
                raise BadRequest("Cliente no encontrado")
            record.client = client
        for field, limit, required in [("plate", 20, True), ("brand", 100, False),
                                       ("model", 100, False), ("color", 50, False),
                                       ("vehicle_type", 80, False)]:
            if creating or field in data:
                value = text_value(data, field, required=required, limit=limit)
                if field == "plate":
                    value = value.upper()
                    _unique(Vehicle, field, value, record.id)
                setattr(record, field, value)
    elif kind == "gps-devices":
        if creating or "vehicle_id" in data:
            vehicle = db.session.get(Vehicle, integer(data.get("vehicle_id"), "vehicle_id"))
            if not vehicle:
                raise BadRequest("Vehículo no encontrado")
            record.vehicle = vehicle
        for field, limit, required in [("imei", 40, True), ("serial_number", 80, False),
                                       ("model", 100, False), ("provider", 100, False),
                                       ("sim_number", 30, False)]:
            if creating or field in data:
                value = text_value(data, field, required=required, limit=limit)
                if field in {"imei", "serial_number"}:
                    _unique(GpsDevice, field, value, record.id)
                setattr(record, field, value)
    else:
        for field, limit, required in [("code", 50, True), ("name", 150, True),
                                       ("description", None, False), ("expected_action", None, False)]:
            if creating or field in data:
                value = text_value(data, field, required=required, limit=limit)
                if field == "code":
                    value = value.upper()
                    _unique(EventType, field, value, record.id)
                setattr(record, field, value)
        if creating or "default_priority" in data:
            record.default_priority = priority_value(data.get("default_priority", "medium"))
        if creating or "generates_alert" in data:
            value = data.get("generates_alert", True)
            if not isinstance(value, bool):
                raise BadRequest("generates_alert debe ser true o false")
            record.generates_alert = value


def create_record(kind, data):
    record = MODELS[kind]()
    db.session.add(record)
    with db.session.no_autoflush:
        _apply(kind, record, data, True)
    db.session.commit()
    return jsonify({"message": "Registro creado", "record": _dict(kind, record)}), 201


def update_record(kind, record_id, data):
    record = MODELS[kind].query.get_or_404(record_id, description="Registro no encontrado")
    _apply(kind, record, data)
    db.session.commit()
    return jsonify({"message": "Registro actualizado", "record": _dict(kind, record)}), 200


def delete_record(kind, record_id):
    record = MODELS[kind].query.get_or_404(record_id, description="Registro no encontrado")
    related = ((kind == "clients" and record.vehicles.count())
               or (kind == "vehicles" and (record.gps_devices.count() or record.alerts.count()))
               or (kind == "gps-devices" and record.alerts.count())
               or (kind == "event-types" and record.alerts.count()))
    if related:
        return jsonify({"error": "El registro tiene información relacionada; cámbialo a Inactivo"}), 409
    db.session.delete(record)
    db.session.commit()
    return jsonify({"message": "Registro eliminado"}), 200
