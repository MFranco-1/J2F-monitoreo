"""
views/alert_routes.py - Endpoints REST para Alertas
"""

from flask import Blueprint, request
from app.security import admin_required
from flask_jwt_extended import jwt_required, get_jwt_identity
from app.controllers import alert_controller

alert_bp = Blueprint("alerts", __name__)


@alert_bp.get("/metrics")
@jwt_required()
def get_metrics():
    """GET /api/alerts/metrics — Métricas para el Dashboard en tiempo real."""
    return alert_controller.get_dashboard_metrics()


@alert_bp.get("/")
@jwt_required()
def get_alerts():
    """
    GET /api/alerts — Lista alertas con filtros.
    Query params: client_id, vehicle_id, state, priority, date_from, date_to, page, per_page
    """
    filters = {
        "client_id": request.args.get("client_id"),
        "vehicle_id": request.args.get("vehicle_id"),
        "state": request.args.get("state"),
        "priority": request.args.get("priority"),
        "date_from": request.args.get("date_from"),
        "date_to": request.args.get("date_to"),
        "page": request.args.get("page", 1),
        "per_page": request.args.get("per_page", 20),
    }
    return alert_controller.get_all_alerts(filters)


@alert_bp.get("/<int:alert_id>")
@jwt_required()
def get_alert(alert_id: int):
    """GET /api/alerts/<id> — Alerta por ID con historial completo."""
    return alert_controller.get_alert_by_id(alert_id)


@alert_bp.post("/")
@jwt_required()
def create_alert():
    """POST /api/alerts — Crea una nueva alerta."""
    data = request.get_json(silent=True) or {}
    current_user_id = int(get_jwt_identity())
    return alert_controller.create_alert(data, current_user_id)


@alert_bp.put("/<int:alert_id>")
@jwt_required()
def update_alert(alert_id: int):
    """PUT /api/alerts/<id> — Actualiza alerta (incluye cambio de estado)."""
    data = request.get_json(silent=True) or {}
    current_user_id = int(get_jwt_identity())
    return alert_controller.update_alert(alert_id, data, current_user_id)


@alert_bp.delete("/<int:alert_id>")
@jwt_required()
@admin_required
def delete_alert(alert_id: int):
    """DELETE /api/alerts/<id> — Elimina una alerta cerrada."""
    current_user_id = int(get_jwt_identity())
    return alert_controller.delete_alert(alert_id, current_user_id)
