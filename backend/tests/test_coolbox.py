"""Proveedor ficticio y maestro real en el PostgreSQL exclusivo de la suite."""
import io
import json
from concurrent.futures import ThreadPoolExecutor
from urllib.parse import parse_qs, urlsplit

import pytest

from app import coolbox


ROUTE = "/api/master-data/clients/import-coolbox"


@pytest.fixture
def source(app, monkeypatch):
    calls, pages = [], {}
    monkeypatch.setitem(app.config, "COOLBOX_API_KEY", "clave-ficticia")
    monkeypatch.setitem(app.config, "COOLBOX_API_URL", "https://coolbox.invalid/api/integracion/clientes")
    monkeypatch.setattr(coolbox, "time", type("Clock", (), {
        "sleep": staticmethod(lambda seconds: None), "monotonic": staticmethod(lambda: 0),
    }))

    class Connection:
        def __init__(self, host, port, timeout):
            assert host == "coolbox.invalid"

        def request(self, method, path, headers):
            assert method == "GET" and headers["X-API-Key"] == "clave-ficticia"
            query = parse_qs(urlsplit(path).query)
            assert query["por_pagina"] == ["100"]
            self.page = int(query["pagina"][0])
            calls.append(self.page)

        def getresponse(self):
            value = pages[self.page]
            if isinstance(value, Exception):
                raise value
            reply = io.BytesIO(json.dumps(value).encode())
            reply.status = value if isinstance(value, int) else 200
            return reply

        def close(self):
            pass

    monkeypatch.setattr(coolbox, "HTTPSConnection", Connection)
    return pages, calls


def customer(kind, number, name="María Salas Ruiz", **fields):
    return dict(tipo_documento=kind, numero_documento=number, nombre_completo=name, **fields)


def test_import_pages_mapping_conflicts_and_repeat(client, admin, source):
    pages, calls = source
    local = {
        "document_type": "DNI", "document_number": "00345678", "business_name": "Nombre anterior",
        "phone": "987654321", "phone_country": "PE", "contact_name": "Contacto local",
        "address": "Av. Central 123", "email": "local@example.org",
    }
    assert client.post("/api/clients/", json=local, headers=admin).status_code == 201
    pages[1] = {"pagina": 1, "siguiente": 2, "clientes": [
        customer("DNI", "00345678", telefono="", email=None, direccion="   "),
        customer("CE", "AB1234567", telefono="987654321", direccion="Av. Los Álamos 41"),
        customer("PASAPORTE", "00345678"),
    ]}
    pages[2] = {"pagina": 2, "siguiente": None, "clientes": [
        customer("PASAPORTE", "J2F12345", email="contacto@example.org"),
        customer("RUC", "20999990011", "Empresa ficticia SAC"),
        customer("DNI", "00000005", ""), customer("DNI", "12"),
        customer("DNI", "00000007", email="correo-invalido"),
        customer("DNI", "00000008", telefono="1234567"),
        customer("RUC", "99100055237"), customer("DNI", 12345678),
    ]}
    response = client.post(ROUTE, headers=admin)
    assert response.status_code == 200, response.json
    result = response.json
    assert calls == [1, 2]
    assert [result[k] for k in ("total", "created", "updated", "unchanged", "rejected")] == [
        11, 3, 1, 0, 7
    ], result
    reasons = [row["reason"] for row in result["rejections"]]
    assert all(word in reason for word, reason in zip(
        ("otro tipo", "Nombre", "Número", "Correo", "Teléfono", "Prefijo", "texto"), reasons
    ))
    records = {r["document_number"]: r for r in client.get("/api/clients/", headers=admin).json["clients"]}
    updated = records["00345678"]
    assert updated["document_type"] == "DNI" and updated["business_name"] == "María Salas Ruiz"
    assert updated["phone"] == "+51987654321" and updated["email"] == local["email"]
    assert updated["address"] == local["address"] and updated["contact_name"] == local["contact_name"]
    assert records["AB1234567"]["phone"] == "+51987654321"
    assert records["J2F12345"]["email"] == "contacto@example.org"
    repeat = client.post(ROUTE, headers=admin).json
    assert repeat["batch_id"] != result["batch_id"]
    assert [repeat[k] for k in ("created", "updated", "unchanged", "rejected")] == [0, 0, 4, 7]


