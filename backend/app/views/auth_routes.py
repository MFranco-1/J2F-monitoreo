"""
views/auth_routes.py - Endpoints de Autenticación
"""

from flask import Blueprint, request
from flask_jwt_extended import jwt_required, get_jwt
from app.controllers import auth_controller

auth_bp = Blueprint("auth", __name__)


@auth_bp.post("/login")
def login():
    """
    POST /api/auth/login
    Body: { "identifier": "email_o_dni", "password": "..." }
    """
    data = request.get_json(silent=True) or {}
    return auth_controller.login(data)


@auth_bp.post("/logout")
@jwt_required(verify_type=False)
def logout():
    """POST /api/auth/logout — Revoca el token JWT actual."""
    return auth_controller.logout()


@auth_bp.post("/refresh")
@jwt_required(refresh=True)
def refresh():
    """POST /api/auth/refresh — Obtiene un nuevo access_token."""
    return auth_controller.refresh_token()


@auth_bp.get("/me")
@jwt_required()
def me():
    """GET /api/auth/me — Retorna el usuario autenticado actual."""
    return auth_controller.get_current_user()
