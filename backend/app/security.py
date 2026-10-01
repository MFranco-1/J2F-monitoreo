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


def _has_role(user, accepted_roles, profile=None):
    if not account_is_active(user):
        return False
    if profile is not None:
        return profile in active_profiles(user) and role_name(profile.name) in accepted_roles
    actor = current_user()
    if not actor or actor.id != user.id:
        return any(role_name(item.name) in accepted_roles for item in active_profiles(user))
    selected = current_profile(user)
    if selected:
        return role_name(selected.name) in accepted_roles
    return any(role_name(item.name) in accepted_roles for item in active_profiles(user))


def is_technician(user, profile=None):
    return _has_role(user, {"tecnico"}, profile)


def is_operator(user, profile=None):
    return _has_role(user, {"operador"}, profile)


def is_supervisor(user, profile=None):
    return _has_role(user, {"supervisor"}, profile)


def has_active_role(user, role, *, excluded_profile_id=None):
    """Comprueba un rol activo sin depender del perfil seleccionado en el JWT."""
    return bool(account_is_active(user) and any(
        profile.id != excluded_profile_id and role_name(profile.name) == role
        for profile in active_profiles(user)
    ))


def active_admin_count(*, excluded_user_id=None, excluded_profile_id=None):
    return sum(
        1 for user in User.query.all()
        if user.id != excluded_user_id
        and has_active_role(user, "administrador", excluded_profile_id=excluded_profile_id)
    )


def can_assign(user):
    return bool(is_admin(user) or is_supervisor(user) or is_operator(user))


def can_view_reports(user):
    return bool(is_admin(user) or is_supervisor(user))


def can_view_all_operations(user):
    return bool(is_admin(user) or is_supervisor(user) or is_operator(user))


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


def assignment_manager_required(fn):
    @wraps(fn)
    def wrapped(*args, **kwargs):
        if not can_assign(current_user()):
            return jsonify({"error": "Esta operación requiere el perfil Supervisor, Operador o Administrador"}), 403
        return fn(*args, **kwargs)
    return wrapped


def report_viewer_required(fn):
    @wraps(fn)
    def wrapped(*args, **kwargs):
        if not can_view_reports(current_user()):
            return jsonify({"error": "Esta operación requiere el perfil Supervisor o Administrador"}), 403
        return fn(*args, **kwargs)
    return wrapped


def may_view_alert(alert, user):
    if can_view_all_operations(user):
        return True
    return bool(is_technician(user) and alert.assignments.filter_by(user_id=user.id).first())


def scope_alert_query(query, user=None):
    """Aplica el alcance operativo al query sin confiar en filtros del cliente."""
    from sqlalchemy import false
    from app.models.alert import Alert
    from app.models.assignment import Assignment

    user = user or current_user()
    if can_view_all_operations(user):
        return query
    if is_technician(user):
        return query.filter(Alert.assignments.any(Assignment.user_id == user.id))
    return query.filter(false())


def may_attend(alert, user):
    if is_admin(user):
        return True
    assignee = alert.current_assignee
    return bool(is_technician(user) and assignee and assignee.id == user.id)
