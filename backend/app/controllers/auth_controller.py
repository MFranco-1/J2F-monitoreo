"""Autenticación con perfil único y revocación persistente en users.updated_at."""
from datetime import timedelta
import hashlib
import json
from flask import jsonify
from flask_jwt_extended import create_access_token, create_refresh_token
from sqlalchemy import func
from app import db
from app.models.user import User
from app.security import current_user, is_active
from app.datetime_utils import utcnow, iso_utc, as_utc_naive
from app.validation import text_value


def invalidate_sessions(user):
    now = utcnow()
    if user.updated_at:
        now = max(now, as_utc_naive(user.updated_at) + timedelta(microseconds=1))
    user.updated_at = now


def access_version(user):
    profile = user.profile
    roles = (user.profile_id, profile.name, profile.state_id) if profile else None
    return hashlib.sha256(json.dumps(roles, ensure_ascii=False).encode()).hexdigest()


def claims(user):
    return {"session_version": iso_utc(user.updated_at), "access_version": access_version(user)}


def login(data):
    identifier = text_value(data, "identifier", required=True, limit=150)
    password = data.get("password")
    if not isinstance(password, str) or not password or len(password) > 1024:
        return jsonify({"error": "Contraseña requerida o inválida"}), 400
    user = User.query.filter((func.lower(User.email) == identifier.casefold()) | (User.dni == identifier)).first()
    if not user or not user.check_password(password):
        return jsonify({"error": "Credenciales inválidas"}), 401
    if not is_active(user):
        return jsonify({"error": "La cuenta y su perfil deben estar activos"}), 403
    user.last_login = utcnow()
    invalidate_sessions(user)
    db.session.commit()
    values = claims(user)
    return jsonify({"access_token": create_access_token(identity=str(user.id), additional_claims=values),
                    "refresh_token": create_refresh_token(identity=str(user.id), additional_claims=values),
                    "user": user.to_dict()}), 200


def logout():
    user = current_user()
    invalidate_sessions(user)
    db.session.commit()
    return jsonify({"message": "Sesión cerrada correctamente"}), 200


def refresh_token():
    user = current_user()
    return jsonify({"access_token": create_access_token(identity=str(user.id), additional_claims=claims(user))}), 200


def get_current_user():
    return jsonify({"user": current_user().to_dict()}), 200


def is_token_revoked(payload):
    try:
        user = db.session.get(User, int(payload.get("sub")))
    except (TypeError, ValueError):
        return True
    return (not is_active(user) or payload.get("session_version") != iso_utc(user.updated_at)
            or payload.get("access_version") != access_version(user))
