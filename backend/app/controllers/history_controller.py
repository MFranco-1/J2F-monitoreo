"""
controllers/history_controller.py - Consultas de Historial de Trazabilidad
"""

from flask import jsonify
from app.models.history import History
from app.models.alert import Alert
from app.validation import integer, date_value, date_range
from app.security import current_user, may_view_alert, scope_alert_query


def get_history_by_alert(alert_id: int) -> tuple:
    """Retorna el historial completo de una alerta específica."""
    alert = Alert.query.get_or_404(alert_id, description="Alerta no encontrada")
    if not may_view_alert(alert, current_user()):
        return jsonify({"error": "No tienes acceso al historial de esta alerta"}), 403
    entries = (
        History.query.filter_by(alert_id=alert_id)
        .order_by(History.timestamp.asc())
        .all()
    )
    return jsonify({"history": [e.to_dict() for e in entries]}), 200


def get_global_history(filters: dict) -> tuple:
    """Retorna el historial global con filtros opcionales."""
    allowed_alerts = scope_alert_query(Alert.query, current_user()).with_entities(Alert.id)
    query = History.query.filter(History.alert_id.in_(allowed_alerts))

    if filters.get("action"):
        query = query.filter_by(action=filters["action"])
    if filters.get("user_id"):
        query = query.filter_by(user_id=integer(filters["user_id"], "user_id"))
    start = date_value(filters.get("date_from"), "date_from")
    end = date_value(filters.get("date_to"), "date_to", end_of_day=True)
    date_range(start, end)
    if start is not None:
        query = query.filter(History.timestamp >= start)
    if end is not None:
        query = query.filter(History.timestamp <= end)

    page = integer(filters.get("page", 1), "page")
    per_page = integer(filters.get("per_page", 30), "per_page", maximum=200)
    pagination = query.order_by(History.timestamp.desc()).paginate(
        page=page, per_page=per_page, error_out=False
    )

    return jsonify({
        "history": [e.to_dict() for e in pagination.items],
        "total": pagination.total,
        "pages": pagination.pages,
        "current_page": page,
    }), 200
