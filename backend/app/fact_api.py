"""Cliente HTTP del emisor Laravel. Las credenciales se quedan en Flask."""
import json
import re
from decimal import Decimal
from urllib.error import HTTPError, URLError
from urllib.parse import urlencode, urlsplit
from urllib.request import HTTPRedirectHandler, Request, build_opener

from flask import current_app

BETA = "https://e-beta.sunat.gob.pe/ol-ti-itcpfegem-beta/billService"


class ProviderError(Exception):
    def __init__(self, message, code=None):
        super().__init__(message)
        self.code = code


class NoRedirect(HTTPRedirectHandler):
    def redirect_request(self, *args):
        return None


class FactAPI:
    def __init__(self):
        cfg = current_app.config
        self.url = cfg["FACT_API_URL"].rstrip("/")
        self.token = cfg["FACT_API_TOKEN"]
        self.missing = []
        parsed = urlsplit(self.url)
        if not parsed.hostname or parsed.username or parsed.password or parsed.query or parsed.fragment or not (
            parsed.scheme == "https" or parsed.scheme == "http" and parsed.hostname in ("localhost", "127.0.0.1", "::1")
        ):
            self.missing.append("URL privada de fact_api (HTTPS o localhost)")
        if not self.token:
            self.missing.append("Token Sanctum en Flask")
        self.issuer = {"url": self.url, "serie": cfg["FACT_API_SERIES"]}
        if not re.fullmatch(r"F[A-Z0-9]{3}", self.issuer["serie"]):
            self.missing.append("Serie de factura de 4 caracteres que empiece por F")
        for field, key in (("company_id", "FACT_API_COMPANY_ID"), ("branch_id", "FACT_API_BRANCH_ID")):
            value = str(cfg[key])
            if not re.fullmatch("[1-9][0-9]{0,9}", value):
                self.missing.append(key)
            else:
                self.issuer[field] = int(value)

    def request(self, path, data=None):
        req = Request(self.url + "/api/v1/" + path,
                      data=None if data is None else json.dumps(data).encode(),
                      headers={"Authorization": "Bearer " + self.token, "Accept": "application/json",
                               "Content-Type": "application/json"})
        try:
            with build_opener(NoRedirect).open(req, timeout=15) as res:
                obj = json.load(res)
                if obj.get("success") is not True or not isinstance(obj.get("data"), dict):
                    raise ProviderError("Respuesta incompleta de fact_api.")
                return obj["data"]
        except HTTPError as error:
            raise ProviderError(f"fact_api devolvió HTTP {error.code}.", error.code) from None
        except (URLError, OSError, ValueError, AttributeError) as error:
            raise ProviderError("No se obtuvo una respuesta válida de fact_api.") from error

    def invoice_pdf(self, inv):
        path = f'invoices/{int(inv["external_id"])}'
        document = self.read(inv)
        if (document.get("datos_adicionales") or {}).get("j2f_reference") != inv["reference"]:
            raise ProviderError("El comprobante del emisor no coincide con esta factura.")
        def download():
            req = Request(self.url + "/api/v1/" + path + "/download-pdf",
                          headers={"Authorization": "Bearer " + self.token, "Accept": "application/pdf"})
            with build_opener(NoRedirect).open(req, timeout=30) as response:
                pdf = response.read()
                if not pdf.startswith(b"%PDF-"):
                    raise ProviderError("El emisor no devolvió un PDF válido.")
                return pdf
        try:
            try:
                return download()
            except HTTPError as error:
                if error.code != 404:
                    raise
            self.request(path + "/generate-pdf", {"format": "A4"})
            return download()
        except (URLError, OSError) as error:
            raise ProviderError("No se pudo obtener el PDF del emisor.") from error

    def check_beta(self):
        if self.missing:
            raise ProviderError("Configura: " + ", ".join(self.missing))
        data = self.request("companies/" + str(self.issuer["company_id"]))
        company = data.get("company") or {}
        if (company.get("modo_produccion") is not False or data.get("j2f_beta_endpoint") != BETA
                or company.get("id") != self.issuer["company_id"]):
            raise ProviderError("El emisor debe usar la integración J2F y el endpoint exclusivo de SUNAT beta.")
        self.signing_ready = data.get("j2f_signing_ready") is True
        if not any(b.get("id") == self.issuer["branch_id"] for b in company.get("branches", [])):
            raise ProviderError("La sucursal configurada no pertenece al emisor.")

    def create(self, inv):
        details = []
        for line in inv["lines"]:
            price, tax = Decimal(str(line["gross"])), Decimal(str(line["igv"]))
            details.append({
                "codigo": f'{line["vehicle_id"]}-{line["concept"]}', "cantidad": 1,
                "descripcion": f'{line["plate"]} · {line["label"]} · {line["period"][:7]}',
                "unidad": "NIU" if line["concept"] == "equipment" else "ZZ",
                "mto_valor_unitario": str(round(price / (1 + tax / 100), 8)),
                "j2f_precio_final": str(price), "porcentaje_igv": str(tax), "tip_afe_igv": "10",
            })
        return self.request("invoices", {
            "company_id": self.issuer["company_id"], "branch_id": self.issuer["branch_id"],
            "serie": self.issuer["serie"], "fecha_emision": inv["issue_date"], "moneda": "PEN",
            "forma_pago_tipo": "Contado", "tipo_operacion": "0101", "client": inv["recipient"],
            "detalles": details, "datos_adicionales": {"j2f_reference": inv["reference"]},
        })

    def find(self, inv):
        params = {"company_id": self.issuer["company_id"], "branch_id": self.issuer["branch_id"],
                  "j2f_reference": inv["reference"]}
        result = self.request("invoices?" + urlencode(params))
        docs = result.get("data")
        if docs == [] and result.get("total") == 0:
            return None
        if (not isinstance(docs, list) or len(docs) != 1 or result.get("total") != 1
                or not isinstance(docs[0], dict)
                or (docs[0].get("datos_adicionales") or {}).get("j2f_reference") != inv["reference"]):
            raise ProviderError("El emisor no pudo identificar una factura única por referencia.")
        return docs[0]

    def read(self, inv):
        return self.request(f'invoices/{int(inv["external_id"])}')

    def send(self, inv):
        return self.request(f'invoices/{int(inv["external_id"])}/send-sunat', {})
