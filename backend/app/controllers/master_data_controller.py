"""CRUD validado de los cuatro datos maestros del monitoreo."""
import json
from flask import jsonify
from werkzeug.exceptions import BadRequest
from sqlalchemy import func
from app import db
from app.models.state import State
from app.models.master_data import Client, Vehicle, GpsDevice, EventType
from app.models.alert import Alert, TERMINAL_ALERT_STATES
from app.models.assignment import Assignment
from app.security import current_user, can_view_all_operations, is_technician
from app.datetime_utils import utcnow, iso_utc
from app.validation import (
    record_text as text_value, integer, user_state, priority_value, validate_email,
    validate_document, validate_phone, validate_plate, validate_imei, validate_code, validate_ruc,
    normalize_client_name, validate_client_phone,
)


MODELS = {"clients": Client, "vehicles": Vehicle, "gps-devices": GpsDevice,
          "event-types": EventType}
PROTECTED_EVENT_CODES = {"LOW_FUEL", "SOS", "SPEEDING", "GPS_SIGNAL_LOSS"}


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
    query, error = _scoped_query(kind, query)
    if error:
        return error
    if filters.get("active") == "true":
        query = query.join(State).filter(State.name == "Activo")
        if kind == "vehicles":
            query = query.filter(Vehicle.client.has(Client.state.has(name="Activo")))
        elif kind == "gps-devices":
            query = query.filter(GpsDevice.vehicle.has(
                Vehicle.state.has(name="Activo") & Vehicle.client.has(Client.state.has(name="Activo"))
            ))
    if kind == "vehicles" and filters.get("client_id"):
        query = query.filter(Vehicle.client_id == integer(filters["client_id"], "client_id"))
    if kind == "gps-devices" and filters.get("vehicle_id"):
        query = query.filter(GpsDevice.vehicle_id == integer(filters["vehicle_id"], "vehicle_id"))
    records = query.order_by(model.id).all()
    return jsonify({kind.replace("-", "_"): [_dict(kind, r) for r in records]}), 200


def get_record(kind, record_id):
    query, error = _scoped_query(kind, MODELS[kind].query)
    if error:
        return error
    record = query.filter_by(id=record_id).first_or_404(description="Registro no encontrado")
    return jsonify({kind.rstrip("s").replace("-", "_"): _dict(kind, record)}), 200


def _scoped_query(kind, query):
    actor = current_user()
    if can_view_all_operations(actor):
        return query, None
    if not is_technician(actor):
        return query, (jsonify({"error": "El perfil activo no puede consultar datos maestros"}), 403)
    assigned = Alert.assignments.any(Assignment.user_id == actor.id)
    if kind == "clients":
        query = query.filter(Client.vehicles.any(Vehicle.alerts.any(assigned)))
    elif kind == "vehicles":
        query = query.filter(Vehicle.alerts.any(assigned))
    elif kind == "gps-devices":
        query = query.filter(GpsDevice.vehicle.has(Vehicle.alerts.any(assigned)))
    # Los tipos de evento son un catálogo necesario para interpretar sus alertas.
    return query, None


def _unique(model, field, value, record_id=None):
    if not value:
        return
    query = model.query.filter(func.lower(getattr(model, field)) == value.casefold())
    if record_id:
        query = query.filter(model.id != record_id)
    if query.first():
        raise BadRequest(f"{field} ya se encuentra registrado")


