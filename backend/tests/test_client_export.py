"""Contrato de lectura de clientes para el backend de COOLBOX."""
from secrets import token_urlsafe

import pytest


CLIENTS = "/api/clients/"


@pytest.fixture
def partner_headers(app, monkeypatch):
    key = token_urlsafe(32)
    monkeypatch.setitem(app.config, "J2F_CLIENTS_API_KEY", key)
    return {"X-API-Key": key}


def test_partner_gets_only_agreed_fields_and_documents(client, admin, partner_headers):
    documents = [
        ("DNI", "00002701"), ("RUC", "20999004211"), ("CE", "CBX000271"),
        ("PASAPORTE", "CBX02701"), ("Código interno", "INT-COOLBOX-27"),
    ]
    for kind, number in documents:
        data = {
            "document_type": kind, "document_number": number, "business_name": "Cliente de prueba",
            "contact_name": "Contacto interno",
        }
        if kind == "DNI":
            data.update(
                phone="987654321", phone_country="PE", email="cliente@example.test",
                address="Av. Central 120",
            )
        assert client.post(CLIENTS, headers=admin, json=data).status_code == 201

    response = client.get(CLIENTS, headers=partner_headers)
    assert response.status_code == 200 and set(response.json) == {"clients"}
    fields = {"document_type", "document_number", "business_name", "phone", "email", "address"}
    assert all(set(row) == fields for row in response.json["clients"])
    exported = {row["document_number"]: row for row in response.json["clients"]}
    for kind, number in documents[:-1]:
        assert exported[number]["document_type"] == kind
    assert "INT-COOLBOX-27" not in exported
    assert exported["00002701"] == {
        "document_type": "DNI", "document_number": "00002701", "business_name": "Cliente de prueba",
        "phone": "+51987654321", "email": "cliente@example.test", "address": "Av. Central 120",
    }
    assert all(exported["CBX02701"][name] is None for name in ("phone", "email", "address"))
    assert client.get(CLIENTS, headers=admin | partner_headers).json == response.json

    local = client.get(CLIENTS, headers=admin, query_string={"search": "INT-COOLBOX-27"})
    assert len(local.json["clients"]) == 1
    assert local.json["clients"][0]["contact_name"] == "Contacto interno"


def test_invalid_and_disabled_keys(client, app, admin, partner_headers, monkeypatch):
    other_key = token_urlsafe(32)
    monkeypatch.setitem(app.config, "COOLBOX_API_KEY", other_key)
    for headers in (
        {}, {"X-API-Key": ""}, {"X-API-Key": other_key}, {"X-API-Key": "inválida"},
        admin | {"X-API-Key": other_key},
    ):
        assert client.get(CLIENTS, headers=headers).status_code == 401
    monkeypatch.setitem(app.config, "J2F_CLIENTS_API_KEY", "")
    assert client.get(CLIENTS, headers=partner_headers).status_code == 401
    assert client.get(CLIENTS, headers=admin).status_code == 200


@pytest.mark.parametrize(("method", "path"), [
    ("POST", CLIENTS), ("PUT", CLIENTS + "1"), ("DELETE", CLIENTS + "1"),
    ("GET", CLIENTS + "1"), ("GET", "/api/master-data/clients/"),
    ("POST", "/api/master-data/clients/import-coolbox"), ("GET", "/api/vehicles/"),
    ("GET", "/api/alerts/"), ("GET", "/api/users/"),
])
def test_key_is_limited_to_reading_the_client_list(client, partner_headers, method, path):
    assert client.open(path, method=method, headers=partner_headers).status_code == 401


def test_jwt_keeps_the_active_profile_scope(client, admin, partner_headers):
    profiles = client.get("/api/profiles/", headers=admin).json["profiles"]
    technician = next(profile for profile in profiles if profile["role_code"] == "technician")
    user = {
        "dni": "00780512", "full_name": "Técnica de pruebas", "email": "tecnica@example.test",
        "profile_ids": [technician["id"]], "password": token_urlsafe(24),
    }
    created = client.post("/api/users/", headers=admin, json=user)
    assert created.status_code == 201
    user_url = f"/api/users/{created.json['user']['id']}"
    try:
        record = {
            "document_type": "DNI", "document_number": "00002702", "business_name": "Otro cliente",
        }
        assert client.post(CLIENTS, headers=admin, json=record).status_code == 201
        login = client.post(
            "/api/auth/login", json={"identifier": user["email"], "password": user["password"]},
        )
        assert login.status_code == 200
        jwt = {"Authorization": "Bearer " + login.json["access_token"]}
        assert client.get(CLIENTS, headers=jwt).json == {"clients": []}
        exported = client.get(CLIENTS, headers=partner_headers).json["clients"]
        assert any(row["document_number"] == "00002702" for row in exported)
    finally:
        # El técnico ficticio deja de ser elegible para la asignación automática de otras pruebas.
        assert client.delete(user_url, headers=admin).status_code == 200
