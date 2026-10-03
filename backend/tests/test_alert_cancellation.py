"""Anulación documentada, permisos y regresiones; exclusivamente SQLite aislada."""
import sqlite3
import json
import unittest
from pathlib import Path
from app import create_app, db
from app.models import Alert, Assignment, History, Profile, State, User


class AlertCancellationTests(unittest.TestCase):
    def setUp(self):
        self.app = create_app("testing")
        self.assertEqual(self.app.config["SQLALCHEMY_DATABASE_URI"], "sqlite:///:memory:")
        self.client = self.app.test_client()
        self.admin = self.login("admin@j2f.com", "Admin@J2F2024")
        with self.app.app_context():
            self.active = State.query.filter_by(name="Activo", type="user").one().id
            self.inactive = State.query.filter_by(name="Inactivo", type="user").one().id
            self.roles = {p.name: p.id for p in Profile.query.all()}
        self.technician_id, self.technician = self.new_user(1, "Técnico")
        self.supervisor_id, self.supervisor = self.new_user(2, "Supervisor")
        self.operator_id, self.operator = self.new_user(3, "Operador")

    def tearDown(self):
        with self.app.app_context():
            db.session.remove(); db.engine.dispose()

    def login(self, email, password="Password-123!"):
        response = self.client.post("/api/auth/login", json={"identifier": email, "password": password})
        self.assertEqual(response.status_code, 200, response.get_json())
        return {"Authorization": "Bearer " + response.get_json()["access_token"]}

    def new_user(self, index, role):
        response = self.client.post("/api/users/", headers=self.admin, json={
            "dni": f"{index:08d}", "full_name": f"Cuenta Nueva {role}", "email": f"user{index}@empresa.com",
            "password": "Password-123!", "profile_ids": [self.roles[role]], "state_id": self.active})
        self.assertEqual(response.status_code, 201, response.get_json())
        return response.get_json()["user"]["id"], self.login(f"user{index}@empresa.com")

    def alert(self, **changes):
        response = self.client.post("/api/alerts/", headers=self.admin, json={"title": "Alerta para verificar", "description": "Incidencia registrada para verificar la atención", **changes})
        self.assertEqual(response.status_code, 201, response.get_json())
        return response.get_json()["alert"]["id"]

    def assign(self, alert_id):
        response = self.client.post("/api/assignments/", headers=self.admin,
                                    json={"alert_id": alert_id, "user_id": self.technician_id})
        self.assertEqual(response.status_code, 201, response.get_json())
        return response.get_json()["assignment"]["id"]

    def cancel(self, alert_id, headers=None, **data):
        return self.client.post(f"/api/alerts/{alert_id}/cancel", headers=headers or self.admin,
                                json={"reason": "Caso duplicado; se atiende el original", **data})

    def test_admin_and_new_supervisor_can_cancel_each_pending_state_with_audit(self):
        for state in ["Abierto", "En Progreso", "Escalado"]:
            for headers, actor in [(self.admin, None), (self.supervisor, self.supervisor_id)]:
                with self.subTest(state=state, supervisor=actor is not None):
                    alert_id = self.alert()
                    if state != "Abierto":
                        response = self.client.put(f"/api/alerts/{alert_id}", headers=self.admin, json={"state_name": state})
                        self.assertEqual(response.status_code, 200, response.get_json())
                    response = self.cancel(alert_id, headers)
                    self.assertEqual(response.status_code, 200, response.get_json())
                    record = response.get_json()["alert"]
                    self.assertEqual(record["state"]["name"], "Anulado")
                    self.assertIsNone(record["resolved_at"])
                    self.assertIsNone(record["response_time_minutes"])
                    entry = next(item for item in record["history"] if item["action"] == "cancelled")
                    self.assertEqual(entry["previous_state"], state)
                    self.assertEqual(entry["new_state"], "Anulado")
                    self.assertIn("duplicado", entry["detail"])
                    self.assertTrue(entry["timestamp"])
                    self.assertEqual(entry["profile"]["name"], "Supervisor" if actor else "Administrador")
                    if actor: self.assertEqual(entry["user_id"], actor)
                    reloaded = self.client.get(f"/api/alerts/{alert_id}", headers=headers).get_json()["alert"]
                    self.assertEqual(reloaded["history"], record["history"])

    def test_other_new_roles_and_anonymous_cannot_cancel_even_by_direct_request(self):
        with self.app.app_context():
            profile = Profile(name="Auditor", state_id=self.active)
            db.session.add(profile); db.session.commit(); self.roles["Auditor"] = profile.id
        _, auditor = self.new_user(4, "Auditor")
        alert_id = self.alert(); self.assign(alert_id)
        for headers in [self.technician, self.operator, auditor]:
            response = self.cancel(alert_id, headers)
            self.assertEqual(response.status_code, 403, response.get_json())
        self.assertEqual(self.client.post(f"/api/alerts/{alert_id}/cancel", json={"reason": "Caso duplicado"}).status_code, 401)
        with self.app.app_context():
            self.assertEqual(db.session.get(Alert, alert_id).state.name, "En Progreso")
            self.assertEqual(History.query.filter_by(action="cancelled").count(), 0)

    def test_multirole_permission_uses_selected_profile_and_not_any_assigned_role(self):
        response = self.client.put(f"/api/users/{self.operator_id}", headers=self.admin,
                                  json={"profile_ids": [self.roles["Operador"], self.roles["Supervisor"]]})
        self.assertEqual(response.status_code, 200, response.get_json())
        temporary = self.login("user3@empresa.com")
        alert_id = self.alert()
        self.assertEqual(self.cancel(alert_id, temporary).status_code, 401)
        for role, expected in [("Operador", 403), ("Supervisor", 200)]:
            response = self.client.post("/api/auth/select-profile", headers=temporary, json={"profile_id": self.roles[role]})
            self.assertEqual(response.status_code, 200, response.get_json())
            selected = {"Authorization": "Bearer " + response.get_json()["access_token"]}
            self.assertEqual(self.cancel(alert_id, selected).status_code, expected)
            # Perfil seleccionado invalida el token temporal anterior.
            if role == "Operador": temporary = self.login("user3@empresa.com")

    def test_reason_required_and_invalid_attempts_leave_assignments_and_history_unchanged(self):
        alert_id = self.alert(); assignment_id = self.assign(alert_id)
        for data in [{}, {"reason": None}, {"reason": ""}, {"reason": "   "}, {"reason": "A"},
                     {"reason": "..."}, {"reason": "12345"}, {"reason": "x" * 1001}, {"reason": 12}]:
            response = self.client.post(f"/api/alerts/{alert_id}/cancel", headers=self.supervisor, json=data)
            self.assertEqual(response.status_code, 400, response.get_json())
        with self.app.app_context():
            self.assertIsNone(db.session.get(Assignment, assignment_id).completed_at)
            self.assertEqual(db.session.get(Alert, alert_id).state.name, "En Progreso")
            self.assertEqual(History.query.filter_by(action="cancelled").count(), 0)

    def test_cancellation_terminal_duplicate_closed_and_assignment_writes_rejected(self):
        alert_id = self.alert(); assignment_id = self.assign(alert_id)
        self.assertEqual(self.cancel(alert_id, self.supervisor).status_code, 200)
        self.assertEqual(self.cancel(alert_id).status_code, 409)
        for data in [{"state_name": "Abierto"}, {"state_name": "Cerrado", "notes": "Solucion no aplicada"}, {"title": "Otro titulo"}]:
            self.assertEqual(self.client.put(f"/api/alerts/{alert_id}", headers=self.admin, json=data).status_code, 409)
        self.assertEqual(self.client.post("/api/assignments/", headers=self.operator,
            json={"alert_id": alert_id, "user_id": self.technician_id}).status_code, 409)
        self.assertEqual(self.client.post("/api/assignments/auto-assign", headers=self.supervisor,
            json={"alert_id": alert_id}).status_code, 409)
        for headers in [self.admin, self.technician]:
            for data in [{"notes": "No debe guardarse"}, {"complete": True, "solution": "No debe cerrarse"}]:
                self.assertEqual(self.client.put(f"/api/assignments/{assignment_id}", headers=headers, json=data).status_code, 409)
        closed = self.alert()
        self.assertEqual(self.client.put(f"/api/alerts/{closed}", headers=self.admin,
            json={"state_name": "Cerrado", "notes": "Incidencia solucionada"}).status_code, 200)
        self.assertEqual(self.cancel(closed).status_code, 409)
        # El cambio de estado general no sirve para saltar el endpoint de anulación.
        bypass = self.alert(); self.assign(bypass)
        self.assertEqual(self.client.put(f"/api/alerts/{bypass}", headers=self.technician,
            json={"state_name": "Anulado", "notes": "Intento no autorizado"}).status_code, 422)
        with self.app.app_context():
            self.assertEqual(History.query.filter_by(action="cancelled").count(), 1)
            assignment = db.session.get(Assignment, assignment_id)
            self.assertIsNotNone(assignment.completed_at)
            self.assertIsNone(assignment.response_time_minutes)
            self.assertEqual(assignment.to_dict()["status"], "Anulada")

    def test_low_fuel_cancellation_does_not_refuel_and_allows_new_event(self):
        customer = self.client.post("/api/master-data/clients/", headers=self.admin,
            json={"document_type": "DNI", "document_number": "12345678", "business_name": "Empresa Transportes", "state_id": self.active}).get_json()["record"]
        vehicle = self.client.post("/api/master-data/vehicles/", headers=self.admin,
            json={"client_id": customer["id"], "plate": "FUEL-01", "state_id": self.active}).get_json()["record"]
        event = {"vehicle_id": vehicle["id"], "event_code": "LOW_FUEL", "latitude": -12, "longitude": -77, "speed": 30, "fuel_percent": 8}
        alert_id = self.client.post("/api/alerts/map/events", headers=self.admin, json=event).get_json()["alert"]["id"]
        self.assign(alert_id)
        action_path = f"/api/alerts/{alert_id}/fuel-actions"
        self.assertEqual(self.client.post(action_path, headers=self.technician,
            json={"action": "coordinate", "observation": "Pago coordinado con conductor"}).status_code, 200)
        self.assertEqual(self.cancel(alert_id, self.supervisor).status_code, 200)
        mapped = self.client.get("/api/alerts/map/vehicles", headers=self.admin).get_json()["vehicles"][0]
        self.assertEqual(mapped["open_events"], [])
        self.assertIsNone(mapped["fuel_confirmation"])
        for action in ["coordinate", "confirm"]:
            self.assertEqual(self.client.post(action_path, headers=self.admin,
                json={"action": action, "observation": "No se debe abastecer"}).status_code, 409)
        self.assertEqual(self.client.get(f"/api/alerts/map/fuel-stations?alert_id={alert_id}&latitude=-12&longitude=-77", headers=self.admin).status_code, 409)
        self.assertEqual(self.client.get(f"/api/alerts/map/route?alert_id={alert_id}&origin_lat=-12&origin_lng=-77&destination_lat=-12.1&destination_lng=-77.1", headers=self.admin).status_code, 409)
        self.assertEqual(self.client.put(f"/api/master-data/vehicles/{vehicle['id']}", headers=self.admin,
            json={"state_id": self.inactive}).status_code, 200)
        self.client.put(f"/api/master-data/vehicles/{vehicle['id']}", headers=self.admin, json={"state_id": self.active})
        created = self.client.post("/api/alerts/map/events", headers=self.admin, json=event)
        self.assertEqual(created.status_code, 201, created.get_json())
        self.assertNotEqual(created.get_json()["alert"]["id"], alert_id)
        with self.app.app_context():
            self.assertEqual(History.query.filter_by(alert_id=alert_id, action="fuel_coordinated").count(), 1)
            self.assertEqual(History.query.filter_by(alert_id=alert_id, action="fuel_confirmed").count(), 0)

    def test_reports_metrics_history_and_technician_scope_distinguish_cancellation(self):
        alert_id = self.alert(); self.assign(alert_id)
        self.assertEqual(self.cancel(alert_id, self.supervisor).status_code, 200)
        metrics = self.client.get("/api/alerts/metrics", headers=self.admin).get_json()
        self.assertEqual(metrics["by_state"]["Anulado"], 1)
        self.assertEqual(metrics["by_state"]["Cerrado"], 0)
        self.assertEqual(metrics["avg_response_time_minutes"], 0)
        with self.app.app_context(): self.assertEqual(db.session.get(User, self.technician_id).active_assignments_count, 0)
        self.assertEqual(self.client.get(f"/api/alerts/{alert_id}", headers=self.technician).status_code, 200)
        unrelated_id, unrelated = self.new_user(5, "Técnico")
        self.assertEqual(self.client.get(f"/api/alerts/{alert_id}", headers=unrelated).status_code, 403)
        history = self.client.get("/api/reports/history?action=cancelled", headers=self.technician).get_json()["history"]
        self.assertEqual(len(history), 1)
        self.assertEqual(self.client.get("/api/reports/history?action=cancelled", headers=unrelated).get_json()["history"], [])
        listing = self.client.get("/api/alerts/?state=Anulado", headers=self.admin).get_json()["alerts"]
        self.assertEqual([a["id"] for a in listing], [alert_id])
        for report_type in ["alerts_summary", "operator_performance", "response_times"]:
            report_id = self.client.post("/api/reports/", headers=self.supervisor,
                json={"name": "Informe de anulacion", "type": report_type}).get_json()["report"]["id"]
            response = self.client.post(f"/api/reports/{report_id}/generate", headers=self.supervisor)
            self.assertEqual(response.status_code, 200, response.get_json())
            result = json.loads(response.get_json()["report"]["result_json"])
            if report_type == "alerts_summary": self.assertEqual(result["by_state"], {"Anulado": 1})
            elif report_type == "response_times": self.assertEqual(result["by_priority"], {})
            else:
                row = result["rows"][0]
                self.assertEqual((row["resolved"], row["cancelled"], row["active"], row["reassigned"]), (0, 1, 0, 0))
                self.assertIsNone(row["avg_response_minutes"])

    def test_state_migration_is_incremental_and_idempotent(self):
        migration = Path(__file__).resolve().parents[1] / "migrations" / "20261003_cancel_alerts.sql"
        with sqlite3.connect(":memory:") as connection:
            connection.execute("CREATE TABLE states (id INTEGER PRIMARY KEY, name TEXT UNIQUE, type TEXT, description TEXT)")
            connection.execute("INSERT INTO states (name,type) VALUES ('Cerrado','alert')")
            connection.commit()
            for _ in range(2): connection.executescript(migration.read_text(encoding="utf-8"))
            self.assertEqual(connection.execute("SELECT name,type FROM states ORDER BY id").fetchall(), [("Cerrado", "alert"), ("Anulado", "alert")])

    def test_reassignment_and_cancelled_performance_remain_separate_and_filterable(self):
        alert_id = self.alert(priority="high")
        previous_id = self.assign(alert_id)
        second_id, second = self.new_user(6, "Técnico")
        response = self.client.post("/api/assignments/", headers=self.admin,
            json={"alert_id": alert_id, "user_id": second_id})
        self.assertEqual(response.status_code, 201, response.get_json())
        self.assertEqual(self.cancel(alert_id, self.supervisor).status_code, 200)
        for priority, expected_rows in [("high", 2), ("low", 0)]:
            report_id = self.client.post("/api/reports/", headers=self.supervisor, json={
                "name": "Rendimiento filtrado", "type": "operator_performance",
                "filters": {"state": "Anulado", "priority": priority}}).get_json()["report"]["id"]
            generated = self.client.post(f"/api/reports/{report_id}/generate", headers=self.supervisor)
            self.assertEqual(generated.status_code, 200, generated.get_json())
            rows = json.loads(generated.get_json()["report"]["result_json"])["rows"]
            self.assertEqual(len(rows), expected_rows)
            if rows:
                by_user = {row["technician_id"]: row for row in rows}
                self.assertEqual(by_user[self.technician_id]["reassigned"], 1)
                self.assertEqual(by_user[self.technician_id]["cancelled"], 0)
                self.assertEqual(by_user[second_id]["reassigned"], 0)
                self.assertEqual(by_user[second_id]["cancelled"], 1)
        response = self.client.put(f"/api/assignments/{previous_id}", headers=self.technician,
                                  json={"notes": "No modificar tras anulacion"})
        self.assertEqual(response.status_code, 409, response.get_json())
        with self.app.app_context():
            old = db.session.get(Assignment, previous_id).to_dict()
            self.assertEqual(old["status"], "Reasignada")
            self.assertEqual(old["alert_state"], "Anulado")

    def test_inactive_account_or_profile_cannot_use_prior_supervisor_token(self):
        alert_id = self.alert()
        response = self.client.put(f"/api/users/{self.supervisor_id}", headers=self.admin,
                                  json={"state_id": self.inactive})
        self.assertEqual(response.status_code, 200, response.get_json())
        self.assertEqual(self.cancel(alert_id, self.supervisor).status_code, 401)
        with self.app.app_context():
            db.session.get(Profile, self.roles["Supervisor"]).state_id = self.inactive
            db.session.commit()
        self.assertEqual(self.cancel(alert_id, self.supervisor).status_code, 401)


if __name__ == "__main__":
    unittest.main()
