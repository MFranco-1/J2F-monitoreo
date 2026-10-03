"""Validación de las entradas de los CRUD existentes."""
import re
import math
import unicodedata
import phonenumbers
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
    value = unicodedata.normalize("NFC", value)
    if any(unicodedata.category(char) in {"Cc", "Cf"} and char not in "\n\r\t" for char in value):
        raise BadRequest(f"{field} contiene caracteres de control no permitidos")
    if required and not value:
        raise BadRequest(f"Campo requerido: {field}")
    if limit and len(value) > limit:
        raise BadRequest(f"{field} admite como máximo {limit} caracteres")
    return value


# Reglas de contenido para escrituras, no para identificadores de sesión ni enums.
# Los campos opcionales vacíos siguen siendo opcionales.
TEXT_RULES = {
    "business_name": ("Razón social", 3, 2),
    "contact_name": ("Contacto", 3, 2),
    "full_name": ("Nombre completo", 3, 2),
    "name": ("Nombre", 3, 2),
    "address": ("Dirección", 5, 2),
    "brand": ("Marca", 2, 1),
    "model": ("Modelo", 2, 0),
    "color": ("Color", 3, 2),
    "vehicle_type": ("Tipo de vehículo", 3, 2),
    "provider": ("Proveedor", 3, 2),
    "title": ("Título", 3, 2),
    "description": ("Descripción", 5, 2),
    "expected_action": ("Acción esperada", 5, 2),
    "service_type": ("Tipo de servicio", 3, 2),
    "location": ("Ubicación", 3, 2),
    "source": ("Origen", 3, 2),
    "notes": ("Observación / solución", 5, 2),
    "solution": ("Solución", 5, 2),
    "observation": ("Observación de abastecimiento", 5, 2),
    "reason": ("Motivo de anulación", 5, 2),
}


def record_text(data, field, *, required=False, limit=None):
    label, minimum, letters = TEXT_RULES.get(field, (field, 0, 0))
    try:
        value = text_value(data, field, required=required,
                           limit=limit if limit is not None else 2000)
    except BadRequest as error:
        raise BadRequest(error.description.replace(field, label)) from None
    if value and field in TEXT_RULES:
        significant = "".join(char.casefold() for char in value if char.isalnum())
        if (len(value) < minimum or len(significant) < 2
                or sum(char.isalpha() for char in value) < letters
                or len(set(significant)) < 2):
            raise BadRequest(f"{label}: ingresa un dato válido de al menos {minimum} caracteres, no una letra o símbolos aislados")
        if field in {"contact_name", "full_name"} and any(
                not (char.isalpha() or char in " .'-") for char in value):
            raise BadRequest(f"{label} solo admite letras, espacios, puntos, apóstrofes y guiones")
        if field == "address" and any(
                not (char.isalpha() or char in "0123456789 .,-/#") for char in value):
            raise BadRequest("Dirección: solo admite letras (incluidas tildes y ñ), números, espacios y . , - / #")
        if field == "business_name" and re.sub(r"[^a-z]", "", value.lower()) in {"sa", "sac", "saa", "sacs", "srl", "eirl"}:
            raise BadRequest("Razón social: ingresa el nombre de la empresa, no solo su forma legal (S.A.C., S.A., etc.)")
    return value


def normalize_client_name(value):
    """Formato solicitado: primera letra mayúscula y el resto en minúscula."""
    if not value:
        return value
    value = re.sub(r"\s+", " ", value.strip()).lower()
    for index, char in enumerate(value):
        if char.isalpha():
            return value[:index] + char.upper() + value[index + 1:]
    return value


def validate_client_phone(value, country=None):
    """Valida el plan telefónico del país, no la existencia ni el titular."""
    if country is not None and (not isinstance(country, str)
            or country not in phonenumbers.SUPPORTED_REGIONS):
        raise BadRequest("Teléfono: selecciona un país válido")
    if not value:
        return value
    if not isinstance(value, str) or not re.fullmatch(r"\+?[0-9]{7,15}", value):
        raise BadRequest("Teléfono: ingresa solo dígitos, sin letras, espacios ni símbolos; el prefijo se elige por país")
    try:
        if country or value.startswith("+"):
            parsed = phonenumbers.parse(value, country)
        else:
            # Compatibilidad con clientes de API anteriores: números nacionales
            # peruanos o un prefijo internacional ya incluido, nunca reescritura masiva.
            parsed = phonenumbers.parse(value, "PE")
            if not phonenumbers.is_valid_number_for_region(parsed, "PE"):
                parsed = phonenumbers.parse("+" + value, None)
        if not phonenumbers.is_valid_number(parsed) or (country and
                not phonenumbers.is_valid_number_for_region(parsed, country)):
            raise BadRequest("Teléfono: el número no es válido para el país seleccionado; revisa la longitud y el código de área")
        canonical = phonenumbers.format_number(parsed, phonenumbers.PhoneNumberFormat.E164)
        if len(canonical) > 16:
            raise BadRequest("Teléfono: máximo 15 dígitos incluyendo el prefijo internacional")
        return canonical
    except phonenumbers.NumberParseException:
        raise BadRequest("Teléfono: ingresa un número válido para el país seleccionado") from None


