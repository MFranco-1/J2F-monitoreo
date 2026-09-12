"""Asignaciones atómicas: una vigente por alerta, con técnicos habilitados."""
from flask import jsonify
from werkzeug.exceptions import NotFound
from app import db
from app.models.assignment import Assignment
from app.models.alert import Alert
from app.models.user import User
from app.models.history import History
from app.security import current_user, is_admin, is_operator, active_profile_id
from app.validation import integer, text_value


def locked_alert(alert_id):
    # Todas las escrituras de atención bloquean primero la misma fila de alerta.
    alert = Alert.query.filter_by(id=alert_id).populate_existing().with_for_update().first()
    if not alert:
        raise NotFound("Alerta no encontrada")
    return alert


def get_all_assignments(filters):
    query = Assignment.query
    for field in ("alert_id", "user_id"):
        if filters.get(field):
            query = query.filter(getattr(Assignment, field) == integer(filters[field], field))
    if filters.get("active_only"):
        query = query.filter(Assignment.completed_at.is_(None))
    return jsonify({"assignments": [a.to_dict() for a in query.order_by(Assignment.assigned_at.desc()).all()]}), 200


def create_assignment(data, current_user_id):
    alert = locked_alert(integer(data.get("alert_id"), "alert_id"))
    user = db.session.get(User, integer(data.get("user_id"), "user_id"))
    notes = text_value(data, "notes")
    if not is_operator(user):
        return jsonify({"error": "Selecciona un Técnico u Operador con cuenta y perfil activos"}), 400
    if alert.state.name == "Cerrado":
        return jsonify({"error": "No se puede asignar una alerta cerrada"}), 409
    previous = alert.assignments.filter_by(completed_at=None).all()
    if len(previous) == 1 and previous[0].user_id == user.id:
        return jsonify({"error": "La alerta ya está asignada a este operador"}), 409
    for assignment in previous:
        assignment.complete()
    _transition_to_in_progress(alert, current_user_id)
    assignment = Assignment(alert_id=alert.id, user_id=user.id, notes=notes, assignment_type="manual")
    db.session.add(assignment)
    _log(alert.id, current_user_id, "assigned", f"Asignada a {user.full_name}" +
         ("; se finalizaron las asignaciones anteriores" if previous else ""))
    db.session.commit()
    return jsonify({"message": f"Alerta #{alert.id} asignada a {user.full_name}",
                    "assignment": assignment.to_dict()}), 201


def auto_assign(data, current_user_id):
    alert = locked_alert(integer(data.get("alert_id"), "alert_id"))
    if alert.state.name == "Cerrado":
        return jsonify({"error": "No se puede asignar una alerta cerrada"}), 409
    if alert.assignments.filter_by(completed_at=None).first():
        return jsonify({"error": "La alerta ya tiene una asignación vigente"}), 409
    operators = [u for u in User.query.order_by(User.id).all() if is_operator(u)]
    if not operators:
        return jsonify({"error": "No hay Técnicos u Operadores activos disponibles"}), 409
    selected = min(operators, key=lambda u: (u.active_assignments_count, u.id))
    workload = selected.active_assignments_count
    _transition_to_in_progress(alert, current_user_id)
    assignment = Assignment(alert_id=alert.id, user_id=selected.id, assignment_type="auto",
                            notes=f"Asignación automática. Carga previa: {workload} alertas.")
    db.session.add(assignment)
    _log(alert.id, current_user_id, "assigned", f"Auto-asignada al operador: {selected.full_name}")
    db.session.commit()
    return jsonify({"message": f"Alerta #{alert.id} asignada a {selected.full_name}",
                    "assignment": assignment.to_dict(),
                    "operator": selected.to_dict(include_profile=False)}), 201


def update_assignment(assignment_id, data, current_user_id):
    assignment = Assignment.query.get_or_404(assignment_id)
    locked_alert(assignment.alert_id)
    db.session.refresh(assignment)
    actor = current_user()
    if not is_admin(actor) and not (is_operator(actor) and assignment.user_id == actor.id):
        return jsonify({"error": "Solo el operador asignado o un administrador puede modificar esta atención"}), 403
    if "complete" in data and not isinstance(data["complete"], bool):
        return jsonify({"error": "complete debe ser true o false"}), 400
    notes = text_value(data, "notes") if "notes" in data else assignment.notes
    if notes != assignment.notes:
        _log(assignment.alert_id, current_user_id, "note_added",
             f"Notas de asignación #{assignment.id}. Antes: {assignment.notes or '—'}. Ahora: {notes or '—'}")
        assignment.notes = notes
    if data.get("complete") and assignment.completed_at is None:
        assignment.complete()
        _log(assignment.alert_id, current_user_id, "updated", f"Asignación #{assignment.id} completada")
    db.session.commit()
    return jsonify({"message": "Asignación actualizada", "assignment": assignment.to_dict()}), 200


def _transition_to_in_progress(alert, user_id):
    if alert.state.name == "Abierto":
        from app.controllers.alert_controller import _change_state
        result = _change_state(alert, user_id, "En Progreso", "Asignación de operador")
        if result is not None:
            from werkzeug.exceptions import Conflict
            raise Conflict("No se pudo iniciar la atención; comprueba el estado En Progreso")


def _log(alert_id, user_id, action, detail):
    db.session.add(History(alert_id=alert_id, user_id=user_id,
                           profile_id=active_profile_id(), action=action, detail=detail))
