"""Regresiones de permisos, sesiones y atención. Solo SQLite temporal."""
import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch
from sqlalchemy import text, inspect
from app import create_app, db
from app.config import TestingConfig
from app.models import User, Profile, State, Alert, Assignment, History, MenuOption
from app.datetime_utils import utcnow


class RegressionTests(unittest.TestCase):
    def setUp(self):
        self.app = create_app("testing")
        self.client = self.app.test_client()
        with self.app.app_context():
            db.session.execute(text("PRAGMA foreign_keys=ON"))
            db.session.commit()
            self.active = State.query.filter_by(name="Activo").one().id
            self.inactive = State.query.filter_by(name="Inactivo").one().id
            self.admin_profile = Profile.query.filter_by(name="Administrador").one().id
        self.admin_tokens = self.login("admin@j2f.com", "Admin@J2F2024")
        self.admin = self.headers(self.admin_tokens["access_token"])

    def tearDown(self):
        with self.app.app_context():
            db.session.remove()
            db.engine.dispose()

    @staticmethod
    def headers(token):
        return {"Authorization": "Bearer " + token}

    def login(self, email, password="Test-password-123!"):
        response = self.client.post("/api/auth/login", json={"identifier": email, "password": password})
        self.assertEqual(response.status_code, 200, response.get_json())
        return response.get_json()

    def user(self, n=1, role="Técnico", active=True):
        with self.app.app_context():
            profile = Profile.query.filter_by(name=role).first()
            if not profile:
                profile = Profile(name=role, state_id=self.active)
                db.session.add(profile)
                db.session.flush()
            user = User(dni=f"{n:08d}", full_name=f"Usuario Prueba {n}", email=f"test{n}@example.invalid",
                        state_id=self.active if active else self.inactive, profile_id=profile.id)
            user.set_password("Test-password-123!")
            db.session.add(user)
            db.session.commit()
            return user.id

    def alert(self):
        response = self.client.post("/api/alerts/", headers=self.admin, json={"title": "Evento de prueba"})
        self.assertEqual(response.status_code, 201, response.get_json())
        return response.get_json()["alert"]["id"]

    def assign(self, alert_id, user_id):
        response = self.client.post("/api/assignments/", headers=self.admin,
                                    json={"alert_id": alert_id, "user_id": user_id})
        self.assertEqual(response.status_code, 201, response.get_json())
        return response.get_json()["assignment"]["id"]

    def test_admin_crud_and_duplicate_dni(self):
        payload = {"dni": "11223344", "full_name": "Prueba", "email": "TEST@example.invalid",
                   "password": "Test-password-123!", "profile_id": self.admin_profile, "state_id": self.active}
        response = self.client.post("/api/users/", headers=self.admin, json=payload)
        self.assertEqual(response.status_code, 201, response.get_json())
        user_id = response.get_json()["user"]["id"]
        response = self.client.put(f"/api/users/{user_id}", headers=self.admin, json={"dni": "44332211"})
        self.assertEqual(response.get_json()["user"]["dni"], "44332211")
        payload["dni"] = "44332211"
        self.assertEqual(self.client.post("/api/users/", headers=self.admin, json=payload).status_code, 409)

    def test_technician_cannot_promote_self_or_modify_admin_cruds(self):
        user_id = self.user()
        headers = self.headers(self.login("test1@example.invalid")["access_token"])
        for method, path, body in [("put", f"/api/users/{user_id}", {"profile_id": self.admin_profile}),
                                   ("post", "/api/profiles/", {"name": "Otro", "state_id": self.active}),
                                   ("post", "/api/menu-options/", {"name": "Otro"})]:
            self.assertEqual(getattr(self.client, method)(path, headers=headers, json=body).status_code, 403)

    def test_anonymous_is_rejected(self):
        self.assertEqual(self.client.get("/api/users/").status_code, 401)

    def test_refresh_and_logout_invalidate_both_tokens(self):
        refresh = self.headers(self.admin_tokens["refresh_token"])
        self.assertEqual(self.client.post("/api/auth/refresh", headers=refresh, json={}).status_code, 200)
        self.assertEqual(self.client.post("/api/auth/logout", headers=refresh, json={}).status_code, 200)
        self.assertEqual(self.client.get("/api/auth/me", headers=self.admin).status_code, 401)
        self.assertEqual(self.client.post("/api/auth/refresh", headers=refresh, json={}).status_code, 401)

    def test_revocation_survives_app_restart(self):
        with tempfile.TemporaryDirectory() as directory:
            with patch.object(TestingConfig, "SQLALCHEMY_DATABASE_URI", "sqlite:///" + str(Path(directory) / "sessions.db")):
                first = create_app("testing")
                client = first.test_client()
                tokens = client.post("/api/auth/login", json={"identifier": "admin@j2f.com", "password": "Admin@J2F2024"}).get_json()
                headers = self.headers(tokens["access_token"])
                self.assertEqual(client.post("/api/auth/logout", headers=headers, json={}).status_code, 200)
                second = create_app("testing")
                self.assertEqual(second.test_client().get("/api/auth/me", headers=headers).status_code, 401)
                for app in (first, second):
                    with app.app_context():
                        db.session.remove()
                        db.engine.dispose()

    def test_disabled_user_cannot_access_refresh_or_restore_old_session(self):
        user_id = self.user()
        tokens = self.login("test1@example.invalid")
        self.client.put(f"/api/users/{user_id}", headers=self.admin, json={"state_id": self.inactive})
        self.assertEqual(self.client.get("/api/auth/me", headers=self.headers(tokens["access_token"])).status_code, 401)
        self.assertEqual(self.client.post("/api/auth/refresh", headers=self.headers(tokens["refresh_token"]), json={}).status_code, 401)
        self.client.put(f"/api/users/{user_id}", headers=self.admin, json={"state_id": self.active})
        self.assertEqual(self.client.get("/api/auth/me", headers=self.headers(tokens["access_token"])).status_code, 401)

    def test_password_change_revokes_old_session(self):
        user_id = self.user()
        tokens = self.login("test1@example.invalid")
        self.client.put(f"/api/users/{user_id}", headers=self.admin, json={"password": "Changed-password!"})
        self.assertEqual(self.client.get("/api/auth/me", headers=self.headers(tokens["access_token"])).status_code, 401)
        self.login("test1@example.invalid", "Changed-password!")

    def test_auto_assignment_selects_technician_once(self):
        operator = self.user()
        self.user(2, active=False)
        alert_id = self.alert()
        first = self.client.post("/api/assignments/auto-assign", headers=self.admin, json={"alert_id": alert_id})
        self.assertEqual(first.status_code, 201, first.get_json())
        self.assertEqual(first.get_json()["operator"]["id"], operator)
        second = self.client.post("/api/assignments/auto-assign", headers=self.admin, json={"alert_id": alert_id})
        self.assertEqual(second.status_code, 409)
        with self.app.app_context():
            self.assertEqual(Assignment.query.filter_by(alert_id=alert_id, completed_at=None).count(), 1)

    def test_auto_assignment_does_not_fall_back_to_admin(self):
        response = self.client.post("/api/assignments/auto-assign", headers=self.admin, json={"alert_id": self.alert()})
        self.assertEqual(response.status_code, 409)

    def test_reassignment_finishes_previous_assignment(self):
        a, b = self.user(), self.user(2)
        alert_id = self.alert()
        first = self.assign(alert_id, a)
        self.assign(alert_id, b)
        with self.app.app_context():
            self.assertIsNotNone(db.session.get(Assignment, first).completed_at)
            self.assertEqual(Assignment.query.filter_by(alert_id=alert_id, completed_at=None).count(), 1)
            self.assertEqual(db.session.get(Alert, alert_id).current_assignee.id, b)

    def test_closing_assigned_alert_uses_consistent_dates(self):
        alert_id = self.alert()
        self.assign(alert_id, self.user())
        response = self.client.put(f"/api/alerts/{alert_id}", headers=self.admin,
                                   json={"state_name": "Cerrado", "notes": "Resuelto"})
        self.assertEqual(response.status_code, 200, response.get_json())
        alert = response.get_json()["alert"]
        self.assertEqual(alert["state"]["name"], "Cerrado")
        self.assertIsNone(alert["current_assignee"])
        self.assertTrue(alert["resolved_at"].endswith("Z"))
        self.assertGreaterEqual(alert["response_time_minutes"], 0)

    def test_completion_is_idempotent_and_audited(self):
        alert_id = self.alert()
        assignment = self.assign(alert_id, self.user())
        url = f"/api/assignments/{assignment}"
        first = self.client.put(url, headers=self.admin, json={"complete": True})
        second = self.client.put(url, headers=self.admin, json={"complete": True})
        self.assertEqual(first.status_code, 200)
        self.assertEqual(first.get_json()["assignment"]["completed_at"], second.get_json()["assignment"]["completed_at"])
        with self.app.app_context():
            self.assertEqual(History.query.filter_by(alert_id=alert_id, action="updated").count(), 1)

    def test_notes_are_audited(self):
        alert_id = self.alert()
        assignment = self.assign(alert_id, self.user())
        self.client.put(f"/api/assignments/{assignment}", headers=self.admin, json={"notes": "Servicio recuperado"})
        with self.app.app_context():
            entry = History.query.filter_by(alert_id=alert_id, action="note_added").one()
            self.assertIn("Servicio recuperado", entry.detail)
            self.assertEqual(entry.user_id, 1)

    def test_other_operator_cannot_edit_attention(self):
        a = self.user()
        self.user(2)
        headers = self.headers(self.login("test2@example.invalid")["access_token"])
        alert_id = self.alert()
        assignment = self.assign(alert_id, a)
        self.assertEqual(self.client.put(f"/api/assignments/{assignment}", headers=headers, json={"notes": "Cambio"}).status_code, 403)
        self.assertEqual(self.client.put(f"/api/alerts/{alert_id}", headers=headers, json={"state_name": "Cerrado"}).status_code, 403)

    def test_assigned_operator_can_close_own_alert(self):
        user_id = self.user()
        headers = self.headers(self.login("test1@example.invalid")["access_token"])
        alert_id = self.alert()
        self.assign(alert_id, user_id)
        self.assertEqual(self.client.put(f"/api/alerts/{alert_id}", headers=headers, json={"state_name": "Cerrado"}).status_code, 200)

    def test_delete_preserves_user_and_alert_history(self):
        user_id = self.user()
        alert_id = self.alert()
        self.assign(alert_id, user_id)
        self.client.put(f"/api/alerts/{alert_id}", headers=self.admin, json={"state_name": "Cerrado"})
        with self.app.app_context():
            count = History.query.filter_by(alert_id=alert_id).count()
        self.assertEqual(self.client.delete(f"/api/alerts/{alert_id}", headers=self.admin).status_code, 409)
        self.assertEqual(self.client.delete(f"/api/users/{user_id}", headers=self.admin).status_code, 200)
        with self.app.app_context():
            self.assertEqual(History.query.filter_by(alert_id=alert_id).count(), count)
            self.assertEqual(db.session.get(User, user_id).state.name, "Inactivo")

    def test_last_administrative_access_is_protected(self):
        self.assertEqual(self.client.delete("/api/users/1", headers=self.admin).status_code, 409)
        self.assertEqual(self.client.put(f"/api/profiles/{self.admin_profile}", headers=self.admin, json={"state_id": self.inactive}).status_code, 409)

    def test_invalid_payloads_return_json_400(self):
        cases = [("post", "/api/alerts/", {"title": "Prueba", "priority": "inventada"}),
                 ("post", "/api/profiles/", {"name": "Prueba", "state_id": 99999}),
                 ("post", "/api/menu-options/", {"name": "Prueba", "parent_id": "null"}),
                 ("post", "/api/users/", []),
                 ("get", "/api/alerts/?page=abc", None),
                 ("get", "/api/reports/history?date_from=invalid", None)]
        for method, url, body in cases:
            with self.subTest(url=url):
                result = getattr(self.client, method)(url, headers=self.admin, json=body) if method != "get" else self.client.get(url, headers=self.admin)
                self.assertEqual(result.status_code, 400, result.get_json())
                self.assertIn("error", result.get_json())

    def test_invalid_transition_does_not_save_other_changes(self):
        alert_id = self.alert()
        self.client.put(f"/api/alerts/{alert_id}", headers=self.admin, json={"state_name": "Cerrado"})
        result = self.client.put(f"/api/alerts/{alert_id}", headers=self.admin, json={"title": "No guardar", "state_name": "Abierto"})
        self.assertEqual(result.status_code, 422)
        with self.app.app_context():
            self.assertEqual(db.session.get(Alert, alert_id).title, "Evento de prueba")

    def test_menu_parent_and_cycle_validation(self):
        parent = self.client.post("/api/menu-options/", headers=self.admin, json={"name": "Raíz", "parent_id": None}).get_json()["menu_option"]
        child = self.client.post("/api/menu-options/", headers=self.admin, json={"name": "Hijo", "parent_id": parent["id"]}).get_json()["menu_option"]
        self.assertEqual(child["parent"]["name"], "Raíz")
        result = self.client.put(f"/api/menu-options/{parent['id']}", headers=self.admin, json={"parent_id": child["id"]})
        self.assertEqual(result.status_code, 400)

    def test_current_routes_are_registered_for_the_admin_profile(self):
        response = self.client.get("/api/menu-options/", headers=self.admin)
        options = response.get_json()["menu_options"]
        by_url = {option["url"]: option for option in options if option["url"]}
        expected = {
            "/dashboard": "MONITOREO", "/alerts": "MONITOREO", "/assignments": "MONITOREO",
            "/history": "SEGUIMIENTO", "/reports": "SEGUIMIENTO",
            "/admin/users": "ADMINISTRACIÓN", "/admin/profiles": "ADMINISTRACIÓN",
            "/admin/menu-options": "ADMINISTRACIÓN",
        }
        self.assertEqual(set(by_url), set(expected))
        self.assertTrue(all(by_url[url]["parent"]["name"] == parent
                            for url, parent in expected.items()))
        self.assertTrue(all([profile["name"] for profile in option["profiles"]] == ["Administrador"]
                            for option in options))

    def test_navigation_only_contains_allowed_active_options(self):
        user_id = self.user()
        headers = self.headers(self.login("test1@example.invalid")["access_token"])
        with self.app.app_context():
            profile_id = db.session.get(User, user_id).profile_id
        for name, profile_ids, state_id in [("Permitido", [profile_id], self.active), ("Privado", [], self.active), ("Inactivo", [profile_id], self.inactive)]:
            self.client.post("/api/menu-options/", headers=self.admin, json={"name": name, "url": "/alerts", "profile_ids": profile_ids, "state_id": state_id})
        response = self.client.get("/api/menu-options/?navigation=true", headers=headers)
        self.assertTrue(response.get_json()["configured"])
        self.assertEqual([o["name"] for o in response.get_json()["menu_options"]], ["Permitido"])
        self.assertEqual(self.client.get("/api/menu-options/", headers=headers).status_code, 403)

    def test_report_reopens_and_end_date_includes_full_day(self):
        self.alert()
        day = utcnow().date().isoformat()
        result = self.client.post("/api/reports/", headers=self.admin,
                                  json={"name": "Reporte prueba", "type": "alerts_summary", "date_range_start": day, "date_range_end": day})
        report_id = result.get_json()["report"]["id"]
        result = self.client.post(f"/api/reports/{report_id}/generate", headers=self.admin, json={})
        self.assertEqual(result.status_code, 200)
        listing = self.client.get("/api/reports/", headers=self.admin).get_json()["reports"]
        self.assertTrue(listing[0]["has_result"])
        detail = self.client.get(f"/api/reports/{report_id}", headers=self.admin).get_json()["report"]
        self.assertEqual(json.loads(detail["result_json"])["total_alerts"], 1)

    def test_invalid_report_dates_are_rejected(self):
        response = self.client.post("/api/reports/", headers=self.admin,
                                    json={"name": "Prueba", "type": "alerts_summary", "date_range_start": "invalid"})
        self.assertEqual(response.status_code, 400)


    def test_regular_startup_does_not_create_or_seed_tables(self):
        from types import SimpleNamespace
        configuration = SimpleNamespace(SQLALCHEMY_DATABASE_URI="sqlite:///:memory:",
            SQLALCHEMY_TRACK_MODIFICATIONS=False, TESTING=False, ENV="development",
            JWT_SECRET_KEY="isolated-test-key", SECRET_KEY="isolated-test-key")
        with patch("app.get_config", return_value=configuration):
            application = create_app("development")
        with application.app_context():
            self.assertEqual(inspect(db.engine).get_table_names(), [])
            db.session.remove()
            db.engine.dispose()

    def test_all_existing_report_types_generate(self):
        user_id = self.user()
        alert_id = self.alert()
        self.assign(alert_id, user_id)
        self.client.put(f"/api/alerts/{alert_id}", headers=self.admin, json={"state_name": "Cerrado"})
        for report_type in ["alerts_summary", "operator_performance", "response_times"]:
            with self.subTest(report_type=report_type):
                result = self.client.post("/api/reports/", headers=self.admin,
                    json={"name": report_type, "type": report_type})
                self.assertEqual(result.status_code, 201, result.get_json())
                report_id = result.get_json()["report"]["id"]
                result = self.client.post(f"/api/reports/{report_id}/generate", headers=self.admin, json={})
                self.assertEqual(result.status_code, 200, result.get_json())
                self.assertEqual(json.loads(result.get_json()["report"]["result_json"])["type"], report_type)

    def test_single_profile_is_changed_removed_and_restored(self):
        user_id = self.user()
        tokens = self.login("test1@example.invalid")
        with self.app.app_context():
            initial_profile = db.session.get(User, user_id).profile_id
        url = f"/api/users/{user_id}"
        result = self.client.put(url, headers=self.admin, json={"profile_id": self.admin_profile})
        self.assertEqual(result.status_code, 200, result.get_json())
        self.assertEqual(result.get_json()["user"]["profile"]["id"], self.admin_profile)
        self.assertNotIn("profiles", result.get_json()["user"])
        self.assertEqual(self.client.get("/api/auth/me", headers=self.headers(tokens["access_token"])).status_code, 401)
        result = self.client.put(url, headers=self.admin, json={"profile_id": None})
        self.assertEqual(result.status_code, 200, result.get_json())
        self.assertIsNone(result.get_json()["user"]["profile"])
        self.assertEqual(self.client.post("/api/auth/login", json={"identifier": "test1@example.invalid", "password": "Test-password-123!"}).status_code, 403)
        self.assertEqual(self.client.put(url, headers=self.admin, json={"profile_id": initial_profile}).status_code, 200)
        self.login("test1@example.invalid")

    def test_direct_profile_change_invalidates_both_tokens(self):
        user_id = self.user()
        tokens = self.login("test1@example.invalid")
        with self.app.app_context():
            # Cambio directo sin actualizar updated_at: el permiso firmado también debe invalidarse.
            db.session.execute(text("UPDATE users SET profile_id = :profile WHERE id = :id"),
                               {"profile": self.admin_profile, "id": user_id})
            db.session.commit()
        self.assertEqual(self.client.get("/api/auth/me", headers=self.headers(tokens["access_token"])).status_code, 401)
        self.assertEqual(self.client.post("/api/auth/refresh", headers=self.headers(tokens["refresh_token"]), json={}).status_code, 401)

    def test_registration_state_ids_are_not_assumed_to_be_one_or_two(self):
        with self.app.app_context():
            old = db.session.get(State, self.active)
            old.name = "Activo anterior"
            db.session.flush()
            state = State(id=77, name="Activo", type="user")
            db.session.add(state)
            db.session.flush()
            User.query.filter_by(state_id=self.active).update({"state_id": 77})
            Profile.query.filter_by(state_id=self.active).update({"state_id": 77})
            db.session.commit()
        self.admin = self.headers(self.login("admin@j2f.com", "Admin@J2F2024")["access_token"])
        result = self.client.get("/api/profiles/", headers=self.admin)
        self.assertIn(77, [state["id"] for state in result.get_json()["states"]])
        result = self.client.post("/api/users/", headers=self.admin, json={"dni": "78123456",
            "full_name": "Nombre completo conservado", "email": "state@example.invalid",
            "password": "Test-password-123!", "profile_id": self.admin_profile, "state_id": 77})
        self.assertEqual(result.status_code, 201, result.get_json())
        self.assertEqual(result.get_json()["user"]["state"]["name"], "Activo")
        self.login("state@example.invalid")

    def test_menu_order_profiles_and_existing_icon_are_preserved(self):
        user_id = self.user()
        with self.app.app_context():
            profile_id = db.session.get(User, user_id).profile_id
        result = self.client.post("/api/menu-options/", headers=self.admin, json={"name": "Atención",
            "url": "/alerts", "order": 7, "icon": "existing-icon", "profile_ids": [profile_id]})
        self.assertEqual(result.status_code, 201, result.get_json())
        menu_id = result.get_json()["menu_option"]["id"]
        result = self.client.put(f"/api/menu-options/{menu_id}", headers=self.admin,
            json={"order": 0, "profile_ids": [profile_id, self.admin_profile], "state_id": self.inactive})
        self.assertEqual(result.status_code, 200, result.get_json())
        menu = result.get_json()["menu_option"]
        self.assertEqual(menu["order"], 0)
        self.assertEqual(menu["icon"], "existing-icon")
        self.assertEqual(len(menu["profiles"]), 2)
        self.assertEqual(menu["state"]["name"], "Inactivo")
        invalid = self.client.post("/api/menu-options/", headers=self.admin, json={"name": "Inválido", "state_id": 0})
        self.assertEqual(invalid.status_code, 400)

    def test_incompatible_user_fields_are_not_silently_discarded(self):
        user_id = self.user()
        for payload in [{"profile_ids": [self.admin_profile]}, {"first_name": "Nombre"},
                        {"profile_id": 999999}, {"full_name": "x" * 151}]:
            with self.subTest(payload=payload):
                response = self.client.put(f"/api/users/{user_id}", headers=self.admin, json=payload)
                self.assertEqual(response.status_code, 400, response.get_json())