def test_failed_second_page_keeps_master_untouched_and_records_error(client, admin, app, source):
    pages, calls = source
    pages[1] = {"pagina": 1, "siguiente": "https://otro.invalid/?pagina=2", "clientes": [customer("DNI", "00222222")]}
    pages[2] = 503
    response = client.post(ROUTE, headers=admin)
    assert response.status_code == 502 and "503" in response.json["error"]
    assert calls == [1, 2, 2]
    bid = response.json["batch_id"]
    app.config["TEST_SQL"](f"""DO $$ BEGIN
        ASSERT EXISTS (SELECT FROM coolbox_import_batches WHERE id={bid} AND status='failed');
        ASSERT EXISTS (SELECT FROM coolbox_client_staging WHERE batch_id={bid} AND outcome='pending');
        ASSERT NOT EXISTS (SELECT FROM clients WHERE document_number='00222222');
    END $$;""")
    pages[1] = {"pagina": 1, "siguiente": None, "clientes": []}
    result = client.post(ROUTE, headers=admin).json
    assert result["total"] == 0 and result["batch_id"] != bid


def test_long_import_continues_same_batch(client, admin, source, monkeypatch):
    pages, _ = source
    ticks = iter([0, 0, 0, 20, 20, 20, 20, 20])
    monkeypatch.setattr(coolbox.time, "monotonic", staticmethod(lambda: next(ticks, 20)))
    pages[1] = {"pagina": 1, "siguiente": 2, "clientes": [customer("DNI", "00999999")]}
    pages[2] = {"pagina": 2, "siguiente": None, "clientes": []}
    pending = client.post(ROUTE, headers=admin)
    assert pending.status_code == 202, pending.json
    url = f"{ROUTE}/{pending.json['batch_id']}"
    result = client.post(url, headers=admin)
    assert result.status_code == 200 and result.json["created"] == 1
    assert client.post(url, headers=admin).status_code == 409


def test_import_requires_client_write_permission_before_contacting_coolbox(client, admin, source):
    _, calls = source
    assert client.post(ROUTE).status_code == 401
    profiles = client.get("/api/profiles/", headers=admin).json["profiles"]
    supervisor = next(p for p in profiles if p["role_code"] == "supervisor")
    user = {"dni": "00777777", "full_name": "Supervisor de importaciones", "password": "PruebaClave123",
            "email": "supervisor-coolbox@example.org", "profile_ids": [supervisor["id"]]}
    assert client.post("/api/users/", json=user, headers=admin).status_code == 201
    login = client.post("/api/auth/login", json={"identifier": user["email"], "password": user["password"]})
    headers = {"Authorization": "Bearer " + login.json["access_token"]}
    assert client.post(ROUTE, headers=headers).status_code == 403 and calls == []


def test_overlapping_imports_create_only_one_client(app, admin, source):
    pages, _ = source
    pages[1] = {"pagina": 1, "siguiente": None, "clientes": [customer("DNI", "00889911")]}

    def submit():
        with app.test_client() as client:
            response = client.post(ROUTE, headers=admin)
            assert response.status_code == 200, response.json
            return response.json

    with ThreadPoolExecutor(max_workers=2) as pool:
        futures = [pool.submit(submit) for _ in range(2)]
        results = [future.result() for future in futures]
    assert len({result["batch_id"] for result in results}) == 2
    assert sum(result["created"] for result in results) == 1
    assert sum(result["unchanged"] for result in results) == 1


def test_missing_key_is_reported_without_making_a_request(app, client, admin, source, monkeypatch):
    _, calls = source
    monkeypatch.setitem(app.config, "COOLBOX_API_KEY", "")
    response = client.post(ROUTE, headers=admin)
    assert response.status_code == 502 and "COOLBOX_API_KEY" in response.json["error"]
    assert calls == []


@pytest.mark.parametrize(("bad_page", "expected"), [
    (401, "clave"), (429, "límite"), (TimeoutError(), "tiempo"),
    ({"pagina": 1, "clientes": []}, "incompleta"), ({"pagina": 4, "siguiente": None, "clientes": []}, "incompleta"),
])
def test_provider_failures(client, admin, source, bad_page, expected):
    pages, _ = source
    pages[1] = bad_page
    response = client.post(ROUTE, headers=admin)
    assert response.status_code == 502 and expected in response.json["error"]
