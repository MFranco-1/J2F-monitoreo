"""Inicio de sesión y cambio seguro del perfil activo."""
from datetime import timedelta
import hashlib
import json
from flask import jsonify, request
from flask_jwt_extended import create_access_token, create_refresh_token
from sqlalchemy import func
from app import db
from app.models.user import User
from app.models.profile import Profile
from app.security import current_user, current_profile, active_profiles, account_is_active
from app.datetime_utils import utcnow, iso_utc, as_utc_naive
from app.validation import text_value, integer


def invalidate_sessions(user):
    now = utcnow()
    if user.updated_at:
        now = max(now, as_utc_naive(user.updated_at) + timedelta(microseconds=1))
    user.updated_at = now


def access_version(user):
    roles = sorted((p.id, p.name, p.state_id) for p in user.profiles)
    if not roles and user.profile:
        roles = [(user.profile.id, user.profile.name, user.profile.state_id)]
    return hashlib.sha256(json.dumps(roles, ensure_ascii=False).encode()).hexdigest()


def claims(user, profile=None, pending=False):
    values = {"session_version": iso_utc(user.updated_at),
              "access_version": access_version(user),
              "profile_selection_pending": pending}
    if profile:
        values.update({"active_profile_id": profile.id, "active_profile_name": profile.name})
    return values


def _final_tokens(user, profile):
    values = claims(user, profile)
    return {"access_token": create_access_token(identity=str(user.id), additional_claims=values),
            "refresh_token": create_refresh_token(identity=str(user.id), additional_claims=values)}


def login(data):
    identifier = text_value(data, "identifier", required=True, limit=150)
    password = data.get("password")
    if not isinstance(password, str) or not password or len(password) > 1024:
        return jsonify({"error": "Contraseña requerida o inválida"}), 400
    user = User.query.filter((func.lower(User.email) == identifier.casefold()) | (User.dni == identifier)).first()
    if not user or not user.check_password(password):
        return jsonify({"error": "Credenciales inválidas"}), 401
    profiles = active_profiles(user)
    if not account_is_active(user) or not profiles:
        return jsonify({"error": "La cuenta debe tener al menos un perfil activo"}), 403
    user.last_login = utcnow()
    invalidate_sessions(user)
    db.session.commit()
    if len(profiles) == 1:
        profile = profiles[0]
        return jsonify({**_final_tokens(user, profile), "requires_profile_selection": False,
                        "profiles": [profile.to_dict()],
                        "user": user.to_dict(active_profile=profile)}), 200
    temporary = create_access_token(identity=str(user.id), additional_claims=claims(user, pending=True),
                                    expires_delta=timedelta(minutes=5))
    return jsonify({"access_token": temporary, "requires_profile_selection": True,
                    "profiles": [p.to_dict() for p in profiles],
                    "user": user.to_dict(active_profile=False)}), 200


def select_profile(data):
    user = current_user()
    profile_id = integer(data.get("profile_id"), "profile_id")
    profile = db.session.get(Profile, profile_id)
    if not account_is_active(user) or profile not in active_profiles(user):
        return jsonify({"error": "El perfil no está asignado al usuario o se encuentra inactivo"}), 403
    invalidate_sessions(user)
    db.session.commit()
    return jsonify({**_final_tokens(user, profile), "requires_profile_selection": False,
                    "profiles": [p.to_dict() for p in active_profiles(user)],
                    "user": user.to_dict(active_profile=profile)}), 200


def logout():
    user = current_user()
    if user:
        invalidate_sessions(user)
        db.session.commit()
    return jsonify({"message": "Sesión cerrada correctamente"}), 200


def refresh_token():
    user = current_user()
    profile = current_profile(user)
    return jsonify({"access_token": create_access_token(
        identity=str(user.id), additional_claims=claims(user, profile))}), 200


def get_current_user():
    user = current_user()
    return jsonify({"user": user.to_dict(active_profile=current_profile(user)),
                    "profiles": [p.to_dict() for p in active_profiles(user)]}), 200


def is_token_revoked(payload):
    try:
        user = db.session.get(User, int(payload.get("sub")))
    except (TypeError, ValueError):
        return True
    if not account_is_active(user):
        return True
    if (payload.get("session_version") != iso_utc(user.updated_at)
            or payload.get("access_version") != access_version(user)):
        return True
    if payload.get("profile_selection_pending"):
        return request.endpoint not in {"auth.select_profile", "auth.logout"}
    try:
        active_id = int(payload.get("active_profile_id"))
    except (TypeError, ValueError):
        return True
    return not any(p.id == active_id for p in active_profiles(user))
