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
from app.validation import text_value, date_value, date_range


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
    report = Report(
        name=name,
        type=report_type,
        description=text_value(data, "description"),
        filters_json=json.dumps(data.get("filters", {})),
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
    query = Alert.query
    if report.date_range_start:
        query = query.filter(Alert.created_at >= report.date_range_start)
    if report.date_range_end:
        query = query.filter(Alert.created_at <= report.date_range_end)

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
        "generated_at": datetime.now(timezone.utc).isoformat(),
    }


def _generate_operator_performance(report: Report) -> dict:
    query = Assignment.query
    if report.date_range_start:
        query = query.filter(Assignment.assigned_at >= report.date_range_start)
    if report.date_range_end:
        query = query.filter(Assignment.assigned_at <= report.date_range_end)

    assignments = query.all()
    performance = {}
    for a in assignments:
        if not a.user:
            continue
        name = a.user.full_name
        if name not in performance:
            performance[name] = {"total": 0, "completed": 0, "avg_response_minutes": []}
        performance[name]["total"] += 1
        if a.completed_at:
            performance[name]["completed"] += 1
        if a.response_time_minutes is not None:
            performance[name]["avg_response_minutes"].append(a.response_time_minutes)

    # Calcular promedios
    for name, data in performance.items():
        times = data["avg_response_minutes"]
        data["avg_response_minutes"] = round(sum(times) / len(times), 2) if times else None

    return {
        "type": "operator_performance",
        "operators": performance,
        "generated_at": datetime.now(timezone.utc).isoformat(),
    }


def _generate_response_times(report: Report) -> dict:
    query = Alert.query.filter(Alert.resolved_at.isnot(None))
    if report.date_range_start:
        query = query.filter(Alert.opened_at >= report.date_range_start)
    if report.date_range_end:
        query = query.filter(Alert.opened_at <= report.date_range_end)

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
        "generated_at": datetime.now(timezone.utc).isoformat(),
    }
