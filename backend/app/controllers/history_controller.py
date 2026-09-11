"""
controllers/history_controller.py - Consultas de Historial de Trazabilidad
"""

from flask import jsonify
from app.models.history import History
from app.models.alert import Alert
from app.validation import integer, date_value, date_range


def get_history_by_alert(alert_id: int) -> tuple:
    """Retorna el historial completo de una alerta específica."""
    Alert.query.get_or_404(alert_id, description="Alerta no encontrada")
    entries = (
        History.query.filter_by(alert_id=alert_id)
        .order_by(History.timestamp.asc())
        .all()
    )
    return jsonify({"history": [e.to_dict() for e in entries]}), 200


def get_global_history(filters: dict) -> tuple:
    """Retorna el historial global con filtros opcionales."""
    query = History.query

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
