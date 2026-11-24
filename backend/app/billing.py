"""Facturación de planes. Cada invoke confirma y libera su conexión antes de llamar a Laravel."""
import json
import re
from datetime import datetime, timezone
from decimal import Decimal, InvalidOperation

from flask import Blueprint, Response, abort, request
from flask_jwt_extended import jwt_required
from app.api import body, context
from psycopg2.errors import SerializationFailure
from app.database import call_routine, connection, invoke
from app.fact_api import FactAPI, ProviderError

billing = Blueprint("billing", __name__)


def db(action, **data):
    routine = "j2f_service" if action in ("preview", "reserve", "history") else "j2f_billing"
    return invoke(routine, action, data, *context())


def month(value):
    if not isinstance(value, str) or not re.fullmatch(r"[1-9][0-9]{3}-(0[1-9]|1[0-2])", value):
        abort(400, "Selecciona un período válido.")
    return value + "-01"


def client_id(value):
    if not re.fullmatch("[1-9][0-9]{0,8}", str(value)):
        abort(400, "Selecciona un cliente.")
    return int(value)


def view(inv):
    return {k: v for k, v in inv.items() if k not in ("issuer", "version")}


def mark(inv, status, **fields):
    return db("result", id=inv["id"], version=inv["version"], status=status, **fields)


def record(inv, doc, *, after_send=False, notice=None):
    try:
        matches = (
            int(doc["id"]) > 0 and (inv["external_id"] is None or inv["external_id"] == int(doc["id"]))
            and doc["datos_adicionales"]["j2f_reference"] == inv["reference"]
            and int(doc["company_id"]) == inv["issuer"]["company_id"]
            and int(doc["branch_id"]) == inv["issuer"]["branch_id"] and doc["serie"] == inv["issuer"]["serie"]
            and doc["moneda"] == "PEN" and doc["client"]["numero_documento"] == inv["recipient"]["numero_documento"]
            and Decimal(str(doc["mto_imp_venta"])) == Decimal(str(inv["total"]))
        )
    except (KeyError, TypeError, ValueError, InvalidOperation):
        matches = False
    if not matches:
        return mark(inv, "mismatch", message="Los datos del comprobante externo no coinciden. Requiere revisión.")
    state = doc.get("estado_sunat")
    cdr = doc.get("respuesta_sunat") or {}
    if isinstance(cdr, str):
        try:
            cdr = json.loads(cdr)
        except ValueError:
            cdr = {}
    cdr = cdr if isinstance(cdr, dict) else {}
    if state == "ACEPTADO" and str(cdr.get("code")) == "0":
        status = "accepted"
    elif state == "RECHAZADO":
        status = "rejected"
    elif state in (None, "PENDIENTE") and not after_send:
        status = "created"
    else:
        status = "send_unknown"
    msg = cdr.get("description") or cdr.get("message") or notice
    return mark(inv, status, external_id=int(doc["id"]), number=doc.get("numero_completo"),
                sunat_status=state, message=str(msg)[:500] if msg else None)


@billing.get("/catalog")
@jwt_required()
def catalog():
    return invoke("j2f_billing_catalog", *context())


@billing.put("/plans/<int:vehicle>")
@jwt_required()
def plan(vehicle):
    data = body()
    if data.get("plan") not in ("monthly", "annual") or type(data.get("equipment_paid")) is not bool:
        abort(400, "Selecciona el plan y confirma si el equipo ya se facturó.")
    return db("plan", vehicle_id=vehicle, plan=data["plan"], service_start=data.get("service_start"),
              first_period=month(data.get("first_period")), equipment_paid=data["equipment_paid"])


def service_args(data, concepts):
    args = dict(client_id=client_id(data.get("client")), period=month(data.get("period")))
    if "vehicle" in data:
        args["vehicle_id"] = client_id(data["vehicle"])
    if concepts is not None:
        if ("vehicle_id" not in args or not isinstance(concepts, list)
                or not concepts or not all(isinstance(c, str) for c in concepts)):
            abort(400, "Selecciona los servicios a cobrar.")
        args["concepts"] = concepts
    return args


