"""Asignaciones atómicas y notas independientes conservadas en el historial."""

import json

from flask import jsonify
from werkzeug.exceptions import BadRequest, NotFound

from app import db
from app.models.alert import Alert
from app.models.assignment import Assignment
from app.models.history import History
from app.models.user import User
from app.security import (
    active_profile_id,
    can_assign,
    current_profile,
    current_user,
    is_admin,
    is_supervisor,
    is_technician,
    may_view_alert,
)
from app.validation import integer
from app.validation import record_text as text_value


def locked_alert(alert_id):
    # Todas las escrituras de atención bloquean primero la misma fila de alerta.
    alert = Alert.query.filter_by(id=alert_id).populate_existing().with_for_update().first()
    if not alert:
        raise NotFound("Alerta no encontrada")
    return alert


def get_all_assignments(filters):
    query = Assignment.query
    actor = current_user()
    if is_technician(actor):
        requested_user = integer(filters.get("user_id"), "user_id", optional=True)
        if requested_user and requested_user != actor.id:
            return jsonify({"error": "Solo puedes consultar tus propias asignaciones"}), 403
        query = query.filter(Assignment.user_id == actor.id)
    elif not can_assign(actor):
        return jsonify({"error": "El perfil activo no puede consultar asignaciones"}), 403
    for field in ("alert_id", "user_id"):
        if filters.get(field):
            query = query.filter(getattr(Assignment, field) == integer(filters[field], field))
    if filters.get("active_only"):
        query = query.filter(Assignment.completed_at.is_(None))
    return jsonify(
        {"assignments": [a.to_dict() for a in query.order_by(Assignment.assigned_at.desc()).all()]}
    ), 200


def get_available_technicians():
    technicians = [
        u for u in User.query.order_by(User.full_name, User.id).all() if is_technician(u)
    ]
    return jsonify(
        {
            "technicians": [
                {
                    "id": user.id,
                    "full_name": user.full_name,
                    "active_assignments_count": user.active_assignments_count,
                }
                for user in technicians
            ]
        }
    ), 200


def create_assignment(data, current_user_id):
    alert = locked_alert(integer(data.get("alert_id"), "alert_id"))
    user = db.session.get(User, integer(data.get("user_id"), "user_id"))
    notes = text_value(data, "notes")
    if not is_technician(user):
        return jsonify({"error": "Selecciona un Técnico con cuenta y perfil activos"}), 400
    if alert.is_terminal:
        return jsonify({"error": "No se puede asignar una alerta cerrada o anulada"}), 409
    previous = alert.assignments.filter_by(completed_at=None).all()
    if len(previous) == 1 and previous[0].user_id == user.id:
        return jsonify({"error": "La alerta ya está asignada a este técnico"}), 409
    for assignment in previous:
        assignment.complete()
        _log(
            alert.id,
            current_user_id,
            "reassigned",
            f"Asignación #{assignment.id} de {assignment.user.full_name} finalizada por reasignación",
        )
    _transition_to_in_progress(alert, current_user_id)
    assignment = Assignment(alert_id=alert.id, user_id=user.id, assignment_type="manual")
    db.session.add(assignment)
    db.session.flush()
    if notes:
        _append_note(assignment, notes, current_user_id)
    _log(
        alert.id,
        current_user_id,
        "assigned",
        f"Asignada a {user.full_name}"
        + ("; se finalizaron las asignaciones anteriores" if previous else ""),
    )
    db.session.commit()
    return jsonify(
        {
            "message": f"Alerta #{alert.id} asignada a {user.full_name}",
            "assignment": assignment.to_dict(),
        }
    ), 201


def auto_assign(data, current_user_id):
    alert = locked_alert(integer(data.get("alert_id"), "alert_id"))
    if alert.is_terminal:
        return jsonify({"error": "No se puede asignar una alerta cerrada o anulada"}), 409
    if alert.assignments.filter_by(completed_at=None).first():
        return jsonify({"error": "La alerta ya tiene una asignación vigente"}), 409
    technicians = [u for u in User.query.order_by(User.id).all() if is_technician(u)]
    if not technicians:
        return jsonify({"error": "No hay Técnicos activos disponibles"}), 409
    selected = min(technicians, key=lambda u: (u.active_assignments_count, u.id))
    workload = selected.active_assignments_count
    _transition_to_in_progress(alert, current_user_id)
    assignment = Assignment(alert_id=alert.id, user_id=selected.id, assignment_type="auto")
    db.session.add(assignment)
    _log(
        alert.id,
        current_user_id,
        "assigned",
        f"Auto-asignada al técnico: {selected.full_name}. Carga previa: {workload} alertas.",
    )
    db.session.commit()
    return jsonify(
        {
            "message": f"Alerta #{alert.id} asignada a {selected.full_name}",
            "assignment": assignment.to_dict(),
            "technician": selected.to_dict(include_profile=False),
        }
    ), 201


