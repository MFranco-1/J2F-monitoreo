"""CRUD de perfiles; conserva el perfil administrativo y sus relaciones."""
from flask import jsonify
from app import db
from app.models.profile import Profile
from app.models.menu_option import MenuOption
from app.models.state import State
from app.validation import record_text as text_value, user_state, ids_list
from app.security import role_name, active_admin_count, has_active_role
from app.controllers.auth_controller import invalidate_sessions


def _assigned_users(profile):
    """Incluye la tabla multiperfil y la relación heredada durante la migración."""
    users = {user.id: user for user in profile.users.all()}
    users.update({user.id: user for user in profile.legacy_users.all()})
    return list(users.values())


def get_all_profiles():
    states = State.query.filter_by(type="user").filter(State.name.in_(["Activo", "Inactivo"])).all()
    return jsonify({"profiles": [p.to_dict() for p in Profile.query.order_by(Profile.name)],
                    "states": [s.to_dict() for s in states]}), 200


def get_profile_by_id(profile_id):
    return jsonify({"profile": Profile.query.get_or_404(profile_id).to_dict(include_menus=True)}), 200


def _menus(value):
    from werkzeug.exceptions import BadRequest
    ids = ids_list(value, "menu_option_ids")
    menus = MenuOption.query.filter(MenuOption.id.in_(ids)).all()
    if len(menus) != len(ids):
        raise BadRequest("Una opción de menú no existe")
    return menus


def _duplicate(name, excluded_id=None):
    return any(p.id != excluded_id and role_name(p.name) == role_name(name) for p in Profile.query.all())


def create_profile(data):
    name = text_value(data, "name", required=True, limit=100)
    description = text_value(data, "description", limit=255)
    state = user_state(data.get("state_id"))
    if _duplicate(name):
        return jsonify({"error": "Ya existe un perfil con ese nombre"}), 409
    profile = Profile(name=name, description=description, state=state)
    if "menu_option_ids" in data:
        profile.menu_options = _menus(data["menu_option_ids"])
    db.session.add(profile)
    db.session.commit()
    return jsonify({"message": "Perfil creado", "profile": profile.to_dict()}), 201


def update_profile(profile_id, data):
    profile = Profile.query.get_or_404(profile_id)
    name = text_value(data, "name", required=True, limit=100) if "name" in data else profile.name
    state = user_state(data["state_id"]) if "state_id" in data else profile.state
    description = text_value(data, "description", limit=255) if "description" in data else profile.description
    if _duplicate(name, profile.id):
        return jsonify({"error": "Nombre de perfil ya en uso"}), 409
    loses_current_role = role_name(name) != role_name(profile.name) or state.name != "Activo"
    if (role_name(profile.name) == "administrador" and loses_current_role
            and active_admin_count(excluded_profile_id=profile.id) == 0):
        return jsonify({"error": "El sistema debe conservar al menos un Administrador activo"}), 409
    if role_name(profile.name) == "tecnico" and loses_current_role:
        for user in _assigned_users(profile):
            if user.active_assignments_count and not has_active_role(
                    user, "tecnico", excluded_profile_id=profile.id):
                return jsonify({"error": "Reasigna primero las atenciones vigentes de los Técnicos"}), 409
    if state.name != "Activo" and profile.state.name == "Activo":
        for user in _assigned_users(profile):
            if not any(other.id != profile.id and other.state and other.state.name == "Activo"
                       for other in user.profiles):
                return jsonify({"error": "El perfil no puede desactivarse: dejaría usuarios sin perfil activo"}), 409
    access_changed = name != profile.name or state.id != profile.state_id
    if "menu_option_ids" in data:
        previous_ids = {menu.id for menu in profile.menu_options}
        profile.menu_options = _menus(data["menu_option_ids"])
        access_changed = access_changed or previous_ids != {menu.id for menu in profile.menu_options}
    if access_changed:
        for user in _assigned_users(profile):
            invalidate_sessions(user)
    profile.name, profile.state, profile.description = name, state, description
    db.session.commit()
    return jsonify({"message": "Perfil actualizado", "profile": profile.to_dict()}), 200


def delete_profile(profile_id):
    profile = Profile.query.get_or_404(profile_id)
    if (role_name(profile.name) == "administrador"
            and active_admin_count(excluded_profile_id=profile.id) == 0):
        return jsonify({"error": "El sistema debe conservar al menos un Administrador activo"}), 409
    if _assigned_users(profile):
        return jsonify({"error": "No se puede eliminar un perfil con usuarios asignados"}), 409
    db.session.delete(profile)
    db.session.commit()
    return jsonify({"message": "Perfil eliminado"}), 200