def new_contract(data):
    start = data.get("start")
    if data.get("plan") not in ("annual", "monthly") or not isinstance(start, str):
        abort(400, "Selecciona el plan y la fecha de inicio.")
    try:
        parsed = datetime.strptime(start, "%Y-%m-%d").date()
    except ValueError:
        abort(400, "La fecha de inicio no es válida.")
    return dict(plan=data["plan"], service_start=parsed.isoformat(),
                first_period=parsed.replace(day=1).isoformat(), equipment_paid=False)


def sale(action, data, **fields):
    contract = new_contract(data)
    bulk = "vehicles" in data
    requested = data["vehicles"] if bulk else [data.get("vehicle")]
    if not isinstance(requested, list) or not requested:
        abort(400, "Selecciona al menos una placa.")
    vehicles = sorted({client_id(value) for value in requested})
    args = dict(client_id=client_id(data.get("client")), period=contract["first_period"], **fields)
    if bulk:
        args.update(vehicles=vehicles, start=contract["service_start"])
    else:
        args["vehicle_id"] = vehicles[0]
    actor = context()
    try:
        with connection() as conn, conn.cursor() as cursor:
            cursor.execute("SET TRANSACTION ISOLATION LEVEL SERIALIZABLE")
            catalog = call_routine(cursor, "j2f_billing", "catalog", {}, *actor)
            units = {v["id"]: v for v in catalog["vehicles"] if v["client_id"] == args["client_id"]}
            for vehicle in vehicles:
                if vehicle not in units:
                    abort(400, "Hay una placa que no pertenece al cliente.")
                existing = units[vehicle]["contract"]
                if existing:
                    if not bulk:
                        abort(409, "El vehículo ya tiene un plan.")
                else:
                    call_routine(cursor, "j2f_billing", "plan", dict(vehicle_id=vehicle, **contract), *actor)
            summary = call_routine(cursor, "j2f_service", action, args, *actor)
            # La cotización usa las mismas tarifas que la venta, sin dejar un contrato provisional.
            if action == "preview":
                conn.rollback()
            else:
                conn.commit()
            return summary
    except SerializationFailure:
        abort(409, "Otro usuario actualizó el vehículo. Actualiza la página para ver su plan vigente.")


@billing.post("/sales/preview")
@jwt_required()
def sale_preview():
    draft = sale("preview", body())
    draft["missing"].extend(FactAPI().missing)
    return view(draft)


@billing.post("/sales")
@jwt_required()
def sell_plan():
    data = body()
    sale("preview", data)
    api = provider()
    inv = sale("reserve", data, issuer=api.issuer, signature=data.get("signature"))
    return create_document(inv, api)


@billing.get("/invoices")
@jwt_required()
def history():
    filters = {}
    if request.args.get("client"):
        filters["client_id"] = client_id(request.args["client"])
    if "before" in request.args:
        cursor = request.args.get("before", type=int)
        if cursor is None or not 0 < cursor <= 2147483647:
            abort(400, "La página solicitada no es válida.")
        filters["before"] = cursor
    for key in ("from", "to"):
        value = request.args.get(key)
        if value:
            try:
                filters[key] = datetime.strptime(value, "%Y-%m-%d").date().isoformat()
            except ValueError:
                abort(400, "La fecha de emisión no es válida.")
    if "from" in filters and "to" in filters and filters["from"] > filters["to"]:
        abort(400, "La fecha final debe ser igual o posterior a la inicial.")
    return db("history", **filters)


@billing.get("/invoices/<int:iid>")
@jwt_required()
def detail(iid):
    return view(db("get", id=iid))


@billing.get("/preview")
@jwt_required()
def preview():
    data = db("preview", **service_args(request.args, request.args.getlist("concept") or None))
    if "id" not in data:
        data["missing"].extend(FactAPI().missing)
    return view(data)


def provider(inv=None):
    api = FactAPI()
    if inv and inv["issuer"] != api.issuer:
        abort(409, "La configuración del emisor cambió respecto a la factura.")
    try:
        api.check_beta()
    except ProviderError as error:
        abort(503, str(error))
    return api


