"""Validación de escrituras de todos los formularios; solo SQLite aislado."""
import unittest
from app import create_app, db
from app.models import Profile, State, User, Alert, Assignment, History
from app.models.master_data import Client, Vehicle, GpsDevice, EventType


class InputValidationTests(unittest.TestCase):
    def setUp(self):
        self.app = create_app("testing")
        self.client = self.app.test_client()
        tokens = self.client.post("/api/auth/login", json={
            "identifier": "admin@j2f.com", "password": "Admin@J2F2024"}).get_json()
        self.headers = {"Authorization": "Bearer " + tokens["access_token"]}
        with self.app.app_context():
            self.active = State.query.filter_by(name="Activo", type="user").one().id
            self.inactive = State.query.filter_by(name="Inactivo", type="user").one().id
            self.profile = Profile.query.filter_by(name="Administrador").one().id
        self.client_data = {
            "document_type": "RUC", "document_number": "20123456786",
            "business_name": "Transportes Muñoz S.A.C.", "contact_name": "José D'Ávila",
            "phone": "987654321", "email": "contacto@empresa.com", "address": "Av. Perú 123",
            "state_id": self.active,
        }

    def tearDown(self):
        with self.app.app_context():
            db.session.remove()
            db.engine.dispose()

    def post(self, path, data, status=201):
        response = self.client.post(path, headers=self.headers, json=data)
        self.assertEqual(response.status_code, status, response.get_json())
        return response.get_json()

    def rejected(self, method, path, data):
        response = getattr(self.client, method)(path, headers=self.headers, json=data)
        self.assertEqual(response.status_code, 400, response.get_json())
        self.assertTrue(response.get_json()["error"])

    def customer(self):
        return self.post("/api/master-data/clients/", self.client_data)["record"]["id"]

    def vehicle(self):
        return self.post("/api/master-data/vehicles/", {
            "client_id": self.customer(), "plate": "ABC-123", "state_id": self.active})["record"]["id"]

    def test_clients_reject_invalid_create_and_do_not_insert(self):
        cases = [
            ("document_type", "A"), ("document_type", 1), ("document_type", None),
            ("document_number", "3000000028254561"), ("document_number", "1234567890h"),
            ("document_number", ""), ("document_number", 20123456789),
            ("business_name", "A"), ("business_name", "   "), ("business_name", "..."),
            ("business_name", "123456"), ("business_name", "AAAAAA"),
            ("business_name", "x" * 181), ("business_name", "Empresa\u200b falsa"),
            ("contact_name", "A"), ("contact_name", "Juan123"),
            ("phone", "987654321h"), ("phone", "+99987654321"), ("phone", "987 654 321"),
            ("phone", "1"), ("phone", "9" * 16), ("email", "hola@gmail"),
            ("email", "hola..nombre@gmail.com"), ("email", "hola@-gmail.com"),
            ("address", "A"), ("address", "12345"), ("state_id", 99999),
        ]
        for field, value in cases:
            with self.subTest(field=field, value=value):
                self.rejected("post", "/api/master-data/clients/", {**self.client_data, field: value})
        with self.app.app_context():
            self.assertEqual(Client.query.count(), 0)

    def test_clients_reject_invalid_edits_atomically(self):
        customer = self.customer()
        original = self.client.get(f"/api/master-data/clients/{customer}", headers=self.headers).get_json()["client"]
        for field, value in [("document_number", "123"), ("document_type", "DNI"),
                             ("business_name", "A"), ("contact_name", "1"),
                             ("phone", "987654321h"), ("email", "no-correo"), ("address", "A")]:
            with self.subTest(field=field):
                self.rejected("put", f"/api/master-data/clients/{customer}",
                              {field: value, "state_id": self.inactive})
                record = self.client.get(f"/api/master-data/clients/{customer}", headers=self.headers).get_json()["client"]
                self.assertEqual(record[field], original[field])
                self.assertEqual(record["state_id"], self.active)

    def test_valid_client_documents_optional_fields_and_normalization(self):
        for kind, number in [
                ("ruc", "20123456786"), ("DNI", "01234567"),
                ("CE", "001234567"), ("PASAPORTE", "ab123456")]:
            with self.subTest(kind=kind):
                record = self.post("/api/master-data/clients/", {
                    **self.client_data, "document_type": kind, "document_number": " " + number + " ",
                    "business_name": "  Logística Ñandú E.I.R.L.  ", "contact_name": "", "phone": "",
                    "email": "", "address": None,
                })["record"]
                self.assertEqual(record["document_type"], kind.upper())
                self.assertEqual(record["document_number"], number.upper())
                self.assertEqual(record["business_name"], "Logística ñandú e.i.r.l.")
        self.rejected("post", "/api/master-data/clients/", self.client_data)

    def test_document_type_and_number_must_be_valid_together_on_edit(self):
        customer = self.customer()
        response = self.client.put(f"/api/master-data/clients/{customer}", headers=self.headers, json={
            "document_type": "DNI", "document_number": "01234567"})
        self.assertEqual(response.status_code, 200, response.get_json())
        self.rejected("put", f"/api/master-data/clients/{customer}", {"document_number": "20123456789"})

    def test_old_invalid_clients_are_preserved_and_state_only_edits_work(self):
        with self.app.app_context():
            old = Client(document_type="RUC", document_number="3000000028254561",
                         business_name="A", phone="987654321h", state_id=self.active)
            db.session.add(old)
            db.session.commit()
            customer = old.id
        response = self.client.put(f"/api/master-data/clients/{customer}", headers=self.headers,
                                   json={"state_id": self.inactive})
        self.assertEqual(response.status_code, 200, response.get_json())
        self.assertEqual(response.get_json()["record"]["document_number"], "3000000028254561")
        self.rejected("put", f"/api/master-data/clients/{customer}", {"business_name": "B"})

    def test_vehicle_validation_create_edit_and_short_valid_brands(self):
        base = {"client_id": self.customer(), "plate": "abc-123", "state_id": self.active}
        for field, value in [("plate", "A"), ("plate", "ABC!123"), ("plate", "123456"),
                             ("plate", "ABCDEF"), ("brand", "A"), ("model", "X"),
                             ("color", "R"), ("vehicle_type", "C"), ("client_id", 99999)]:
            with self.subTest(field=field):
                self.rejected("post", "/api/master-data/vehicles/", {**base, field: value})
        record = self.post("/api/master-data/vehicles/", {**base, "brand": "MG", "model": "X5"})["record"]
        self.assertEqual(record["plate"], "ABC-123")
        self.rejected("put", f"/api/master-data/vehicles/{record['id']}", {"plate": "A"})
        with self.app.app_context():
            self.assertEqual(Vehicle.query.count(), 1)
            self.assertEqual(db.session.get(Vehicle, record["id"]).plate, "ABC-123")

    def test_gps_validation_create_edit_and_optional_serial(self):
        base = {"vehicle_id": self.vehicle(), "imei": "860000000000001", "state_id": self.active}
        for field, value in [("imei", "123"), ("imei", "86000000000000h"),
                             ("imei", "8600000000000001"), ("serial_number", "A"),
                             ("serial_number", "ABC 123"), ("sim_number", "987654321h"),
                             ("provider", "A"), ("vehicle_id", 99999)]:
            with self.subTest(field=field):
                self.rejected("post", "/api/master-data/gps-devices/", {**base, field: value})
        record = self.post("/api/master-data/gps-devices/", {**base, "serial_number": "", "sim_number": "51987654321"})["record"]
        self.assertIsNone(record["serial_number"])
        self.rejected("put", f"/api/master-data/gps-devices/{record['id']}", {"imei": "A"})
        with self.app.app_context():
            self.assertEqual(GpsDevice.query.count(), 1)

    def test_event_types_validate_codes_names_text_and_enums(self):
        base = {"code": "TEST_EVENT", "name": "Evento de prueba", "state_id": self.active}
        for field, value in [("code", "A"), ("code", "1EVENT"), ("code", "TEST EVENT"),
                             ("name", "A"), ("name", "12345"), ("description", "A"),
                             ("expected_action", "A"), ("default_priority", "alta"),
                             ("generates_alert", "true")]:
            with self.subTest(field=field):
                self.rejected("post", "/api/master-data/event-types/", {**base, field: value})
        record = self.post("/api/master-data/event-types/", base)["record"]
        self.rejected("put", f"/api/master-data/event-types/{record['id']}", {"name": "A"})

    def test_users_validate_names_dni_email_password_and_edits(self):
        base = {"dni": "01234567", "full_name": "María Pérez", "email": "maria@empresa.com",
                "password": "Password-123!", "profile_ids": [self.profile], "state_id": self.active}
        for field, value in [("dni", "1234567h"), ("full_name", "A"), ("full_name", "María123"),
                             ("email", "maria@@empresa.com"), ("password", "a"),
                             ("password", " " * 8), ("password", "a" * 129), ("profile_ids", [])]:
            with self.subTest(field=field):
                self.rejected("post", "/api/users/", {**base, field: value})
        user_id = self.post("/api/users/", base)["user"]["id"]
        for data in ({"password": "a"}, {"full_name": "A"}, {"email": "a@b.c"}):
            self.rejected("put", f"/api/users/{user_id}", data)
        with self.app.app_context():
            user = db.session.get(User, user_id)
            self.assertTrue(user.check_password(base["password"]))
            self.assertEqual(user.full_name, "María Pérez")

    def test_profiles_menus_and_reports_validate_text_routes_and_dates(self):
        self.rejected("post", "/api/profiles/", {"name": "A", "state_id": self.active})
        profile = self.post("/api/profiles/", {"name": "Auditoría", "state_id": self.active})["profile"]
        self.rejected("put", f"/api/profiles/{profile['id']}", {"description": "A"})
        menu = {"name": "Consulta de alertas", "url": "/alerts", "state_id": self.active}
        for data in ({"name": "A"}, {"url": "https://example.com"}, {"url": "javascript:alert(1)"},
                     {"url": "/bad path"}, {"icon": "<svg>"}, {"order": -1}, {"order": 1.5}):
            self.rejected("post", "/api/menu-options/", {**menu, **data})
        option = self.post("/api/menu-options/", menu)["menu_option"]
        self.rejected("put", f"/api/menu-options/{option['id']}", {"name": "A"})
        report = {"name": "Informe de alertas", "type": "alerts_summary"}
        for data in ({"name": "A"}, {"description": "A"}, {"type": "inventado"},
                     {"date_range_start": "2026-02-30"}, {"filters": {"client_id": 99999}},
                     {"filters": []}, {"filters": False},
                     {"date_range_start": "2026-10-03", "date_range_end": "2026-10-02"}):
            self.rejected("post", "/api/reports/", {**report, **data})

    def test_alerts_and_assignment_notes_cannot_close_with_isolated_letters(self):
        for field, value in [("title", "A"), ("title", "123"), ("description", "A"),
                             ("location", "A"), ("priority", "alta")]:
            self.rejected("post", "/api/alerts/", {"title": "Alerta manual", "description": "Incidencia que requiere atención", field: value})
        alert_id = self.post("/api/alerts/", {"title": "Alerta manual", "description": "Incidencia que requiere atención"})["alert"]["id"]
        self.rejected("put", f"/api/alerts/{alert_id}", {"state_name": "Cerrado", "notes": "A"})
        with self.app.app_context():
            technician = Profile.query.filter_by(name="Técnico").one()
            user = User(dni="12345678", full_name="Técnico Prueba", email="tecnico@empresa.com",
                        profile=technician, state_id=self.active)
            user.set_password("Password-123!")
            db.session.add(user)
            db.session.commit()
            user_id = user.id
        base = {"alert_id": alert_id, "user_id": user_id}
        self.rejected("post", "/api/assignments/", {**base, "notes": "A"})
        assignment = self.post("/api/assignments/", base)["assignment"]
        self.rejected("put", f"/api/assignments/{assignment['id']}", {"notes": "A"})
        self.rejected("put", f"/api/assignments/{assignment['id']}", {"complete": True, "solution": "A"})
        with self.app.app_context():
            self.assertEqual(db.session.get(Alert, alert_id).state.name, "En Progreso")
            self.assertIsNone(db.session.get(Assignment, assignment["id"]).completed_at)
            self.assertEqual(History.query.filter_by(alert_id=alert_id, action="closed").count(), 0)

    def test_fuel_observation_validation_preserves_workflow_and_permissions(self):
        vehicle_id = self.vehicle()
        with self.app.app_context():
            event_id = EventType.query.filter_by(code="LOW_FUEL").one().id
            customer_id = db.session.get(Vehicle, vehicle_id).client_id
        alert_id = self.post("/api/alerts/", {"title": "Combustible bajo", "description": "Nivel bajo que requiere abastecimiento", "vehicle_id": vehicle_id,
            "client_id": customer_id, "event_type_id": event_id})["alert"]["id"]
        path = f"/api/alerts/{alert_id}/fuel-actions"
        for observation in ("A", "...", "12345", "AAAAAA", "a" * 501):
            self.rejected("post", path, {"action": "coordinate", "observation": observation})
        self.post(path, {"action": "confirm", "observation": "Se verificó el abastecimiento"}, 409)
        self.post(path, {"action": "coordinate", "observation": "Se llamó al conductor y se coordinó el pago"}, 200)
        self.rejected("post", path, {"action": "confirm", "observation": "A"})
        self.post(path, {"action": "confirm", "observation": "Se cargaron 30 litros según comprobante 001"}, 200)
        self.post(path, {"action": "confirm", "observation": "Se cargaron 30 litros según comprobante 001"}, 409)

    def test_map_numbers_reject_boolean_infinite_and_out_of_range_values(self):
        vehicle_id = self.vehicle()
        base = {"vehicle_id": vehicle_id, "event_code": "LOW_FUEL", "fuel_percent": 8,
                "latitude": -12, "longitude": -77, "speed": 40}
        for field, value in [("speed", -1), ("speed", 251), ("speed", "NaN"),
                             ("speed", "Infinity"), ("speed", True),
                             ("latitude", True), ("latitude", 91), ("latitude", "NaN"),
                             ("longitude", -181), ("fuel_percent", True), ("fuel_percent", "Infinity")]:
            with self.subTest(field=field, value=value):
                self.rejected("post", "/api/alerts/map/events", {**base, field: value})
        with self.app.app_context():
            self.assertEqual(Alert.query.count(), 0)


if __name__ == "__main__":
    unittest.main()
