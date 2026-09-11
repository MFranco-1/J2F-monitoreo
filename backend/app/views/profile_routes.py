"""
views/profile_routes.py - Endpoints REST para Perfiles
"""

from flask import Blueprint, request
from app.security import admin_required
from flask_jwt_extended import jwt_required
from app.controllers import profile_controller

profile_bp = Blueprint("profiles", __name__)


@profile_bp.get("/")
@jwt_required()
@admin_required
def get_profiles():
    """GET /api/profiles — Lista todos los perfiles."""
    return profile_controller.get_all_profiles()


@profile_bp.get("/<int:profile_id>")
@jwt_required()
@admin_required
def get_profile(profile_id: int):
    """GET /api/profiles/<id> — Perfil por ID con opciones de menú."""
    return profile_controller.get_profile_by_id(profile_id)


@profile_bp.post("/")
@jwt_required()
@admin_required
def create_profile():
    """POST /api/profiles — Crea un nuevo perfil."""
    data = request.get_json(silent=True) or {}
    return profile_controller.create_profile(data)


@profile_bp.put("/<int:profile_id>")
@jwt_required()
@admin_required
def update_profile(profile_id: int):
    """PUT /api/profiles/<id> — Actualiza un perfil."""
    data = request.get_json(silent=True) or {}
    return profile_controller.update_profile(profile_id, data)


@profile_bp.delete("/<int:profile_id>")
@jwt_required()
@admin_required
def delete_profile(profile_id: int):
    """DELETE /api/profiles/<id> — Elimina un perfil."""
    return profile_controller.delete_profile(profile_id)
