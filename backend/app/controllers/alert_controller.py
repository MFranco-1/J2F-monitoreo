"""
controllers/alert_controller.py - Lógica de negocio para Alertas
Gestiona el flujo automático de alertas, cambio de estados y trazabilidad.
"""

from app.datetime_utils import utcnow
from flask import jsonify
from app import db
from app.models.alert import Alert
from app.models.state import State
from app.models.history import History
from app.models.master_data import Client, Vehicle, GpsDevice, EventType
from app.validation import text_value, priority_value, integer, date_value, date_range
from app.security import current_user, may_attend, active_profile_id


# Orden válido de transiciones de estado de alerta
VALID_TRANSITIONS = {
    "Abierto": ["En Progreso", "Escalado", "Cerrado"],
    "En Progreso": ["Cerrado", "Escalado", "Abierto"],
    "Escalado": ["En Progreso", "Cerrado"],
    "Cerrado": [],  # Terminal
}


def get_all_alerts(filters: dict) -> tuple:
    """
    Lista todas las alertas con filtros opcionales.
    Filtros: state_name, priority, assigned_user_id, date_from, date_to
    """
    query = Alert.query.join(State, Alert.state_id == State.id)

    if filters.get("state"):
        query = query.filter(State.name == filters["state"])
    if filters.get("priority"):
        query = query.filter(Alert.priority == filters["priority"])
    start = date_value(filters.get("date_from"), "date_from")
    end = date_value(filters.get("date_to"), "date_to", end_of_day=True)
    date_range(start, end)
    if start is not None:
        query = query.filter(Alert.created_at >= start)
    if end is not None:
        query = query.filter(Alert.created_at <= end)

    page = integer(filters.get("page", 1), "page")
    per_page = integer(filters.get("per_page", 20), "per_page", maximum=200)
    pagination = query.order_by(Alert.opened_at.desc()).paginate(
        page=page, per_page=per_page, error_out=False
    )

    return jsonify({
        "alerts": [a.to_dict() for a in pagination.items],
        "total": pagination.total,
        "pages": pagination.pages,
        "current_page": page,
    }), 200


def get_alert_by_id(alert_id: int) -> tuple:
    """Retorna una alerta específica con su historial completo."""
    alert = Alert.query.get_or_404(alert_id, description="Alerta no encontrada")
    return jsonify({"alert": alert.to_dict(include_history=True)}), 200


def create_alert(data: dict, current_user_id: int) -> tuple:
    """Crea una nueva alerta y registra el evento en el historial."""
    if not data.get("title"):
        return jsonify({"error": "El título de la alerta es requerido"}), 400

    # Buscar estado "Abierto" por defecto
    open_state = State.query.filter_by(name="Abierto", type="alert").first()
    if not open_state:
        return jsonify({"error": "Estado 'Abierto' no configurado en el sistema"}), 500

    vehicle, device, event_type = _validated_relations(data)
    alert = Alert(
        title=text_value(data, "title", required=True, limit=200),
        description=text_value(data, "description"),
        priority=priority_value(data.get("priority", event_type.default_priority if event_type else "medium")),
        service_type=text_value(data, "service_type", limit=100),
        location=text_value(data, "location", limit=200),
        source=text_value(data, "source", limit=100) or "Manual",
        state_id=open_state.id,
        created_by=current_user_id,
        vehicle=vehicle,
        gps_device=device,
        event_type=event_type,
    )
    db.session.add(alert)
    db.session.flush()  # Para obtener el ID

    # Registrar en historial
    _log_history(
        alert_id=alert.id,
        user_id=current_user_id,
        action="created",
        new_state="Abierto",
        detail=f"Alerta creada con prioridad {alert.priority}",
    )

    db.session.commit()
    return jsonify({"message": "Alerta creada exitosamente", "alert": alert.to_dict()}), 201


def update_alert(alert_id: int, data: dict, current_user_id: int) -> tuple:
    """Actualiza los datos de una alerta. Si cambia el estado, valida la transición."""
    from app.controllers.assignment_controller import locked_alert
    alert = locked_alert(alert_id)
    if not may_attend(alert, current_user()):
        return jsonify({"error": "Solo el operador asignado o un administrador puede modificar la alerta"}), 403
    changes = {}
    for field, limit in [("title", 200), ("description", None), ("service_type", 100), ("location", 200)]:
        if field in data:
            changes[field] = text_value(data, field, required=(field == "title"), limit=limit)
    if "priority" in data:
        changes["priority"] = priority_value(data["priority"])
    notes = text_value(data, "notes")
    if "state_name" in data:
        new_state = text_value(data, "state_name", required=True, limit=50)
        result = _change_state(alert, current_user_id, new_state, notes)
        if result is not None:
            db.session.rollback()
            return result
    changed = [field for field, value in changes.items() if getattr(alert, field) != value]
    if changed:
        detail = "; ".join(f"{field}: {getattr(alert, field)} → {changes[field]}" for field in changed)
        for field in changed:
            setattr(alert, field, changes[field])
        _log_history(alert.id, current_user_id, "updated", detail=detail)

    db.session.commit()
    return jsonify({"message": "Alerta actualizada", "alert": alert.to_dict()}), 200


def delete_alert(alert_id: int, current_user_id: int) -> tuple:
    """Elimina una alerta (solo si está cerrada)."""
    Alert.query.get_or_404(alert_id, description="Alerta no encontrada")
    return jsonify({"error": "Las alertas se conservan para mantener la trazabilidad; utiliza el estado Cerrado"}), 409


