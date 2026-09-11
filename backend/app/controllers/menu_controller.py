"""CRUD y navegación de las opciones ya existentes, con jerarquía validada."""
from flask import jsonify
from werkzeug.exceptions import BadRequest
from app import db
from app.models.menu_option import MenuOption
from app.models.profile import Profile
from app.validation import text_value, integer, ids_list, user_state
from app.security import current_user, is_admin


def get_all_menu_options(filters):
    actor = current_user()
    options = MenuOption.query.order_by(MenuOption.order, MenuOption.id).all()
    if filters.get("navigation"):
        active = {o.id: o for o in options if o.state and o.state.name == "Activo"}
        keep = set()
        for option in active.values():
            if not is_admin(actor) and actor.profile_id not in [p.id for p in option.profiles]:
                continue
            chain, node = set(), option
            while node and node.id not in chain:
                chain.add(node.id)
                if node.parent_id is None:
                    keep.update(chain)
                    break
                node = active.get(node.parent_id)
        def tree(option):
            data = option.to_dict(include_children=False)
            data["children"] = [tree(child) for child in active.values()
                                if child.parent_id == option.id and child.id in keep]
            return data
        roots = [tree(o) for o in options if o.parent_id is None and o.id in keep]
        return jsonify({"menu_options": roots, "configured": bool(options)}), 200
    if not is_admin(actor):
        return jsonify({"error": "Esta operación requiere el perfil Administrador"}), 403
    if filters.get("parent_only"):
        options = [o for o in options if o.parent_id is None]
    return jsonify({"menu_options": [o.to_dict() for o in options]}), 200


def get_menu_option_by_id(option_id):
    return jsonify({"menu_option": MenuOption.query.get_or_404(option_id).to_dict()}), 200


def _parent(value, option_id=None):
    parent_id = integer(value, "parent_id", optional=True)
    if parent_id is None:
        return None
    parent = db.session.get(MenuOption, parent_id)
    if not parent:
        raise BadRequest("Menú padre no encontrado")
    visited = set()
    node = parent
    while node:
        if node.id == option_id or node.id in visited:
            raise BadRequest("La jerarquía de menús no puede contener ciclos")
        visited.add(node.id)
        node = node.parent
    return parent


def _profiles(value):
    ids = ids_list(value, "profile_ids")
    profiles = Profile.query.filter(Profile.id.in_(ids)).all()
    if len(profiles) != len(ids):
        raise BadRequest("Un perfil seleccionado no existe")
    return profiles


def create_menu_option(data, state_id):
    name = text_value(data, "name", required=True, limit=100)
    url = text_value(data, "url", limit=255)
    icon = text_value(data, "icon", limit=100)
    parent = _parent(data.get("parent_id"))
    state = user_state(state_id)
    order = integer(data.get("order", 0), "order", minimum=0)
    profiles = _profiles(data.get("profile_ids", []))
    option = MenuOption(name=name, url=url, icon=icon, parent=parent, state=state, order=order)
    option.profiles = profiles
    db.session.add(option)
    db.session.commit()
    return jsonify({"message": "Opción de menú creada", "menu_option": option.to_dict()}), 201


def update_menu_option(option_id, data):
    option = MenuOption.query.get_or_404(option_id)
    values = {}
    for field, limit in [("name", 100), ("url", 255), ("icon", 100)]:
        if field in data:
            values[field] = text_value(data, field, required=(field == "name"), limit=limit)
    parent = _parent(data["parent_id"], option.id) if "parent_id" in data else option.parent
    state = user_state(data["state_id"]) if "state_id" in data else option.state
    order = integer(data["order"], "order", minimum=0) if "order" in data else option.order
    profiles = _profiles(data["profile_ids"]) if "profile_ids" in data else option.profiles
    for field, value in values.items():
        setattr(option, field, value)
    option.parent, option.state, option.order, option.profiles = parent, state, order, profiles
    db.session.commit()
    return jsonify({"message": "Opción actualizada", "menu_option": option.to_dict()}), 200


def delete_menu_option(option_id):
    option = MenuOption.query.get_or_404(option_id)
    if option.children:
        return jsonify({"error": "No se puede eliminar una opción con sub-opciones"}), 409
    db.session.delete(option)
    db.session.commit()
    return jsonify({"message": "Opción eliminada"}), 200