class InstalledSchemaTests(unittest.TestCase):
    def test_models_match_the_nine_tables_reported_from_postgresql(self):
        from sqlalchemy.dialects import postgresql
        # Contrato independiente: estructura enviada por el usuario desde su PostgreSQL.
        definitions = {
            "states": "id INTEGER!; name VARCHAR(50)!; type VARCHAR(20)!; description VARCHAR(255); created_at TIMESTAMP",
            "profiles": "id INTEGER!; name VARCHAR(100)!; description VARCHAR(255); state_id INTEGER!; created_at TIMESTAMP; updated_at TIMESTAMP",
            "menu_options": "id INTEGER!; name VARCHAR(100)!; url VARCHAR(255); icon VARCHAR(100); parent_id INTEGER; order INTEGER; state_id INTEGER!; created_at TIMESTAMP; updated_at TIMESTAMP",
            "profile_menu_option": "profile_id INTEGER!; menu_option_id INTEGER!",
            "users": "id INTEGER!; dni VARCHAR(20)!; full_name VARCHAR(150)!; email VARCHAR(150)!; password_hash VARCHAR(256)!; profile_id INTEGER; state_id INTEGER!; last_login TIMESTAMP; created_at TIMESTAMP; updated_at TIMESTAMP",
            "alerts": "id INTEGER!; title VARCHAR(200)!; description TEXT; priority VARCHAR(20)!; service_type VARCHAR(100); location VARCHAR(200); source VARCHAR(100); state_id INTEGER!; created_by INTEGER; opened_at TIMESTAMP; acknowledged_at TIMESTAMP; resolved_at TIMESTAMP; created_at TIMESTAMP; updated_at TIMESTAMP",
            "reports": "id INTEGER!; name VARCHAR(200)!; type VARCHAR(50)!; description TEXT; filters_json TEXT; date_range_start TIMESTAMP; date_range_end TIMESTAMP; generated_by INTEGER; result_json TEXT; created_at TIMESTAMP",
            "assignments": "id INTEGER!; alert_id INTEGER!; user_id INTEGER!; notes TEXT; assignment_type VARCHAR(20); assigned_at TIMESTAMP; completed_at TIMESTAMP; response_time_minutes DOUBLE PRECISION",
            "history": "id INTEGER!; alert_id INTEGER!; user_id INTEGER; action VARCHAR(50)!; previous_state VARCHAR(100); new_state VARCHAR(100); detail TEXT; timestamp TIMESTAMP",
        }
        relations = {
            "states": set(), "profiles": {("state_id", "states.id")},
            "menu_options": {("parent_id", "menu_options.id"), ("state_id", "states.id")},
            "profile_menu_option": {("profile_id", "profiles.id"), ("menu_option_id", "menu_options.id")},
            "users": {("profile_id", "profiles.id"), ("state_id", "states.id")},
            "alerts": {("created_by", "users.id"), ("state_id", "states.id")},
            "reports": {("generated_by", "users.id")},
            "assignments": {("alert_id", "alerts.id"), ("user_id", "users.id")},
            "history": {("alert_id", "alerts.id"), ("user_id", "users.id")},
        }
        self.assertEqual(set(db.metadata.tables), set(definitions))
        for name, definition in definitions.items():
            with self.subTest(table=name):
                expected = {}
                for field in definition.split(";"):
                    column, sql_type = field.strip().split(" ", 1)
                    expected[column] = (sql_type.rstrip("!"), not sql_type.endswith("!"))
                table = db.metadata.tables[name]
                actual = {}
                for column in table.columns:
                    sql_type = str(column.type.compile(dialect=postgresql.dialect()))
                    sql_type = {"TIMESTAMP WITHOUT TIME ZONE": "TIMESTAMP", "FLOAT": "DOUBLE PRECISION"}.get(sql_type, sql_type)
                    actual[column.name] = (sql_type, column.nullable)
                self.assertEqual(actual, expected)
                self.assertEqual({(fk.parent.name, fk.target_fullname) for fk in table.foreign_keys}, relations[name])
                self.assertEqual([column.name for column in table.primary_key.columns],
                    ["profile_id", "menu_option_id"] if name == "profile_menu_option" else ["id"])


if __name__ == "__main__":
    unittest.main()
