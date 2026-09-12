"""
views/assignment_routes.py - Endpoints REST para Asignaciones
"""

from flask import Blueprint, request
from app.security import assignment_manager_required
from flask_jwt_extended import jwt_required, get_jwt_identity
from app.controllers import assignment_controller

assignment_bp = Blueprint("assignments", __name__)


@assignment_bp.get("/")
@jwt_required()
def get_assignments():
    """
    GET /api/assignments — Lista asignaciones.
    Query params: alert_id, user_id, active_only=true
    """
    filters = {
        "alert_id": request.args.get("alert_id"),
        "user_id": request.args.get("user_id"),
        "active_only": request.args.get("active_only", "").lower() == "true",
    }
    return assignment_controller.get_all_assignments(filters)


@assignment_bp.post("/")
@jwt_required()
@assignment_manager_required
def create_assignment():
    """POST /api/assignments - Asignación manual de alerta a técnico."""
    data = request.get_json(silent=True) or {}
    current_user_id = int(get_jwt_identity())
    return assignment_controller.create_assignment(data, current_user_id)


@assignment_bp.post("/auto-assign")
@jwt_required()
@assignment_manager_required
def auto_assign():
    """
    POST /api/assignments/auto-assign
    Body: { "alert_id": <int> }
    Asigna automáticamente al técnico con menor carga.
    """
    data = request.get_json(silent=True) or {}
    current_user_id = int(get_jwt_identity())
    return assignment_controller.auto_assign(data, current_user_id)


@assignment_bp.get("/technicians")
@jwt_required()
@assignment_manager_required
def get_technicians():
    """GET /api/assignments/technicians - Técnicos activos disponibles."""
    return assignment_controller.get_available_technicians()


@assignment_bp.put("/<int:assignment_id>")
@jwt_required()
def update_assignment(assignment_id: int):
    """PUT /api/assignments/<id> — Actualiza notas o completa una asignación."""
    data = request.get_json(silent=True) or {}
    current_user_id = int(get_jwt_identity())
    return assignment_controller.update_assignment(assignment_id, data, current_user_id)
