"""Adaptador REST. Las reglas y consultas están en database/03_funciones.sql."""
import csv
import io
import json
from flask import Blueprint, Response, abort, jsonify, request
from flask_jwt_extended import create_access_token, create_refresh_token, get_jwt, get_jwt_identity, jwt_required
from werkzeug.security import check_password_hash, generate_password_hash
from app.database import invoke

api = Blueprint("api", __name__)

def body():
    value = request.get_json(silent=True)
    if value is None and not request.content_length:
        return {}
    if not isinstance(value, dict):
        abort(400, "Envía un objeto JSON válido")
    return value

def context():
    return int(get_jwt_identity()), get_jwt().get("active_profile_id")

def operation(resource, action, record_id=None, data=None, filters=None):
    actor, profile = context()
    return invoke("j2f_api", resource, action, record_id, data or {}, filters or {}, actor, profile)

def revoked(payload):
    try:
        state = invoke("j2f_auth", "status", {"user_id": int(payload["sub"]), "profile_id": payload.get("active_profile_id")})
        user = state["user"]
        profile_id = payload.get("active_profile_id")
        return state["session_version"] != payload.get("session_version") or not user["state"]["is_active"] or (profile_id is not None and not any(p["id"] == profile_id for p in user["profiles"]))
    except (KeyError, ValueError, TypeError):
        return True

def tokens(result):
    claims = {"active_profile_id": result.pop("active_profile_id"), "session_version": result.pop("session_version")}
    identity = str(result["user"]["id"])
    result["access_token"] = create_access_token(identity, additional_claims=claims)
    if not result["requires_profile_selection"]:
        result["refresh_token"] = create_refresh_token(identity, additional_claims=claims)
    return result

@api.get("/catalogs")
def catalogs():
    return invoke("j2f_catalogs")

@api.post("/auth/login")
def login():
    data = body()
    if not isinstance(data.get("identifier"), str) or not isinstance(data.get("password"), str):
        abort(400, "Ingresa identificador y contraseña")
    user = invoke("j2f_auth", "lookup", {"identifier": data["identifier"].strip()})
    if not user or not check_password_hash(user["password_hash"], data["password"]):
        abort(401, "Credenciales inválidas")
    return tokens(invoke("j2f_auth", "login", {"user_id": user["id"]}))

@api.post("/auth/select-profile")
@jwt_required()
def select_profile():
    data = body()
    if type(data.get("profile_id")) is not int:
        abort(400, "Selecciona un perfil válido")
    return tokens(invoke("j2f_auth", "select", {"user_id": context()[0], "profile_id": data["profile_id"]}))

@api.post("/auth/logout")
@jwt_required(verify_type=False)
def logout():
    invoke("j2f_auth", "logout", {"user_id": context()[0]})
    return {"message": "Sesión finalizada"}

@api.post("/auth/refresh")
@jwt_required(refresh=True)
def refresh():
    claims = get_jwt()
    if claims.get("active_profile_id") is None:
        abort(403, "Selecciona un perfil")
    return {"access_token": create_access_token(get_jwt_identity(), additional_claims={k: claims[k] for k in ("active_profile_id", "session_version")})}

@api.get("/auth/me")
@jwt_required()
def me():
    actor, profile = context()
    return {"user": invoke("j2f_auth", "status", {"user_id": actor, "profile_id": profile})["user"]}

@api.get("/alerts/metrics")
@jwt_required()
def metrics():
    return operation("alerts", "metrics")

@api.get("/alerts/map/vehicles")
@jwt_required()
def map_vehicles():
    return operation("alerts", "map", filters=request.args.to_dict())

@api.post("/alerts/map/events")
@jwt_required()
def event():
    data = body()
    validate_coordinates(data.get("latitude"), data.get("longitude"))
    result = operation("alerts", "event", data=data)
    return result, 201 if result["created"] else 200

@api.get("/alerts/map/fuel-stations")
@jwt_required()
def stations():
    from app.map_services import fuel_stations
    return fuel_stations(operation)

@api.get("/alerts/map/route")
@jwt_required()
def street_route():
    from app.map_services import street_route
    return street_route(operation)

@api.post("/alerts/<int:record_id>/cancel")
@jwt_required()
def cancel(record_id):
    return operation("alerts", "cancel", record_id, body())