def _apply(kind, record, data, creating=False):
    previous_identity = (record.document_type, record.document_number, record.business_name) if kind == "clients" else None
    if "state_id" in data or creating:
        record.state = _state(data.get("state_id"))
    if kind == "clients":
        # Validar el par completo cuando cambia cualquiera de sus partes. No
        # reinterpretar documentos heredados en actualizaciones solo de estado.
        if creating or "document_type" in data or "document_number" in data:
            document_type = (text_value(data, "document_type", required=True, limit=20)
                             if creating or "document_type" in data else record.document_type)
            number = (text_value(data, "document_number", required=True, limit=30)
                      if creating or "document_number" in data else record.document_number)
            document_type, number = validate_document(document_type, number)
            _unique(Client, "document_number", number, record.id)
            record.document_type, record.document_number = document_type, number
        fields = [("business_name", 180, True), ("contact_name", 150, False),
                  ("phone", 30, False), ("email", 150, False), ("address", 255, False)]
        for field, limit, required in fields:
            if creating or field in data:
                value = text_value(data, field, required=required, limit=limit)
                if field == "email" and value:
                    value = validate_email(value)
                if field == "phone":
                    value = validate_client_phone(value, data.get("phone_country"))
                if field in {"business_name", "contact_name"}:
                    value = normalize_client_name(value)
                setattr(record, field, value)
        if "phone_country" in data and "phone" not in data and not creating:
            raise BadRequest("Teléfono: envía también el número cuando cambies el país")
        _preserve_client_verification(record, data, previous_identity, creating)
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
                    value = validate_plate(value)
                    _unique(Vehicle, field, value, record.id)
                setattr(record, field, value)
        if record.is_active and not record.client.is_active:
            raise BadRequest("No se puede activar un vehículo de un cliente inactivo; activa primero al cliente")
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
                if field == "serial_number":
                    value = validate_code(value, serial=True) or None
                if field == "imei":
                    value = validate_imei(value)
                if field == "sim_number":
                    value = validate_phone(value, sim=True)
                if field in {"imei", "serial_number"}:
                    _unique(GpsDevice, field, value, record.id)
                setattr(record, field, value)
        if record.is_active and (not record.vehicle.is_active or not record.vehicle.client.is_active):
            raise BadRequest("No se puede activar un GPS de un vehículo o cliente inactivo; activa primero al cliente y al vehículo")
    else:
        for field, limit, required in [("code", 50, True), ("name", 150, True),
                                       ("description", None, False), ("expected_action", None, False)]:
            if creating or field in data:
                value = text_value(data, field, required=required, limit=limit)
                if field == "code":
                    value = validate_code(value)
                    _unique(EventType, field, value, record.id)
                setattr(record, field, value)
        if creating or "default_priority" in data:
            record.default_priority = priority_value(data.get("default_priority", "medium"))
        if creating or "generates_alert" in data:
            value = data.get("generates_alert", True)
            if not isinstance(value, bool):
                raise BadRequest("generates_alert debe ser true o false")
            record.generates_alert = value


def _preserve_client_verification(record, data, previous_identity, creating):
    """Conserva el historial anterior sin exigir ni permitir consultas externas."""
    identity = (record.document_type, record.document_number, record.business_name)
    changed = creating or identity != previous_identity
    if any(key in data for key in ("verification_json", "verification_status")):
        raise BadRequest("La verificación se registra desde el servidor, no desde campos editables")
    if record.document_type == "RUC" and changed:
        validate_ruc(record.document_number)
    if not changed or not record.verification_json:
        return  # Sin reescribir registros ni historial por editar teléfono/estado.
    actor = current_user()
    entry = {"status": "pending" if record.document_type == "RUC" else "not_applicable",
             "source": "manual", "observation": "Datos modificados manualmente, sin consulta externa",
             "actor": {"id": actor.id, "name": actor.full_name}, "timestamp": iso_utc(utcnow()),
             "document_number": record.document_number, "business_name": record.business_name}
    record.verification_json = json.dumps({**entry, "audit": [*record.verification.get("audit", []), entry]}, ensure_ascii=False)


def create_record(kind, data):
    record = MODELS[kind]()
    db.session.add(record)
    with db.session.no_autoflush:
        _apply(kind, record, data, True)
    db.session.commit()
    return jsonify({"message": "Registro creado", "record": _dict(kind, record)}), 201


