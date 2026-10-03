"""
controllers/report_controller.py - Generación y almacenamiento de Reportes
"""

import json
from datetime import datetime, timezone
from flask import jsonify
from app import db
from app.models.report import Report
from app.models.alert import Alert
from app.models.assignment import Assignment
from app.models.user import User
from app.models.state import State
from app.models.master_data import Client, Vehicle
from app.validation import record_text as text_value, date_value, date_range, integer, priority_value


def get_all_reports() -> tuple:
    reports = Report.query.order_by(Report.created_at.desc()).all()
    return jsonify({"reports": [r.to_dict() for r in reports]}), 200


def get_report_by_id(report_id: int) -> tuple:
    report = Report.query.get_or_404(report_id, description="Reporte no encontrado")
    return jsonify({"report": report.to_dict(include_result=True)}), 200


def create_report(data: dict, current_user_id: int) -> tuple:
    """Crea metadatos de un nuevo reporte (sin generarlo aún)."""
    if not data.get("name") or not data.get("type"):
        return jsonify({"error": "name y type son requeridos"}), 400

    name = text_value(data, "name", required=True, limit=200)
    report_type = text_value(data, "type", required=True, limit=50)
    if report_type not in {"alerts_summary", "operator_performance", "response_times"}:
        return jsonify({"error": "Tipo de reporte no soportado"}), 400
    start = date_value(data.get("date_range_start"), "date_range_start")
    end = date_value(data.get("date_range_end"), "date_range_end", end_of_day=True)
    date_range(start, end)
    filters = data.get("filters")
    if filters is None:
        filters = {}
    if not isinstance(filters, dict):
        return jsonify({"error": "filters debe ser un objeto"}), 400
    normalized_filters = {}
    for field in ("client_id", "vehicle_id", "user_id"):
        value = integer(filters.get(field), field, optional=True)
        if value is not None:
            normalized_filters[field] = value
    if filters.get("priority"):
        normalized_filters["priority"] = priority_value(filters["priority"])
    if filters.get("state"):
        state_name = text_value(filters, "state", required=True, limit=50)
        if not State.query.filter_by(name=state_name, type="alert").first():
            return jsonify({"error": "Estado de alerta no encontrado"}), 400
        normalized_filters["state"] = state_name
    if normalized_filters.get("vehicle_id"):
        vehicle = db.session.get(Vehicle, normalized_filters["vehicle_id"])
        if not vehicle:
            return jsonify({"error": "Vehículo no encontrado"}), 400
        if normalized_filters.get("client_id") and vehicle.client_id != normalized_filters["client_id"]:
            return jsonify({"error": "El vehículo no pertenece al cliente seleccionado"}), 400
    if normalized_filters.get("client_id") and not db.session.get(Client, normalized_filters["client_id"]):
        return jsonify({"error": "Cliente no encontrado"}), 400
    if normalized_filters.get("user_id") and not db.session.get(User, normalized_filters["user_id"]):
        return jsonify({"error": "Usuario no encontrado"}), 400

    report = Report(
        name=name,
        type=report_type,
        description=text_value(data, "description"),
        filters_json=json.dumps(normalized_filters),
        date_range_start=start,
        date_range_end=end,
        generated_by=current_user_id,
    )
    db.session.add(report)
    db.session.commit()
    return jsonify({"message": "Reporte creado", "report": report.to_dict()}), 201


def generate_report(report_id: int) -> tuple:
    """
    Genera el contenido del reporte y lo almacena en result_json.
    Tipo 'alerts_summary': métricas generales de alertas en el rango de fechas.
    Tipo 'operator_performance': rendimiento por operador.
    Tipo 'response_times': tiempos de respuesta por prioridad.
    """
    report = Report.query.get_or_404(report_id, description="Reporte no encontrado")

    generators = {
        "alerts_summary": _generate_alerts_summary,
        "operator_performance": _generate_operator_performance,
        "response_times": _generate_response_times,
    }

    generator_fn = generators.get(report.type)
    if not generator_fn:
        return jsonify({"error": f"Tipo de reporte no soportado: {report.type}"}), 400

    result = generator_fn(report)
    report.result_json = json.dumps(result, ensure_ascii=False)
    db.session.commit()

    return jsonify({"message": "Reporte generado", "report": report.to_dict(include_result=True)}), 200


def delete_report(report_id: int) -> tuple:
    report = Report.query.get_or_404(report_id, description="Reporte no encontrado")
    db.session.delete(report)
    db.session.commit()
    return jsonify({"message": "Reporte eliminado"}), 200


# --- Generadores internos ---

def _generate_alerts_summary(report: Report) -> dict:
    query = _filtered_alert_query(report)

    alerts = query.all()
    by_priority = {}
    by_state = {}
    for alert in alerts:
        by_priority[alert.priority] = by_priority.get(alert.priority, 0) + 1
        state_name = alert.state.name if alert.state else "Desconocido"
        by_state[state_name] = by_state.get(state_name, 0) + 1

    return {
        "type": "alerts_summary",
        "total_alerts": len(alerts),
        "by_priority": by_priority,
        "by_state": by_state,
        "filters": _report_filters(report),
        "generated_at": datetime.now(timezone.utc).isoformat(),
    }