def client_phone_country(value):
    """País derivado del número guardado, sin añadir columnas ni alterar datos."""
    if not value:
        return None
    try:
        canonical = validate_client_phone(value)
        return phonenumbers.region_code_for_number(phonenumbers.parse(canonical, None))
    except BadRequest:
        return None  # Los registros antiguos siguen siendo consultables.


def validate_document(document_type, number):
    document_type = document_type.upper()
    patterns = {"RUC": (r"[0-9]{11}", "El RUC debe contener exactamente 11 dígitos"),
                "DNI": (r"[0-9]{8}", "El DNI debe contener exactamente 8 dígitos"),
                "CE": (r"[0-9]{9,12}", "El carné de extranjería debe contener de 9 a 12 dígitos"),
                "PASAPORTE": (r"[A-Z0-9]{6,12}", "El pasaporte debe contener de 6 a 12 letras o dígitos")}
    if document_type not in patterns:
        raise BadRequest("Selecciona un tipo de documento válido: RUC, DNI, CE o PASAPORTE")
    pattern, message = patterns[document_type]
    number = number.upper()
    if not re.fullmatch(pattern, number):
        raise BadRequest(message)
    return document_type, number


def validate_phone(value, *, sim=False):
    if value and not re.fullmatch(r"[0-9]{7,22}" if sim else r"[0-9]{7,15}", value):
        raise BadRequest("SIM: ingresa de 7 a 22 dígitos, sin letras ni símbolos" if sim else
                         "Teléfono: ingresa de 7 a 15 dígitos, sin letras, espacios ni símbolos")
    return value


def validate_ruc(value):
    if not isinstance(value, str) or not re.fullmatch(r"[0-9]{11}", value):
        raise BadRequest("El RUC debe contener exactamente 11 dígitos")
    if value[:2] not in {"10", "15", "16", "17", "20"}:
        raise BadRequest("El prefijo del RUC no es válido")
    weighted_sum = sum(int(digit) * weight for digit, weight in
                       zip(value[:10], (5, 4, 3, 2, 7, 6, 5, 4, 3, 2)))
    digit = (11 - weighted_sum % 11) % 10
    if int(value[-1]) != digit:
        raise BadRequest("El dígito verificador del RUC no es válido; comprueba el número")
    return value


def validate_plate(value):
    value = value.upper()
    if (not re.fullmatch(r"[A-Z0-9]{2,4}-?[A-Z0-9]{2,4}", value)
            or not any(char.isalpha() for char in value)
            or not any(char.isdigit() for char in value)):
        raise BadRequest("Placa inválida: usa de 4 a 8 letras y dígitos, con un guion opcional (ej. ABC-123)")
    return value


def validate_imei(value):
    if not re.fullmatch(r"[0-9]{15}", value):
        raise BadRequest("El IMEI debe contener exactamente 15 dígitos")
    return value


def validate_code(value, *, serial=False):
    value = value if serial else value.upper()
    pattern = r"[A-Za-z0-9][A-Za-z0-9._/-]{2,79}" if serial else r"[A-Z][A-Z0-9]*(?:_[A-Z0-9]+)*"
    if value and (not re.fullmatch(pattern, value) or (not serial and len(value) < 2)):
        raise BadRequest("Número de serie inválido: mínimo 3 caracteres alfanuméricos; admite . _ / -" if serial else
                         "Código inválido: mínimo 2 caracteres; usa letras, dígitos y guiones bajos, comenzando por una letra")
    return value


def validate_password(value):
    if not isinstance(value, str) or not value.strip() or not 8 <= len(value) <= 128:
        raise BadRequest("La contraseña debe contener entre 8 y 128 caracteres y no solo espacios")
    return value


def validate_menu_url(value):
    if value and not re.fullmatch(r"/(?:[A-Za-z0-9_-]+(?:/[A-Za-z0-9_-]+)*)?", value):
        raise BadRequest("La ruta del menú debe ser interna, por ejemplo /alerts; no admite espacios ni URLs externas")
    return value


def validate_icon(value):
    if value and not re.fullmatch(r"[A-Za-z][A-Za-z0-9_-]{1,99}", value):
        raise BadRequest("Ícono inválido: usa un identificador de al menos 2 letras, dígitos o guiones")
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


def number_value(value, label, *, minimum=None, maximum=None):
    if isinstance(value, bool) or not isinstance(value, (str, int, float)):
        raise BadRequest(f"{label} debe ser un número válido")
    try:
        result = float(value)
    except (ValueError, OverflowError):
        raise BadRequest(f"{label} debe ser un número válido") from None
    if (not math.isfinite(result) or (minimum is not None and result < minimum)
            or (maximum is not None and result > maximum)):
        raise BadRequest(f"{label} está fuera del rango permitido")
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
    if (len(value) > 150 or not re.fullmatch(
            r"[A-Za-z0-9!#$%&'*+/=?^_`{|}~.-]+@(?:[A-Za-z0-9](?:[A-Za-z0-9-]{0,61}[A-Za-z0-9])?\.)+[A-Za-z]{2,63}", value)
            or value.startswith(".") or ".." in value or ".@" in value
            or len(value.split("@")[0]) > 64):
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