def get_assignment_notes(assignment_id):
    assignment = db.get_or_404(Assignment, assignment_id)
    if not may_view_alert(assignment.alert, current_user()):
        return jsonify({"error": "No tienes acceso a las notas de este caso"}), 403
    notes, legacy_audits = [], []
    for entry in (
        assignment.alert.history.filter_by(action="note_added")
        .order_by(History.timestamp, History.id)
        .all()
    ):
        serialized = entry.to_dict()
        if (serialized["metadata"] or {}).get("kind") == "assignment_note":
            notes.append(serialized)
        else:
            legacy_audits.append(serialized)
    # Los textos anteriores no acreditan su autor ni su fecha de creación.
    # No se atribuyen al técnico ni se confunden con las notas nuevas.
    legacy_notes = [
        {"assignment_id": item.id, "detail": item.notes}
        for item in assignment.alert.assignments.order_by(
            Assignment.assigned_at, Assignment.id
        ).all()
        if item.notes
    ]
    return jsonify(
        {
            "alert_id": assignment.alert_id,
            "notes": notes,
            "legacy_notes": legacy_notes,
            "legacy_audits": legacy_audits,
            "can_add": _note_permission_error(assignment) is None,
        }
    ), 200


def add_assignment_note(assignment_id, data, current_user_id):
    assignment = db.get_or_404(Assignment, assignment_id)
    locked_alert(assignment.alert_id)
    db.session.refresh(assignment)
    error = _note_permission_error(assignment)
    if error:
        return error
    if set(data) - {"notes"}:
        raise BadRequest(
            "Envía únicamente el texto de la nota; autor, perfil y fecha los registra el servidor"
        )
    note = _append_note(assignment, text_value(data, "notes", required=True), current_user_id)
    db.session.commit()
    return jsonify(
        {"message": "Nota añadida; las notas anteriores se conservan", "note": note.to_dict()}
    ), 201


def _note_permission_error(assignment):
    actor = current_user()
    if not (
        is_admin(actor)
        or is_supervisor(actor)
        or (is_technician(actor) and assignment.user_id == actor.id)
    ):
        return jsonify(
            {"error": "Solo el técnico asignado, Supervisor o Administrador puede añadir notas"}
        ), 403
    if assignment.alert.is_terminal or assignment.completed_at is not None:
        return jsonify(
            {
                "error": "Solo se pueden añadir notas a una asignación vigente de una alerta pendiente"
            }
        ), 409
    latest = (
        assignment.alert.assignments.filter_by(completed_at=None)
        .order_by(Assignment.assigned_at.desc(), Assignment.id.desc())
        .first()
    )
    if not latest or latest.id != assignment.id:
        return jsonify(
            {"error": "Esta asignación ya no es la vigente; consulta la atención actual"}
        ), 409
    return None


def _append_note(assignment, content, user_id):
    actor = current_user()
    profile = current_profile(actor)
    category = (
        "technical"
        if is_technician(actor)
        else "coordination"
        if is_admin(actor) or is_supervisor(actor)
        else "assignment"
    )
    note = History(
        alert_id=assignment.alert_id,
        user_id=user_id,
        profile_id=active_profile_id(),
        action="note_added",
        detail=json.dumps(
            {
                "kind": "assignment_note",
                "assignment_id": assignment.id,
                "category": category,
                "text": content,
                "author": {"id": actor.id, "full_name": actor.full_name},
                "profile": {"id": profile.id, "name": profile.name},
            },
            ensure_ascii=False,
        ),
    )
    db.session.add(note)
    return note


def update_assignment(assignment_id, data, current_user_id):
    assignment = db.get_or_404(Assignment, assignment_id)
    locked_alert(assignment.alert_id)
    db.session.refresh(assignment)
    actor = current_user()
    if set(data) - {"notes", "complete", "solution"}:
        raise BadRequest(
            "Las notas existentes no se pueden editar ni eliminar; añade una nueva nota"
        )
    if "complete" in data and not isinstance(data["complete"], bool):
        return jsonify({"error": "complete debe ser true o false"}), 400
    if "complete" in data or "solution" in data or "notes" not in data:
        if not is_admin(actor) and not (is_technician(actor) and assignment.user_id == actor.id):
            return jsonify(
                {"error": "Solo el técnico asignado o un administrador puede cerrar esta atención"}
            ), 403
    # Conserva la repetición idempotente del cierre, pero nunca añade notas al repetirlo.
    if (
        data.get("complete")
        and "notes" not in data
        and assignment.completed_at is not None
        and assignment.alert.state.name == "Cerrado"
    ):
        text_value(data, "solution", required=True)
        return jsonify(
            {"message": "La atención ya estaba cerrada", "assignment": assignment.to_dict()}
        ), 200
    error = _note_permission_error(assignment)
    if error:
        return error
    notes = text_value(data, "notes", required=True) if "notes" in data else None
    if data.get("complete"):
        solution = text_value(data, "solution", required=True)
        from app.controllers.alert_controller import _change_state

        result = _change_state(assignment.alert, current_user_id, "Cerrado", solution)
        if result is not None:
            db.session.rollback()
            return result
    if notes:
        _append_note(assignment, notes, current_user_id)
    db.session.commit()
    message = "Atención y alerta cerradas" if data.get("complete") else "Asignación actualizada"
    return jsonify({"message": message, "assignment": assignment.to_dict()}), 200


def _transition_to_in_progress(alert, user_id):
    if alert.state.name == "Abierto":
        from app.controllers.alert_controller import _change_state

        result = _change_state(alert, user_id, "En Progreso", "Asignación de técnico")
        if result is not None:
            from werkzeug.exceptions import Conflict

            raise Conflict("No se pudo iniciar la atención; comprueba el estado En Progreso")


def _log(alert_id, user_id, action, detail):
    db.session.add(
        History(
            alert_id=alert_id,
            user_id=user_id,
            profile_id=active_profile_id(),
            action=action,
            detail=detail,
        )
    )
