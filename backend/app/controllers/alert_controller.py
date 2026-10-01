"""
controllers/alert_controller.py - Lógica de negocio para Alertas
Gestiona el flujo automático de alertas, cambio de estados y trazabilidad.
"""

from app.datetime_utils import utcnow
import json
from urllib.error import HTTPError, URLError
from urllib.parse import urlencode
from urllib.request import Request, urlopen
from flask import current_app, jsonify
from app import db
from app.models.alert import Alert
from app.models.state import State
from app.models.history import History
from app.models.master_data import Client, Vehicle, GpsDevice, EventType
from app.models.assignment import Assignment
from app.validation import text_value, priority_value, integer, date_value, date_range
from app.security import (
    current_user, may_attend, may_view_alert, scope_alert_query,
    active_profile_id, can_view_all_operations, is_technician,
)


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
    Filtros: client_id, vehicle_id, state, priority, date_from, date_to
    """
    query = scope_alert_query(Alert.query, current_user()).join(State, Alert.state_id == State.id)

    client_id = integer(filters.get("client_id"), "client_id", optional=True)
    vehicle_id = integer(filters.get("vehicle_id"), "vehicle_id", optional=True)
    client = db.session.get(Client, client_id) if client_id else None
    vehicle = db.session.get(Vehicle, vehicle_id) if vehicle_id else None
    if client_id and not client:
        from werkzeug.exceptions import BadRequest
        raise BadRequest("Cliente no encontrado")
    if vehicle_id and not vehicle:
        from werkzeug.exceptions import BadRequest
        raise BadRequest("Vehículo no encontrado")
    if client and vehicle and vehicle.client_id != client.id:
        from werkzeug.exceptions import BadRequest
        raise BadRequest("El vehículo no pertenece al cliente seleccionado")
    if client_id:
        query = query.join(Vehicle, Alert.vehicle_id == Vehicle.id).filter(Vehicle.client_id == client_id)
    if vehicle_id:
        query = query.filter(Alert.vehicle_id == vehicle_id)

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
    if not may_view_alert(alert, current_user()):
        return jsonify({"error": "No tienes acceso a esta alerta"}), 403
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
        return jsonify({"error": "Solo el técnico asignado o un administrador puede modificar la alerta"}), 403
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
    base_query = scope_alert_query(Alert.query, current_user())
    total = base_query.count()

    states = State.query.filter_by(type="alert").all()
    state_counts = {}
    for state in states:
        count = base_query.filter(Alert.state_id == state.id).count()
        state_counts[state.name] = count

    # Últimas 7 alertas críticas abiertas
    critical_open = (
        scope_alert_query(Alert.query, current_user()).join(State)
        .filter(Alert.priority == "critical", State.name == "Abierto")
        .order_by(Alert.opened_at.desc())
        .limit(7)
        .all()
    )

    # Tiempo promedio de respuesta (alertas cerradas)
    closed_alerts = base_query.filter(Alert.resolved_at.isnot(None)).all()
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


SIMULATED_EVENT_CODES = {"SPEEDING", "GPS_SIGNAL_LOSS", "SOS", "LOW_FUEL"}


def get_map_vehicles(client_id_value=None) -> tuple:
    """Devuelve solo vehículos que el perfil activo puede consultar."""
    actor = current_user()
    query = Vehicle.query.join(State, Vehicle.state_id == State.id).filter(State.name == "Activo")
    if is_technician(actor) and not can_view_all_operations(actor):
        query = query.filter(Vehicle.alerts.any(
            Alert.assignments.any(Assignment.user_id == actor.id)
        ))
    elif not can_view_all_operations(actor):
        return jsonify({"error": "El perfil activo no puede consultar vehículos"}), 403

    client_id = integer(client_id_value, "client_id", optional=True)
    if client_id:
        query = query.filter(Vehicle.client_id == client_id)

    vehicles = []
    for vehicle in query.order_by(Vehicle.plate).all():
        device = vehicle.gps_devices.join(State).filter(State.name == "Activo").order_by(GpsDevice.id).first()
        open_events_query = (
            Alert.query.join(State, Alert.state_id == State.id)
            .filter(Alert.vehicle_id == vehicle.id, State.name != "Cerrado")
        )
        if is_technician(actor) and not can_view_all_operations(actor):
            open_events_query = open_events_query.filter(
                Alert.assignments.any(Assignment.user_id == actor.id))
        open_events = open_events_query.order_by(Alert.opened_at.desc()).all()
        last_fuel_confirmation = (
            History.query.join(Alert, History.alert_id == Alert.id)
            .filter(Alert.vehicle_id == vehicle.id, History.action == "fuel_confirmed")
        )
        if is_technician(actor) and not can_view_all_operations(actor):
            last_fuel_confirmation = last_fuel_confirmation.filter(
                Alert.assignments.any(Assignment.user_id == actor.id))
        last_fuel_confirmation = last_fuel_confirmation.order_by(
            History.timestamp.desc(), History.id.desc()).first()
        vehicles.append({
            "id": vehicle.id,
            "plate": vehicle.plate,
            "brand": vehicle.brand,
            "model": vehicle.model,
            "client": vehicle.client.to_dict() if vehicle.client else None,
            "gps_device": device.to_dict() if device else None,
            # La confirmación persistida permite que otro navegador reconozca una
            # recarga explícita. Cerrar una alerta por sí solo no produce este dato.
            "fuel_confirmation": ({
                "alert_id": last_fuel_confirmation.alert_id,
                "timestamp": last_fuel_confirmation.to_dict()["timestamp"],
            } if last_fuel_confirmation else None),
            "open_events": [_map_open_event(item, actor) for item in open_events],
        })
    return jsonify({"vehicles": vehicles}), 200


def _map_open_event(alert, actor):
    """Serializa cualquier alerta abierta sin tratarla como evento simulable."""
    code = alert.event_type.code if alert.event_type else None
    is_low_fuel = code == "LOW_FUEL"
    return {
        "alert_id": alert.id,
        "code": code,
        "name": alert.event_type.name if alert.event_type else alert.title,
        "priority": alert.priority,
        "can_coordinate": may_attend(alert, actor),
        "fuel_status": _fuel_status(alert) if is_low_fuel else "pending",
        "fuel_workflow": (_fuel_workflow(alert) if is_low_fuel else
                          {"coordination": None, "confirmation": None}),
    }


def create_map_event(data: dict, current_user_id: int) -> tuple:
    """Convierte un evento cartográfico simulado en una alerta persistente."""
    vehicle_id = integer(data.get("vehicle_id"), "vehicle_id")
    event_code = text_value(data, "event_code", required=True, limit=50)
    if event_code not in SIMULATED_EVENT_CODES:
        return jsonify({"error": "Evento de mapa no soportado"}), 400
    try:
        latitude = float(data.get("latitude"))
        longitude = float(data.get("longitude"))
        speed = max(0.0, min(float(data.get("speed", 0)), 250.0))
    except (TypeError, ValueError):
        return jsonify({"error": "La posición y velocidad simuladas son inválidas"}), 400
    if not (-90 <= latitude <= 90 and -180 <= longitude <= 180):
        return jsonify({"error": "La posición simulada está fuera de rango"}), 400
    fuel_percent = None
    if event_code == "LOW_FUEL":
        try:
            fuel_percent = float(data.get("fuel_percent"))
        except (TypeError, ValueError):
            return jsonify({"error": "Indica el porcentaje de combustible simulado"}), 400
        if not (0 <= fuel_percent <= 10):
            return jsonify({"error": "Combustible bajo requiere un nivel entre 0 % y 10 %"}), 400

    vehicle = Vehicle.query.filter_by(id=vehicle_id).with_for_update().first()
    if not vehicle or not vehicle.is_active or not vehicle.client or not vehicle.client.is_active:
        return jsonify({"error": "Vehículo no encontrado o inactivo"}), 404
    event_type = EventType.query.filter_by(code=event_code).first()
    if not event_type or not event_type.is_active or not event_type.generates_alert:
        return jsonify({"error": "Tipo de evento no disponible"}), 409

    duplicate = (
        Alert.query.join(State, Alert.state_id == State.id)
        .filter(Alert.vehicle_id == vehicle.id, Alert.event_type_id == event_type.id,
                State.name != "Cerrado").first()
    )
    if duplicate:
        return jsonify({"message": "Ya existe una alerta abierta para este evento y vehículo",
                        "created": False, "alert": duplicate.to_dict()}), 200

    open_state = State.query.filter_by(name="Abierto", type="alert").first()
    if not open_state:
        return jsonify({"error": "Estado 'Abierto' no configurado"}), 500
    device = vehicle.gps_devices.join(State).filter(State.name == "Activo").order_by(GpsDevice.id).first()
    location = f"Posición simulada: {latitude:.5f}, {longitude:.5f}"
    alert = Alert(
        title=f"{event_type.name} - {vehicle.plate}",
        description=(f"Evento generado desde el mapa. Velocidad simulada: {speed:.0f} km/h. "
                     f"{f'Combustible simulado: {fuel_percent:.1f} %. ' if fuel_percent is not None else ''}"
                     f"{event_type.expected_action or ''}").strip(),
        priority=event_type.default_priority,
        service_type="Monitoreo GPS",
        location=location,
        source="Simulación cartográfica",
        state=open_state,
        vehicle=vehicle,
        gps_device=device,
        event_type=event_type,
        created_by=current_user_id,
    )
    db.session.add(alert)
    db.session.flush()
    _log_history(alert.id, current_user_id, "created", new_state="Abierto",
                 detail=(f"{event_type.name}; {location}; velocidad {speed:.0f} km/h"
                         + (f"; combustible {fuel_percent:.1f} %" if fuel_percent is not None else "")))
    db.session.commit()
    return jsonify({"message": f"Alerta #{alert.id} creada para {vehicle.plate}",
                    "created": True, "alert": alert.to_dict()}), 201


def get_nearby_fuel_stations(latitude_value, longitude_value, radius_value=None,
                             alert_id_value=None) -> tuple:
    """Consulta estaciones reales registradas en OpenStreetMap mediante Overpass."""
    permission_error = _validate_fuel_service_access(alert_id_value)
    if permission_error:
        return permission_error
    latitude, longitude = _coordinates(latitude_value, longitude_value)
    radius = integer(radius_value or 3000, "radius", minimum=100, maximum=10000)
    endpoint = current_app.config.get("OVERPASS_API_URL")
    if not endpoint:
        return jsonify({"error": "El servicio de estaciones no está configurado"}), 503
    query = (f'[out:json][timeout:10];nwr["amenity"="fuel"]'
             f'(around:{radius},{latitude},{longitude});out center tags;')
    try:
        payload = _external_json(endpoint, data=urlencode({"data": query}).encode("utf-8"))
        stations = []
        for item in payload.get("elements", []):
            lat = item.get("lat") or (item.get("center") or {}).get("lat")
            lng = item.get("lon") or (item.get("center") or {}).get("lon")
            if lat is None or lng is None:
                continue
            tags = item.get("tags") or {}
            stations.append({"id": f'{item.get("type", "osm")}-{item.get("id")}',
                             "name": tags.get("name") or tags.get("brand") or "Estación sin nombre registrado",
                             "brand": tags.get("brand"), "latitude": lat, "longitude": lng})
        return jsonify({"stations": stations, "source": "OpenStreetMap"}), 200
    except (HTTPError, URLError, TimeoutError, ValueError, json.JSONDecodeError):
        return jsonify({"error": "No se pudo consultar el servicio de estaciones cercanas"}), 502


def get_street_route(origin_lat, origin_lng, destination_lat, destination_lng,
                     alert_id_value=None) -> tuple:
    """Obtiene una geometría vial real; nunca fabrica una línea de respaldo."""
    if alert_id_value is not None:
        permission_error = _validate_fuel_service_access(alert_id_value)
        if permission_error:
            return permission_error
    start_lat, start_lng = _coordinates(origin_lat, origin_lng)
    end_lat, end_lng = _coordinates(destination_lat, destination_lng)
    endpoint = (current_app.config.get("ROUTING_API_URL") or "").rstrip("/")
    if not endpoint:
        return jsonify({"error": "El servicio de rutas no está configurado"}), 503
    url = (f"{endpoint}/route/v1/driving/{start_lng},{start_lat};{end_lng},{end_lat}"
           "?overview=full&geometries=geojson&steps=false")
    try:
        payload = _external_json(url)
        routes = payload.get("routes") or []
        if payload.get("code") != "Ok" or not routes:
            return jsonify({"error": "El servicio no encontró una ruta por calles"}), 404
        route = routes[0]
        coordinates = route.get("geometry", {}).get("coordinates") or []
        if len(coordinates) < 2:
            return jsonify({"error": "El servicio no devolvió una geometría vial válida"}), 502
        return jsonify({"coordinates": [[lat, lng] for lng, lat in coordinates],
                        "distance_meters": route.get("distance"),
                        "duration_seconds": route.get("duration"), "source": "OSRM"}), 200
    except (HTTPError, URLError, TimeoutError, ValueError, json.JSONDecodeError):
        return jsonify({"error": "No se pudo consultar el servicio de rutas"}), 502


def record_fuel_action(alert_id: int, data: dict, user_id: int) -> tuple:
    alert = Alert.query.filter_by(id=alert_id).with_for_update().first_or_404(
        description="Alerta no encontrada")
    if not alert.event_type or alert.event_type.code != "LOW_FUEL":
        return jsonify({"error": "La alerta no corresponde a combustible bajo"}), 400
    if alert.state.name == "Cerrado":
        if not may_view_alert(alert, current_user()):
            return jsonify({"error": "No tienes acceso a esta alerta"}), 403
        return jsonify({"error": "La alerta de combustible ya está cerrada"}), 409
    if not may_attend(alert, current_user()):
        return jsonify({"error": "Solo el técnico asignado o un administrador puede registrar el abastecimiento"}), 403
    action = text_value(data, "action", required=True, limit=30)
    observation = text_value(data, "observation", required=True, limit=500)
    actions = {"coordinate": ("fuel_coordinated", "Coordinación de abastecimiento"),
               "confirm": ("fuel_confirmed", "Abastecimiento confirmado")}
    if action not in actions:
        return jsonify({"error": "Acción de abastecimiento inválida"}), 400
    history_action, label = actions[action]
    if alert.history.filter_by(action=history_action).first():
        return jsonify({"error": f"{label} ya fue registrada"}), 409
    if action == "confirm" and not alert.history.filter_by(action="fuel_coordinated").first():
        return jsonify({"error": "Primero registra la coordinación del abastecimiento"}), 409
    station = _validated_station(data.get("station")) if action == "coordinate" else None
    detail = json.dumps({
        "observacion": observation,
        "modalidad": "estacion" if station else "manual",
        "estacion": station,
    }, ensure_ascii=False, separators=(",", ":"))
    _log_history(alert.id, user_id, history_action, detail=detail)
    if action == "confirm":
        result = _change_state(alert, user_id, "Cerrado", f"Abastecimiento confirmado: {observation}")
        if result is not None:
            db.session.rollback()
            return result
    db.session.commit()
    return jsonify({"message": f"{label} registrada", "fuel_status": _fuel_status(alert),
                    "fuel_workflow": _fuel_workflow(alert)}), 200


def _fuel_status(alert):
    if alert.history.filter_by(action="fuel_confirmed").first():
        return "confirmed"
    if alert.history.filter_by(action="fuel_coordinated").first():
        return "coordinated"
    return "pending"


def _fuel_workflow(alert):
    """Reconstruye el avance persistido sin depender de la animación del navegador."""
    return {
        "coordination": _fuel_history_data(
            alert.history.filter_by(action="fuel_coordinated").order_by(History.id.desc()).first()),
        "confirmation": _fuel_history_data(
            alert.history.filter_by(action="fuel_confirmed").order_by(History.id.desc()).first()),
    }


def _fuel_history_data(entry):
    if not entry:
        return None
    try:
        payload = json.loads(entry.detail or "{}")
    except (TypeError, ValueError, json.JSONDecodeError):
        payload = {"observacion": entry.detail, "modalidad": "manual", "estacion": None}
    return {
        "user": ({"id": entry.user.id, "full_name": entry.user.full_name}
                 if entry.user else None),
        "profile": ({"id": entry.profile.id, "name": entry.profile.name}
                    if entry.profile else None),
        "timestamp": entry.to_dict()["timestamp"],
        "observation": payload.get("observacion"),
        "mode": payload.get("modalidad", "manual"),
        "station": payload.get("estacion"),
    }


def _validated_station(value):
    if value is None:
        return None
    if not isinstance(value, dict):
        from werkzeug.exceptions import BadRequest
        raise BadRequest("La estación seleccionada no es válida")
    name = text_value(value, "name", required=True, limit=160)
    latitude, longitude = _coordinates(value.get("latitude"), value.get("longitude"))
    station = {
        "id": text_value(value, "id", limit=100),
        "name": name,
        "latitude": latitude,
        "longitude": longitude,
    }
    if value.get("road_distance") is not None:
        try:
            road_distance = float(value["road_distance"])
        except (TypeError, ValueError):
            from werkzeug.exceptions import BadRequest
            raise BadRequest("La distancia vial de la estación no es válida")
        if road_distance < 0:
            from werkzeug.exceptions import BadRequest
            raise BadRequest("La distancia vial de la estación no es válida")
        station["road_distance"] = road_distance
    return station


def _validate_fuel_service_access(alert_id_value):
    alert_id = integer(alert_id_value, "alert_id")
    alert = db.session.get(Alert, alert_id)
    if not alert:
        return jsonify({"error": "Alerta no encontrada"}), 404
    if not alert.event_type or alert.event_type.code != "LOW_FUEL":
        return jsonify({"error": "La alerta no corresponde a combustible bajo"}), 400
    if alert.state.name == "Cerrado":
        return jsonify({"error": "La alerta de combustible ya está cerrada"}), 409
    if not may_attend(alert, current_user()):
        return jsonify({"error": "Solo el técnico asignado o un administrador puede consultar el abastecimiento"}), 403
    return None


def _coordinates(latitude_value, longitude_value):
    try:
        latitude, longitude = float(latitude_value), float(longitude_value)
    except (TypeError, ValueError):
        from werkzeug.exceptions import BadRequest
        raise BadRequest("Coordenadas inválidas")
    if not (-90 <= latitude <= 90 and -180 <= longitude <= 180):
        from werkzeug.exceptions import BadRequest
        raise BadRequest("Coordenadas fuera de rango")
    return latitude, longitude


def _external_json(url, data=None):
    request = Request(url, data=data, headers={"User-Agent": "J2F-Monitoreo/1.0",
                                               "Content-Type": "application/x-www-form-urlencoded"})
    with urlopen(request, timeout=current_app.config.get("MAP_SERVICE_TIMEOUT", 12)) as response:
        return json.loads(response.read().decode("utf-8"))


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

    if new_state_name == "Cerrado" and not notes:
        return jsonify({"error": "Registra la solución aplicada antes de cerrar la alerta"}), 400
    if (new_state_name == "Cerrado" and alert.event_type
            and alert.event_type.code == "LOW_FUEL"
            and not alert.history.filter_by(action="fuel_confirmed").first()):
        return jsonify({"error": "Confirma y documenta el abastecimiento antes de cerrar la alerta"}), 409

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
        action="closed" if new_state_name == "Cerrado" else "state_changed",
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
    if event_type and event_type.code == "LOW_FUEL" and (not client or not vehicle):
        from werkzeug.exceptions import BadRequest
        raise BadRequest("Combustible bajo requiere seleccionar un cliente y su vehículo")
    return vehicle, device, event_type
