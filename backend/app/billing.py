"""Facturación de planes. Cada invoke confirma y libera su conexión antes de llamar a Laravel."""
import json
import re
from datetime import datetime, timezone
from decimal import Decimal, InvalidOperation

from flask import Blueprint, Response, abort, request
from flask_jwt_extended import jwt_required
from app.api import body, context
from app.database import invoke
from app.fact_api import FactAPI, ProviderError

billing = Blueprint("billing", __name__)


def db(action, **data):
    return invoke("j2f_billing", action, data, *context())


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
    return db("catalog")


@billing.put("/plans/<int:vehicle>")
@jwt_required()
def plan(vehicle):
    data = body()
    if data.get("plan") not in ("monthly", "annual") or type(data.get("equipment_paid")) is not bool:
        abort(400, "Selecciona el plan y confirma si el equipo ya se facturó.")
    return db("plan", vehicle_id=vehicle, plan=data["plan"], service_start=data.get("service_start"),
              first_period=month(data.get("first_period")), equipment_paid=data["equipment_paid"])


@billing.get("/preview")
@jwt_required()
def preview():
    data = db("preview", client_id=client_id(request.args.get("client")), period=month(request.args.get("period")))
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
    args = dict(client_id=client_id(data.get("client")), period=month(data.get("period")))
    current = db("preview", **args)
    if current.get("id") and current["status"] != "reserved":
        return view(current)
    api = provider(current if current.get("id") else None)
    inv = db("reserve", **args, issuer=api.issuer, signature=data.get("signature"))
    if inv["status"] != "reserved":
        return view(inv)
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
