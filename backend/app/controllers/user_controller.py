"""CRUD de usuarios con validación y baja mediante el estado existente."""
from flask import jsonify
from werkzeug.exceptions import BadRequest
from sqlalchemy import func
from app import db
from app.models.user import User
from app.models.state import State
from app.security import current_user
from app.validation import text_value, validate_dni, validate_email, user_state, ids_list
from app.models.profile import Profile
from app.controllers.auth_controller import invalidate_sessions


def get_all_users(filters):
    query = User.query
    if filters.get("state"):
        query = query.join(State).filter(State.name == filters["state"])
    if filters.get("profile_id"):
        profile_id = ids_list([filters["profile_id"]], "profile_id")[0]
        query = query.filter(User.profiles.any(Profile.id == profile_id))
    if filters.get("search"):
        term = f"%{filters['search']}%"
        query = query.filter(User.full_name.ilike(term) | User.email.ilike(term) | User.dni.ilike(term))
    return jsonify({"users": [u.to_dict() for u in query.order_by(User.full_name).all()]}), 200


def get_user_by_id(user_id):
    return jsonify({"user": User.query.get_or_404(user_id).to_dict()}), 200


def _check_user_fields(data):
    unsupported = {"profiles", "first_name", "paternal_last_name", "maternal_last_name", "phone"} & data.keys()
    if unsupported:
        raise BadRequest("Esta base utiliza full_name y profile_ids")


def _profiles(value):
    values = ids_list(value, "profile_ids")
    if not values:
        raise BadRequest("Selecciona al menos un perfil activo")
    profiles = Profile.query.filter(Profile.id.in_(values)).all()
    if len(profiles) != len(values):
        raise BadRequest("Uno de los perfiles no existe")
    if any(not p.state or p.state.name != "Activo" for p in profiles):
        raise BadRequest("Solo se pueden asignar perfiles activos")
    order = {profile_id: index for index, profile_id in enumerate(values)}
    return sorted(profiles, key=lambda p: order[p.id])


def create_user(data):
    _check_user_fields(data)
    dni = validate_dni(text_value(data, "dni", required=True, limit=20))
    name = text_value(data, "full_name", required=True, limit=150)
    email = validate_email(text_value(data, "email", required=True, limit=150))
    password = data.get("password")
    if not isinstance(password, str) or not password.strip() or len(password) > 1024:
        return jsonify({"error": "Contraseña requerida"}), 400
    state = user_state(data.get("state_id"))
    raw_profiles = data.get("profile_ids")
    if raw_profiles is None and data.get("profile_id") is not None:
        raw_profiles = [data["profile_id"]]
    profiles = _profiles(raw_profiles)
    if User.query.filter_by(dni=dni).first():
        return jsonify({"error": "DNI ya registrado"}), 409
    if User.query.filter(func.lower(User.email) == email).first():
        return jsonify({"error": "Correo ya registrado"}), 409
    user = User(dni=dni, full_name=name, email=email, profile_id=profiles[0].id,
                profiles=profiles, state=state)
    user.set_password(password)
    db.session.add(user)
    db.session.commit()
    return jsonify({"message": "Usuario creado", "user": user.to_dict()}), 201


def update_user(user_id, data):
    _check_user_fields(data)
    user = User.query.get_or_404(user_id)
    dni = validate_dni(text_value(data, "dni", required=True, limit=20)) if "dni" in data else user.dni
    name = text_value(data, "full_name", required=True, limit=150) if "full_name" in data else user.full_name
    email = validate_email(text_value(data, "email", required=True, limit=150)) if "email" in data else user.email
    state = user_state(data["state_id"]) if "state_id" in data else user.state
    if "profile_ids" in data:
        profiles = _profiles(data["profile_ids"])
    elif "profile_id" in data:
        profiles = _profiles([data["profile_id"]])
    else:
        profiles = list(user.profiles) or ([user.profile] if user.profile else [])
        if not profiles or any(not p.state or p.state.name != "Activo" for p in profiles):
            raise BadRequest("Todo usuario debe conservar al menos un perfil activo")
    password = data.get("password", "")
    if not isinstance(password, str) or len(password) > 1024:
        return jsonify({"error": "La contraseña debe ser texto"}), 400
    if current_user().id == user.id and state.name != "Activo":
        return jsonify({"error": "No puedes desactivar tu propia cuenta"}), 409
    if User.query.filter(User.dni == dni, User.id != user_id).first():
        return jsonify({"error": "DNI ya registrado"}), 409
    if User.query.filter(func.lower(User.email) == email, User.id != user_id).first():
        return jsonify({"error": "Correo ya en uso"}), 409
    user.dni, user.full_name, user.email = dni, name, email
    user.state, user.profiles = state, profiles
    if user.profile_id not in {profile.id for profile in profiles}:
        user.profile_id = profiles[0].id
    if password:
        if not password.strip() or len(password) > 1024:
            return jsonify({"error": "La contraseña no puede contener solo espacios"}), 400
        user.set_password(password)
    invalidate_sessions(user)
    db.session.commit()
    return jsonify({"message": "Usuario actualizado", "user": user.to_dict()}), 200


def delete_user(user_id):
    user = User.query.get_or_404(user_id)
    if current_user().id == user.id:
        return jsonify({"error": "No puedes desactivar tu propia cuenta"}), 409
    inactive = State.query.filter_by(name="Inactivo", type="user").first()
    if not inactive:
        return jsonify({"error": "No está configurado el estado Inactivo"}), 409
    user.state = inactive
    invalidate_sessions(user)
    db.session.commit()
    return jsonify({"message": f"Usuario {user.full_name} desactivado; se conserva su historial"}), 200