def get_dashboard_metrics() -> tuple:
    """
    Retorna métricas de dashboard para las tarjetas de resumen.
    Usado por el frontend para polling en tiempo real.
    """
    total = Alert.query.count()

    states = State.query.filter_by(type="alert").all()
    state_counts = {}
    for state in states:
        count = Alert.query.filter_by(state_id=state.id).count()
        state_counts[state.name] = count

    # Últimas 7 alertas críticas abiertas
    critical_open = (
        Alert.query.join(State)
        .filter(Alert.priority == "critical", State.name == "Abierto")
        .order_by(Alert.opened_at.desc())
        .limit(7)
        .all()
    )

    # Tiempo promedio de respuesta (alertas cerradas)
    closed_alerts = Alert.query.filter(Alert.resolved_at.isnot(None)).all()
    avg_response = 0.0
    if closed_alerts:
        times = [a.response_time_minutes for a in closed_alerts if a.response_time_minutes is not None]
        avg_response = round(sum(times) / len(times), 2) if times else 0.0

    return jsonify({
        "total_alerts": total,
        "by_state": state_counts,
        "critical_open": [a.to_dict() for a in critical_open],
        "avg_response_time_minutes": avg_response,
    }), 200


# --- Helpers internos ---

def _change_state(alert: Alert, user_id: int, new_state_name: str, notes: str = None):
    """
    Valida y ejecuta la transición de estado de una alerta.
    Retorna una tupla de error si la transición es inválida, None si es válida.
    """
    current_state_name = alert.state.name if alert.state else "Abierto"
    allowed = VALID_TRANSITIONS.get(current_state_name, [])

    if new_state_name not in allowed:
        return jsonify({
            "error": f"Transición inválida: '{current_state_name}' → '{new_state_name}'. "
                     f"Transiciones permitidas: {allowed}"
        }), 422

    new_state = State.query.filter_by(name=new_state_name, type="alert").first()
    if not new_state:
        return jsonify({"error": f"Estado '{new_state_name}' no encontrado"}), 404

    old_state_name = current_state_name
    alert.state = new_state
    alert.state_id = new_state.id

    # Registrar timestamps especiales
    now = utcnow()
    if new_state_name == "En Progreso" and not alert.acknowledged_at:
        alert.acknowledged_at = now
    if new_state_name == "Cerrado":
        alert.resolved_at = now
        # Completar asignaciones activas
        for assignment in alert.assignments.filter_by(completed_at=None):
            assignment.complete()

    _log_history(
        alert_id=alert.id,
        user_id=user_id,
        action="state_changed",
        previous_state=old_state_name,
        new_state=new_state_name,
        detail=notes or f"Estado cambiado de {old_state_name} a {new_state_name}",
    )
    return None  # Éxito


def _log_history(
    alert_id: int,
    user_id: int,
    action: str,
    previous_state: str = None,
    new_state: str = None,
    detail: str = None,
) -> None:
    """Crea un registro de historial de trazabilidad."""
    entry = History(
        alert_id=alert_id,
        user_id=user_id,
        profile_id=active_profile_id(),
        action=action,
        previous_state=previous_state,
        new_state=new_state,
        detail=detail,
    )
    db.session.add(entry)


def _validated_relations(data):
    """Valida en servidor la cadena cliente → vehículo → dispositivo."""
    client_id = integer(data.get("client_id"), "client_id", optional=True)
    vehicle_id = integer(data.get("vehicle_id"), "vehicle_id", optional=True)
    device_id = integer(data.get("gps_device_id"), "gps_device_id", optional=True)
    event_type_id = integer(data.get("event_type_id"), "event_type_id", optional=True)
    client = db.session.get(Client, client_id) if client_id else None
    vehicle = db.session.get(Vehicle, vehicle_id) if vehicle_id else None
    device = db.session.get(GpsDevice, device_id) if device_id else None
    event_type = db.session.get(EventType, event_type_id) if event_type_id else None
    if bool(client_id) != bool(vehicle_id):
        from werkzeug.exceptions import BadRequest
        raise BadRequest("Selecciona conjuntamente el cliente y su vehículo")
    if client_id and (not client or not client.is_active):
        from werkzeug.exceptions import BadRequest
        raise BadRequest("Cliente no encontrado o inactivo")
    if vehicle_id and (not vehicle or not vehicle.is_active or not vehicle.client.is_active):
        from werkzeug.exceptions import BadRequest
        raise BadRequest("Vehículo no encontrado, inactivo o perteneciente a un cliente inactivo")
    if client and vehicle and vehicle.client_id != client.id:
        from werkzeug.exceptions import BadRequest
        raise BadRequest("El vehículo no pertenece al cliente seleccionado")
    if device_id and (not device or not device.is_active):
        from werkzeug.exceptions import BadRequest
        raise BadRequest("Dispositivo GPS no encontrado o inactivo")
    if device and (not vehicle or device.vehicle_id != vehicle.id):
        from werkzeug.exceptions import BadRequest
        raise BadRequest("El dispositivo GPS no pertenece al vehículo seleccionado")
    if event_type_id and (not event_type or not event_type.is_active):
        from werkzeug.exceptions import BadRequest
        raise BadRequest("Tipo de evento no encontrado o inactivo")
    if event_type and not event_type.generates_alert:
        from werkzeug.exceptions import BadRequest
        raise BadRequest("El tipo de evento seleccionado no genera alertas")
    return vehicle, device, event_type
