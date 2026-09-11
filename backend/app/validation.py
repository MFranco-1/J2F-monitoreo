"""Validación de las entradas de los CRUD existentes."""
import re
from datetime import datetime, timedelta
from werkzeug.exceptions import BadRequest
from app.datetime_utils import as_utc_naive


def text_value(data, field, *, required=False, limit=None):
    value = data.get(field)
    if value is None:
        if required:
            raise BadRequest(f"Campo requerido: {field}")
        return None
    if not isinstance(value, str):
        raise BadRequest(f"{field} debe ser texto")
    value = value.strip()
    if required and not value:
        raise BadRequest(f"Campo requerido: {field}")
    if limit and len(value) > limit:
        raise BadRequest(f"{field} admite como máximo {limit} caracteres")
    return value


def integer(value, field, *, optional=False, minimum=1, maximum=None):
    if optional and value is None:
        return None
    if isinstance(value, bool) or not isinstance(value, (str, int)):
        raise BadRequest(f"{field} debe ser un número entero")
    try:
        result = int(value)
    except (TypeError, ValueError):
        raise BadRequest(f"{field} debe ser un número entero") from None
    if result < minimum or (maximum is not None and result > maximum):
        raise BadRequest(f"{field} está fuera del rango permitido")
    return result


def ids_list(value, field):
    if not isinstance(value, list):
        raise BadRequest(f"{field} debe ser una lista")
    return list(dict.fromkeys(integer(item, field) for item in value))


def user_state(value):
    from app import db
    from app.models.state import State
    state = db.session.get(State, integer(value, "state_id"))
    if not state or state.type != "user" or state.name not in {"Activo", "Inactivo"}:
        raise BadRequest("Estado de usuario inválido")
    return state


def profile_value(value):
    from app import db
    from app.models.profile import Profile
    profile_id = integer(value, "profile_id", optional=True)
    if profile_id is None:
        return None
    profile = db.session.get(Profile, profile_id)
    if not profile:
        raise BadRequest("Perfil no encontrado")
    return profile


def validate_dni(value):
    if not re.fullmatch(r"[0-9]{8}", value):
        raise BadRequest("El DNI debe contener 8 dígitos")
    return value


def validate_email(value):
    if not re.fullmatch(r"[^\s@]+@[^\s@]+\.[^\s@]+", value):
        raise BadRequest("Correo electrónico inválido")
    return value.casefold()


def priority_value(value):
    if value not in ("critical", "high", "medium", "low"):
        raise BadRequest("Prioridad inválida")
    return value


def date_value(value, field, *, end_of_day=False):
    if value is None or value == "":
        return None
    if not isinstance(value, str):
        raise BadRequest(f"{field} debe ser una fecha ISO válida")
    try:
        result = as_utc_naive(datetime.fromisoformat(value.replace("Z", "+00:00")))
        if end_of_day and re.fullmatch(r"\d{4}-\d{2}-\d{2}", value):
            result += timedelta(days=1, microseconds=-1)
        return result
    except (ValueError, OverflowError):
        raise BadRequest(f"{field} debe ser una fecha ISO válida") from None


def date_range(start, end):
    if start is not None and end is not None and start > end:
        raise BadRequest("La fecha inicial no puede ser posterior a la fecha final")
