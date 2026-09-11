"""
views/menu_routes.py - Endpoints REST para Opciones de Menú
"""

from flask import Blueprint, request
from app.security import admin_required
from flask_jwt_extended import jwt_required, get_jwt_identity
from app.controllers import menu_controller
from app.models.state import State


menu_bp = Blueprint("menu", __name__)


@menu_bp.get("/")
@jwt_required()
def get_menu_options():
    """GET /api/menu-options — Lista opciones de menú. ?parent_only=true para solo raíces."""
    filters = {"parent_only": request.args.get("parent_only", "").lower() == "true",
               "navigation": request.args.get("navigation", "").lower() == "true"}
    return menu_controller.get_all_menu_options(filters)


@menu_bp.get("/<int:option_id>")
@jwt_required()
@admin_required
def get_menu_option(option_id: int):
    """GET /api/menu-options/<id>"""
    return menu_controller.get_menu_option_by_id(option_id)


@menu_bp.post("/")
@jwt_required()
@admin_required
def create_menu_option():
    """POST /api/menu-options — Crea una nueva opción de menú."""
    data = request.get_json(silent=True) or {}
    active_state = State.query.filter_by(name="Activo", type="user").first()
    state_id = data.get("state_id", active_state.id if active_state else None)
    return menu_controller.create_menu_option(data, state_id)


@menu_bp.put("/<int:option_id>")
@jwt_required()
@admin_required
def update_menu_option(option_id: int):
    """PUT /api/menu-options/<id>"""
    data = request.get_json(silent=True) or {}
    return menu_controller.update_menu_option(option_id, data)


@menu_bp.delete("/<int:option_id>")
@jwt_required()
@admin_required
def delete_menu_option(option_id: int):
    """DELETE /api/menu-options/<id>"""
    return menu_controller.delete_menu_option(option_id)
