"""
views/report_routes.py - Endpoints REST para Reportes
"""

from flask import Blueprint, request
from flask_jwt_extended import jwt_required, get_jwt_identity
from app.controllers import report_controller
from app.controllers import history_controller

report_bp = Blueprint("reports", __name__)


@report_bp.get("/")
@jwt_required()
def get_reports():
    """GET /api/reports — Lista todos los reportes."""
    return report_controller.get_all_reports()


@report_bp.get("/<int:report_id>")
@jwt_required()
def get_report(report_id: int):
    """GET /api/reports/<id> — Reporte por ID con resultado incluido."""
    return report_controller.get_report_by_id(report_id)


@report_bp.post("/")
@jwt_required()
def create_report():
    """POST /api/reports — Crea metadatos de un reporte."""
    data = request.get_json(silent=True) or {}
    current_user_id = int(get_jwt_identity())
    return report_controller.create_report(data, current_user_id)


@report_bp.post("/<int:report_id>/generate")
@jwt_required()
def generate_report(report_id: int):
    """POST /api/reports/<id>/generate — Genera el contenido del reporte."""
    return report_controller.generate_report(report_id)


@report_bp.delete("/<int:report_id>")
@jwt_required()
def delete_report(report_id: int):
    """DELETE /api/reports/<id> — Elimina un reporte."""
    return report_controller.delete_report(report_id)


# --- Endpoints de Historial (bajo /api/reports/history por proximidad semántica) ---

@report_bp.get("/history")
@jwt_required()
def get_history():
    """
    GET /api/reports/history — Historial global de trazabilidad.
    Query params: action, user_id, date_from, date_to, page, per_page
    """
    filters = {
        "action": request.args.get("action"),
        "user_id": request.args.get("user_id"),
        "date_from": request.args.get("date_from"),
        "date_to": request.args.get("date_to"),
        "page": request.args.get("page", 1),
        "per_page": request.args.get("per_page", 30),
    }
    return history_controller.get_global_history(filters)


@report_bp.get("/history/alerts/<int:alert_id>")
@jwt_required()
def get_alert_history(alert_id: int):
    """GET /api/reports/history/alerts/<id> — Historial de una alerta específica."""
    return history_controller.get_history_by_alert(alert_id)
