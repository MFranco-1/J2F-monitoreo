"""Importación manual. PostgreSQL conserva el lote entre páginas y hace la conciliación final."""
import json
import time
from http.client import HTTPException, HTTPSConnection
from urllib.parse import urlencode, urlsplit

import phonenumbers
from flask import current_app

from app.database import invoke


class CoolboxError(Exception):
    """Mensaje dirigido al operador; nunca contiene la respuesta privada del proveedor."""


def fetch_page(page):
    key = current_app.config["COOLBOX_API_KEY"]
    if not key:
        raise CoolboxError("Configura COOLBOX_API_KEY en el backend de J2F.")
    try:
        endpoint = urlsplit(current_app.config["COOLBOX_API_URL"])
        port = endpoint.port
    except ValueError as exc:
        raise CoolboxError("Revisa COOLBOX_API_URL en el backend de J2F.") from exc
    if (endpoint.scheme != "https" or not endpoint.hostname or endpoint.username
            or endpoint.password or endpoint.query or endpoint.fragment):
        raise CoolboxError("Revisa COOLBOX_API_URL en el backend de J2F.")
    query = urlencode({"pagina": page, "por_pagina": 100})
    for attempt in range(2):
        # La primera petición puede despertar la instancia gratuita. Un reintento
        # corto cubre un 502/503 sin exceder el tiempo del worker después de una espera larga.
        started = time.monotonic()
        conn = HTTPSConnection(endpoint.hostname, port, timeout=65)
        try:
            conn.request("GET", f"{endpoint.path}?{query}", headers={
                "X-API-Key": key, "Accept": "application/json",
            })
            response = conn.getresponse()
            if response.status == 200:
                return json.load(response)
            if response.status in (401, 403):
                raise CoolboxError("COOLBOX rechazó la clave de acceso.")
            if response.status == 429:
                raise CoolboxError("COOLBOX alcanzó su límite de consultas. Intenta de nuevo en un minuto.")
            if response.status not in (502, 503) or attempt or time.monotonic() - started > 10:
                raise CoolboxError(f"COOLBOX devolvió HTTP {response.status}.")
        except (TimeoutError, OSError, HTTPException) as exc:
            raise CoolboxError("No se pudo conectar con COOLBOX o se agotó el tiempo de espera.") from exc
        except ValueError as exc:
            raise CoolboxError("COOLBOX devolvió una respuesta inválida.") from exc
        finally:
            conn.close()
        time.sleep(2)


def last_page(payload, page):
    if (not isinstance(payload, dict) or not isinstance(payload.get("clientes"), list)
            or type(payload.get("pagina")) is not int or payload["pagina"] != page
            or "siguiente" not in payload):
        raise CoolboxError("COOLBOX devolvió una página de clientes incompleta.")
    # La API numera las páginas consecutivamente. Nunca reenviamos la clave a un enlace recibido.
    return payload["siguiente"] is None


def stage_row(raw):
    fields = {}
    row = {"fields": fields}
    if not isinstance(raw, dict):
        return row | {"error": "El registro debe ser un objeto JSON"}
    for field in ("tipo_documento", "numero_documento", "nombre_completo", "telefono", "email", "direccion"):
        value = raw.get(field)
        if value is None:
            continue
        if not isinstance(value, str):
            row["error"] = f"El campo {field} debe ser texto"
        elif "\x00" in value or any(0xD800 <= ord(c) <= 0xDFFF for c in value):
            row["error"] = f"El campo {field} contiene caracteres no válidos"
        else:
            fields[field] = value.strip()
    phone = fields.get("telefono", "")
    if phone.isascii() and phone.isdigit():
        try:
            parsed = phonenumbers.parse(phone, "PE")
            if phonenumbers.is_valid_number_for_region(parsed, "PE") and str(parsed.national_number) == phone:
                row["phone"] = phonenumbers.format_number(parsed, phonenumbers.PhoneNumberFormat.E164)
        except phonenumbers.NumberParseException:
            pass  # La función de carga registra el rechazo junto con la fila original.
    return row


def import_clients(actor, profile, batch_id):
    batch = invoke("j2f_coolbox_batch", actor, profile, batch_id)
    started = time.monotonic()
    while True:
        page = batch["next_page"]
        args = (actor, profile, batch["batch_id"], page)
        requested = time.monotonic()
        try:
            payload = fetch_page(page)
            last = last_page(payload, page)
        except CoolboxError as exc:
            message = f"Lote {batch['batch_id']}, página {page}: {exc}"
            return invoke("j2f_coolbox_page", *args, {"error": message}), 502
        rows = [stage_row(item) for item in payload["clientes"]]
        batch = invoke("j2f_coolbox_page", *args, {"rows": rows, "last": last})
        if last:
            return batch, 200
        time.sleep(max(0, 1 - (time.monotonic() - requested)))  # Hasta 60 consultas por minuto.
        if time.monotonic() - started >= 15:
            # Angular continúa el mismo lote para que las listas largas no agoten el timeout de Render.
            return batch, 202
