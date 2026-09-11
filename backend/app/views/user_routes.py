"""
views/user_routes.py - Endpoints REST para Usuarios
"""

from flask import Blueprint, request
from app.security import admin_required
from flask_jwt_extended import jwt_required
from app.controllers import user_controller

user_bp = Blueprint("users", __name__)


@user_bp.get("/")
@jwt_required()
@admin_required
def get_users():
    """GET /api/users — Lista usuarios con filtros opcionales."""
    filters = {
        "state": request.args.get("state"),
        "profile_id": request.args.get("profile_id"),
        "search": request.args.get("search"),
    }
    return user_controller.get_all_users(filters)


@user_bp.get("/<int:user_id>")
@jwt_required()
@admin_required
def get_user(user_id: int):
    """GET /api/users/<id> — Retorna un usuario por ID."""
    return user_controller.get_user_by_id(user_id)


@user_bp.post("/")
@jwt_required()
@admin_required
def create_user():
    """POST /api/users — Crea un nuevo usuario."""
    data = request.get_json(silent=True) or {}
    return user_controller.create_user(data)


@user_bp.put("/<int:user_id>")
@jwt_required()
@admin_required
def update_user(user_id: int):
    """PUT /api/users/<id> — Actualiza un usuario existente."""
    data = request.get_json(silent=True) or {}
    return user_controller.update_user(user_id, data)


@user_bp.delete("/<int:user_id>")
@jwt_required()
@admin_required
def delete_user(user_id: int):
    """DELETE /api/users/<id> — Elimina un usuario."""
    return user_controller.delete_user(user_id)