@api.post("/alerts/<int:record_id>/fuel-actions")
@jwt_required()
def fuel(record_id):
    return operation("alerts", "fuel", record_id, body())

@api.get("/assignments/technicians")
@jwt_required()
def technicians():
    return operation("assignments", "technicians")

@api.post("/assignments/auto-assign")
@jwt_required()
def auto_assign():
    return operation("assignments", "auto-assign", data=body()), 201

@api.route("/assignments/<int:record_id>/notes", methods=["GET", "POST"])
@jwt_required()
def notes(record_id):
    return operation("assignments", "notes" if request.method == "GET" else "add-note", record_id, body() if request.method == "POST" else {})

@api.post("/reports/<int:record_id>/generate")
@jwt_required()
def generate(record_id):
    return operation("reports", "generate", record_id)

@api.get("/reports/<int:record_id>/export")
@jwt_required()
def export(record_id):
    report = operation("reports", "get", record_id)["report"]
    if not report.get("result_json"):
        abort(409, "Genera el reporte antes de exportarlo")
    result = json.loads(report["result_json"])
    fmt = request.args.get("format", "csv")
    if fmt == "json":
        text = json.dumps(result, ensure_ascii=False, indent=2)
        mime = "application/json"
    elif fmt == "csv":
        stream = io.StringIO()
        writer = csv.writer(stream)
        def safe(value):
            value = str(value)
            return "'" + value if value.lstrip().startswith(("=", "+", "-", "@")) else value
        for key, value in result.items():
            writer.writerow([safe(key), safe(json.dumps(value, ensure_ascii=False) if isinstance(value, (dict, list)) else value)])
        text, mime = "\ufeff" + stream.getvalue(), "text/csv"
    else:
        abort(400, "Elige CSV o JSON")
    return Response(text, mimetype=mime, headers={"Content-Disposition": f'attachment; filename="reporte_{record_id}.{fmt}"'})

@api.get("/reports/history")
@jwt_required()
def history():
    return operation("history", "list", filters=request.args.to_dict())

@api.get("/reports/history/alerts/<int:record_id>")
@jwt_required()
def alert_history(record_id):
    operation("alerts", "get", record_id)
    return operation("history", "detail", record_id)

@api.route("/master-data/<resource>/", defaults={"record_id": None}, methods=["GET", "POST"])
@api.route("/master-data/<resource>/<int:record_id>", methods=["GET", "PUT", "DELETE"])
@api.route("/<resource>/", defaults={"record_id": None}, methods=["GET", "POST"])
@api.route("/<resource>/<int:record_id>", methods=["GET", "PUT", "DELETE"])
@jwt_required()
def records(resource, record_id):
    action = {"GET": "list" if record_id is None else "get", "POST": "create", "PUT": "update", "DELETE": "delete"}[request.method]
    data = body() if request.method in {"POST", "PUT"} else {}
    # Hashing sigue en Python; nunca se almacena o devuelve una contraseña en claro.
    if resource == "users" and action in {"create", "update"}:
        if action == "create" or data.get("password"):
            password = data.pop("password", None)
            if not isinstance(password, str) or len(password) < 8:
                abort(400, "La contraseña requiere al menos 8 caracteres")
            data["password_hash"] = generate_password_hash(password)
        else:
            data.pop("password", None)
            data.pop("password_hash", None)
    if resource == "clients" and data.get("phone"):
        import phonenumbers
        region = data.pop("phone_country", None)
        if region is None:
            region = invoke("j2f_param", "default_phone_country")
        try:
            phone = phonenumbers.parse(data["phone"], region)
            if not phonenumbers.is_valid_number(phone):
                raise ValueError()
            data["phone"] = phonenumbers.format_number(phone, phonenumbers.PhoneNumberFormat.E164)
        except (ValueError, phonenumbers.NumberParseException):
            abort(400, "Teléfono inválido para el país seleccionado")
    result = operation(resource, action, record_id, data, request.args.to_dict())
    return result, 201 if action == "create" else 200

def validate_coordinates(latitude, longitude):
    import math
    try:
        lat, lng = float(latitude), float(longitude)
        if not math.isfinite(lat) or not math.isfinite(lng) or not -90 <= lat <= 90 or not -180 <= lng <= 180:
            raise ValueError()
        return lat, lng
    except (ValueError, TypeError):
        abort(400, "Coordenadas inválidas")