@billing.post("/invoices")
@jwt_required()
def issue():
    data = body()
    args = service_args(data, data.get("concepts"))
    current = db("preview", **args)
    if current.get("id") and current["status"] != "reserved":
        return view(current)
    api = provider(current if current.get("id") else None)
    inv = db("reserve", **args, issuer=api.issuer, signature=data.get("signature"))
    if inv["status"] != "reserved":
        return view(inv)
    return create_document(inv, api)


@billing.post("/invoices/<int:iid>/create")
@jwt_required()
def retry_creation(iid):
    inv = db("get", id=iid)
    if inv["status"] != "reserved":
        abort(409, "Consulta el estado de la factura.")
    return create_document(inv, provider(inv))


def create_document(inv, api):
    inv = db("claim_create", id=inv["id"], version=inv["version"])
    try:
        doc = api.create(inv)
    except ProviderError as error:
        # Errores de validación/autenticación ocurren antes de InvoiceController::store.
        status = "reserved" if error.code in (401, 403, 422) else "uncertain"
        return view(mark(inv, status, message=str(error)))
    return view(record(inv, doc)), 201


@billing.get("/invoices/<int:iid>/pdf")
@jwt_required()
def invoice_pdf(iid):
    inv = db("get", id=iid)
    if not inv["external_id"] or inv["status"] == "mismatch":
        abort(409, "El PDF estará disponible cuando se cree la factura.")
    api = provider(inv)
    try:
        content = api.invoice_pdf(inv)
    except ProviderError as error:
        abort(502, str(error))
    return Response(content, mimetype="application/pdf", headers={
        "Content-Disposition": f'inline; filename="factura-{iid}.pdf"',
    })


@billing.get("/invoices/<int:iid>/xml")
@jwt_required()
def invoice_xml(iid):
    inv = db("get", id=iid)
    if not inv["external_id"] or inv["status"] == "mismatch":
        abort(409, "El XML todavía no está disponible.")
    api = provider(inv)
    try:
        content = api.invoice_xml(inv)
    except ProviderError as error:
        abort(404 if error.code == 404 else 502, str(error))
    return Response(content, mimetype="application/xml", headers={
        "Content-Disposition": f'attachment; filename="factura-{iid}.xml"',
    })


@billing.post("/invoices/<int:iid>/send")
@jwt_required()
def send(iid):
    inv = db("get", id=iid)
    if inv["status"] not in ("created", "rejected"):
        abort(409, "Consulta el estado antes de enviar.")
    api = provider(inv)
    if not api.signing_ready:
        abort(409, "Configura el certificado PEM privado y las credenciales SOL beta en el emisor antes de enviar.")
    inv = db("claim_send", id=iid, version=inv["version"])
    try:
        doc = api.send(inv)
    except ProviderError as error:
        try:
            doc = api.read(inv)
        except ProviderError:
            return view(mark(inv, "send_unknown", message=str(error)))
        if doc.get("estado_sunat") == "PENDIENTE" and error.code in (400, 401, 403, 422, 500):
            return view(record(inv, doc, notice=f"{error} La factura sigue pendiente. Puedes reintentar el envío."))
    return view(record(inv, doc, after_send=True))


@billing.post("/invoices/<int:iid>/consult")
@jwt_required()
def consult(iid):
    inv = db("get", id=iid)
    if inv["status"] in ("accepted", "mismatch", "reserved"):
        return view(inv)
    if inv["status"] in ("creating", "sending"):
        changed = datetime.fromisoformat(inv["updated_at"])
        if (datetime.now(timezone.utc) - changed).total_seconds() < 60:
            abort(409, "La operación está en curso. Consulta de nuevo en un minuto.")
    api = provider(inv)
    try:
        doc = api.read(inv) if inv["external_id"] else api.find(inv)
    except ProviderError as error:
        abort(503, str(error))
    if doc is None:
        return view(mark(inv, "reserved", message="El emisor no tiene esta referencia. Puedes reintentar la creación."))
    return view(record(inv, doc, after_send=inv["status"] == "sending"))
