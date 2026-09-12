"""Autorización basada exclusivamente en el perfil activo del JWT."""
from functools import wraps
import unicodedata
from flask import jsonify
from flask_jwt_extended import get_jwt, get_jwt_identity
from app import db
from app.models.user import User


def role_name(name):
    value = name or ""
    return "".join(c for c in unicodedata.normalize("NFD", value.strip().casefold())
                   if unicodedata.category(c) != "Mn")


def active_profiles(user):
    if not user:
        return []
    assigned = list(user.profiles)
    if not assigned and user.profile:
        assigned = [user.profile]
    return [p for p in assigned if p.state and p.state.name == "Activo"]


def account_is_active(user):
    return bool(user and user.state and user.state.name == "Activo")


def current_profile(user=None):
    user = user or current_user()
    try:
        profile_id = int(get_jwt().get("active_profile_id"))
    except (RuntimeError, TypeError, ValueError):
        return None
    return next((p for p in active_profiles(user) if p.id == profile_id), None)


def is_active(user):
    return bool(account_is_active(user) and current_profile(user))


def is_admin(user):
    profile = current_profile(user)
    return bool(account_is_active(user) and profile and role_name(profile.name) == "administrador")


def is_operator(user, profile=None):
    if not account_is_active(user):
        return False
    if profile is not None:
        return profile in active_profiles(user) and role_name(profile.name) in {"tecnico", "operador"}
    actor = current_user()
    if not actor or actor.id != user.id:
        return any(role_name(item.name) in {"tecnico", "operador"} for item in active_profiles(user))
    selected = current_profile(user)
    if selected:
        return role_name(selected.name) in {"tecnico", "operador"}
    return any(role_name(item.name) in {"tecnico", "operador"} for item in active_profiles(user))


def current_user():
    try:
        return db.session.get(User, int(get_jwt_identity()))
    except (RuntimeError, ValueError, TypeError):
        return None


def active_profile_id():
    profile = current_profile()
    return profile.id if profile else None


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
