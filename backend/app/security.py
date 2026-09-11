"""Permisos de las operaciones existentes, consultados en la base de datos."""
from functools import wraps
import unicodedata
from flask import jsonify
from flask_jwt_extended import get_jwt_identity
from app import db
from app.models.user import User


def role_name(name):
    return "".join(c for c in unicodedata.normalize("NFD", name.strip().casefold())
                   if unicodedata.category(c) != "Mn")


def is_active(user):
    return bool(user and user.state and user.state.name == "Activo"
                and user.profile and user.profile.state
                and user.profile.state.name == "Activo")


def is_admin(user):
    return bool(is_active(user) and role_name(user.profile.name) == "administrador")


def is_operator(user):
    return bool(is_active(user) and role_name(user.profile.name) in {"tecnico", "operador"})


def current_user():
    try:
        return db.session.get(User, int(get_jwt_identity()))
    except (ValueError, TypeError):
        return None


def admin_required(fn):
    @wraps(fn)
    def wrapped(*args, **kwargs):
        if not is_admin(current_user()):
            return jsonify({"error": "Esta operación requiere el perfil Administrador"}), 403
        return fn(*args, **kwargs)
    return wrapped


def may_attend(alert, user):
    if is_admin(user):
        return True
    assignee = alert.current_assignee
    return bool(is_operator(user) and assignee and assignee.id == user.id)