def _generate_operator_performance(report: Report) -> dict:
    query = Assignment.query
    if report.date_range_start:
        query = query.filter(Assignment.assigned_at >= report.date_range_start)
    if report.date_range_end:
        query = query.filter(Assignment.assigned_at <= report.date_range_end)
    filters = _report_filters(report)
    if filters.get("user_id"):
        query = query.filter(Assignment.user_id == filters["user_id"])
    if any(filters.get(key) for key in ("vehicle_id", "client_id", "priority", "state")):
        query = query.join(Alert, Assignment.alert_id == Alert.id)
        if filters.get("vehicle_id"):
            query = query.filter(Alert.vehicle_id == filters["vehicle_id"])
        if filters.get("client_id"):
            query = query.join(Vehicle, Alert.vehicle_id == Vehicle.id).filter(
                Vehicle.client_id == filters["client_id"])
        if filters.get("priority"):
            query = query.filter(Alert.priority == filters["priority"])
        if filters.get("state"):
            query = query.join(State, Alert.state_id == State.id).filter(State.name == filters["state"])

    assignments = query.all()
    performance = {}
    for a in assignments:
        if not a.user:
            continue
        user_id = a.user.id
        if user_id not in performance:
            performance[user_id] = {"technician_id": user_id, "technician": a.user.full_name,
                                    "assigned": 0, "resolved": 0, "reassigned": 0,
                                    "active": 0, "avg_response_minutes": []}
        performance[user_id]["assigned"] += 1
        siblings = a.alert.assignments.order_by(Assignment.assigned_at, Assignment.id).all()
        is_latest = bool(siblings and siblings[-1].id == a.id)
        resolved = bool(a.completed_at and is_latest and a.alert.resolved_at)
        reassigned = bool(a.completed_at and not is_latest)
        if resolved:
            performance[user_id]["resolved"] += 1
        elif reassigned:
            performance[user_id]["reassigned"] += 1
        elif a.completed_at is None:
            performance[user_id]["active"] += 1
        if resolved and a.response_time_minutes is not None:
            performance[user_id]["avg_response_minutes"].append(a.response_time_minutes)

    # Calcular promedios
    for data in performance.values():
        times = data["avg_response_minutes"]
        data["avg_response_minutes"] = round(sum(times) / len(times), 2) if times else None

    rows = sorted(performance.values(), key=lambda item: (item["technician"], item["technician_id"]))
    return {
        "type": "operator_performance",
        "operators": {str(user_id): data for user_id, data in performance.items()},
        "rows": rows,
        "filters": filters,
        "generated_at": datetime.now(timezone.utc).isoformat(),
    }


def _generate_response_times(report: Report) -> dict:
    query = _filtered_alert_query(report, date_field=Alert.opened_at).filter(
        Alert.resolved_at.isnot(None))

    alerts = query.all()
    by_priority = {}
    for alert in alerts:
        p = alert.priority
        if p not in by_priority:
            by_priority[p] = []
        if alert.response_time_minutes is not None:
            by_priority[p].append(alert.response_time_minutes)

    result = {}
    for priority, times in by_priority.items():
        result[priority] = {
            "count": len(times),
            "avg_minutes": round(sum(times) / len(times), 2) if times else None,
            "min_minutes": min(times) if times else None,
            "max_minutes": max(times) if times else None,
        }

    return {
        "type": "response_times",
        "by_priority": result,
        "filters": _report_filters(report),
        "generated_at": datetime.now(timezone.utc).isoformat(),
    }


def _report_filters(report: Report) -> dict:
    try:
        value = json.loads(report.filters_json or "{}")
        return value if isinstance(value, dict) else {}
    except (TypeError, ValueError):
        return {}


def _filtered_alert_query(report: Report, date_field=None):
    date_field = date_field or Alert.created_at
    query = Alert.query
    if report.date_range_start:
        query = query.filter(date_field >= report.date_range_start)
    if report.date_range_end:
        query = query.filter(date_field <= report.date_range_end)
    filters = _report_filters(report)
    if filters.get("user_id"):
        query = query.filter(Alert.assignments.any(Assignment.user_id == filters["user_id"]))
    if filters.get("client_id"):
        query = query.join(Vehicle, Alert.vehicle_id == Vehicle.id).filter(
            Vehicle.client_id == filters["client_id"])
    if filters.get("vehicle_id"):
        query = query.filter(Alert.vehicle_id == filters["vehicle_id"])
    if filters.get("priority"):
        query = query.filter(Alert.priority == filters["priority"])
    if filters.get("state"):
        query = query.join(State, Alert.state_id == State.id).filter(State.name == filters["state"])
    return query