def update_record(kind, record_id, data):
    message = "Registro actualizado"
    record = MODELS[kind].query.filter_by(id=record_id).with_for_update().first_or_404(description="Registro no encontrado")
    if kind == "vehicles" and "state_id" in data:
        requested_state = _state(data["state_id"])
        if requested_state.name == "Inactivo" and record.state.name != "Inactivo":
            pending_fuel = (
                record.alerts.join(State, Alert.state_id == State.id)
                .join(EventType, Alert.event_type_id == EventType.id)
                .filter(State.name.notin_(TERMINAL_ALERT_STATES), EventType.code == "LOW_FUEL")
                .first()
            )
            if pending_fuel:
                return jsonify({
                    "error": ("Completa primero el abastecimiento de la alerta "
                              f"#{pending_fuel.id} antes de desactivar el vehículo")
                }), 409
    if (kind == "vehicles" and "client_id" in data
            and integer(data.get("client_id"), "client_id") != record.client_id
            and record.alerts.count()):
        return jsonify({"error": "No se puede cambiar el cliente: el vehículo tiene alertas históricas"}), 409
    if (kind == "gps-devices" and "vehicle_id" in data
            and integer(data.get("vehicle_id"), "vehicle_id") != record.vehicle_id
            and record.alerts.count()):
        return jsonify({"error": "No se puede cambiar el vehículo: el GPS tiene alertas históricas"}), 409
    if kind == "event-types" and record.code in PROTECTED_EVENT_CODES:
        requested_code = str(data.get("code", record.code)).strip().upper()
        requested_state = _state(data["state_id"]) if "state_id" in data else record.state
        requested_generates = data.get("generates_alert", record.generates_alert)
        if (requested_code != record.code or requested_state.name != "Activo"
                or requested_generates is not True):
            return jsonify({"error": "El código interno, estado activo y generación de alerta de este evento están protegidos"}), 409
    with db.session.no_autoflush:
        _apply(kind, record, data)
        if kind in {"clients", "vehicles"} and "state_id" in data and record.state.name == "Inactivo":
            if kind == "clients":
                vehicles = record.vehicles.order_by(Vehicle.id).with_for_update().all()
                vehicle_ids = [vehicle.id for vehicle in vehicles]
                pending_fuel = (Alert.query.join(State, Alert.state_id == State.id)
                    .join(EventType, Alert.event_type_id == EventType.id)
                    .filter(Alert.vehicle_id.in_(vehicle_ids), State.name.notin_(TERMINAL_ALERT_STATES),
                            EventType.code == "LOW_FUEL").first())
                if pending_fuel:
                    db.session.rollback()
                    return jsonify({"error": ("Completa primero el abastecimiento o anula con motivo la alerta "
                        f"#{pending_fuel.id} antes de desactivar el cliente y sus vehículos")}), 409
                for vehicle in vehicles:
                    vehicle.state = record.state
            else:
                vehicle_ids = [record.id]
            devices = GpsDevice.query.filter(GpsDevice.vehicle_id.in_(vehicle_ids)).order_by(GpsDevice.id).with_for_update().all()
            for device in devices:
                device.state = record.state
            message = ("Cliente actualizado; sus vehículos y GPS quedan inactivos" if kind == "clients" else
                       "Vehículo actualizado; sus GPS quedan inactivos")
    db.session.commit()
    return jsonify({"message": message, "record": _dict(kind, record)}), 200


def delete_record(kind, record_id):
    record = MODELS[kind].query.get_or_404(record_id, description="Registro no encontrado")
    if kind == "event-types" and record.code in PROTECTED_EVENT_CODES:
        return jsonify({"error": "Este tipo de evento interno no puede eliminarse"}), 409
    related = ((kind == "clients" and record.vehicles.count())
               or (kind == "vehicles" and (record.gps_devices.count() or record.alerts.count()))
               or (kind == "gps-devices" and record.alerts.count())
               or (kind == "event-types" and record.alerts.count()))
    if related:
        return jsonify({"error": "El registro tiene información relacionada; cámbialo a Inactivo"}), 409
    db.session.delete(record)
    db.session.commit()
    return jsonify({"message": "Registro eliminado"}), 200
