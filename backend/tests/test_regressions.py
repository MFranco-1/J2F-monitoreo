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
        technician = self.user()
        self.user(2, active=False)
        alert_id = self.alert()
        first = self.client.post("/api/assignments/auto-assign", headers=self.admin, json={"alert_id": alert_id})
        self.assertEqual(first.status_code, 201, first.get_json())
        self.assertEqual(first.get_json()["technician"]["id"], technician)
        second = self.client.post("/api/assignments/auto-assign", headers=self.admin, json={"alert_id": alert_id})
        self.assertEqual(second.status_code, 409)
        with self.app.app_context():
            self.assertEqual(Assignment.query.filter_by(alert_id=alert_id, completed_at=None).count(), 1)

    def test_auto_assignment_does_not_fall_back_to_admin(self):
        response = self.client.post("/api/assignments/auto-assign", headers=self.admin, json={"alert_id": self.alert()})
        self.assertEqual(response.status_code, 409)

    def test_operator_assigns_alerts_only_to_technicians(self):
        technician_id = self.user()
        operator_id = self.user(2, role="Operador")
        operator_headers = self.headers(self.login("test2@example.invalid")["access_token"])

        available = self.client.get("/api/assignments/technicians", headers=operator_headers)
        self.assertEqual(available.status_code, 200, available.get_json())
        self.assertEqual([item["id"] for item in available.get_json()["technicians"]], [technician_id])

        manual = self.client.post("/api/assignments/", headers=operator_headers,
                                  json={"alert_id": self.alert(), "user_id": technician_id})
        self.assertEqual(manual.status_code, 201, manual.get_json())

        invalid_target = self.client.post("/api/assignments/", headers=operator_headers,
                                          json={"alert_id": self.alert(), "user_id": operator_id})
        self.assertEqual(invalid_target.status_code, 400, invalid_target.get_json())

        automatic = self.client.post("/api/assignments/auto-assign", headers=operator_headers,
                                     json={"alert_id": self.alert()})
        self.assertEqual(automatic.status_code, 201, automatic.get_json())
        self.assertEqual(automatic.get_json()["technician"]["id"], technician_id)

        technician_headers = self.headers(self.login("test1@example.invalid")["access_token"])
        forbidden = self.client.post("/api/assignments/auto-assign", headers=technician_headers,
                                     json={"alert_id": self.alert()})
        self.assertEqual(forbidden.status_code, 403, forbidden.get_json())

    def test_supervisor_can_assign_but_cannot_attend_as_technician(self):
        technician_id = self.user()
        self.user(2, role="Supervisor")
        supervisor_headers = self.headers(self.login("test2@example.invalid")["access_token"])
        alert_id = self.alert()

        assigned = self.client.post("/api/assignments/", headers=supervisor_headers,
                                    json={"alert_id": alert_id, "user_id": technician_id})
        self.assertEqual(assigned.status_code, 201, assigned.get_json())
        forbidden = self.client.put(f"/api/alerts/{alert_id}", headers=supervisor_headers,
                                    json={"state_name": "Cerrado"})
        self.assertEqual(forbidden.status_code, 403, forbidden.get_json())

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
            self.assertEqual(entry.profile_id, self.admin_profile)

    def test_other_technician_cannot_edit_attention(self):
        a = self.user()
        self.user(2)
        headers = self.headers(self.login("test2@example.invalid")["access_token"])
        alert_id = self.alert()
        assignment = self.assign(alert_id, a)
        self.assertEqual(self.client.put(f"/api/assignments/{assignment}", headers=headers, json={"notes": "Cambio"}).status_code, 403)
        self.assertEqual(self.client.put(f"/api/alerts/{alert_id}", headers=headers, json={"state_name": "Cerrado"}).status_code, 403)

    def test_assigned_technician_can_close_own_alert(self):
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
            "/admin/menu-options": "ADMINISTRACIÓN", "/master-data": "ADMINISTRACIÓN",
        }
        self.assertEqual(set(by_url), set(expected))
        self.assertTrue(all(by_url[url]["parent"]["name"] == parent
                            for url, parent in expected.items()))
        self.assertTrue(all("Administrador" in [profile["name"] for profile in option["profiles"]]
                            for option in by_url.values()))

    def test_navigation_only_contains_allowed_active_options(self):
        user_id = self.user()
        headers = self.headers(self.login("test1@example.invalid")["access_token"])
        with self.app.app_context():
            profile_id = db.session.get(User, user_id).profile_id
        for name, profile_ids, state_id in [("Permitido", [profile_id], self.active), ("Privado", [], self.active), ("Inactivo", [profile_id], self.inactive)]:
            self.client.post("/api/menu-options/", headers=self.admin, json={"name": name, "url": "/alerts", "profile_ids": profile_ids, "state_id": state_id})
        response = self.client.get("/api/menu-options/?navigation=true", headers=headers)
        self.assertTrue(response.get_json()["configured"])
        names = [o["name"] for o in response.get_json()["menu_options"]]
        self.assertIn("Permitido", names)
        self.assertNotIn("Privado", names)
        self.assertNotIn("Inactivo", names)
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

    def test_profile_assignments_are_changed_and_at_least_one_is_required(self):
        user_id = self.user()
        tokens = self.login("test1@example.invalid")
        with self.app.app_context():
            initial_profile = db.session.get(User, user_id).profile_id
        url = f"/api/users/{user_id}"
        result = self.client.put(url, headers=self.admin, json={"profile_ids": [self.admin_profile]})
        self.assertEqual(result.status_code, 200, result.get_json())
        self.assertEqual(result.get_json()["user"]["profile"]["id"], self.admin_profile)
        self.assertEqual([p["id"] for p in result.get_json()["user"]["profiles"]], [self.admin_profile])
        self.assertEqual(self.client.get("/api/auth/me", headers=self.headers(tokens["access_token"])).status_code, 401)
        result = self.client.put(url, headers=self.admin, json={"profile_ids": []})
        self.assertEqual(result.status_code, 400, result.get_json())
        self.assertEqual(self.client.put(url, headers=self.admin, json={"profile_ids": [initial_profile]}).status_code, 200)
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
        for payload in [{"profile_ids": [999999]}, {"first_name": "Nombre"},
                        {"profile_id": 999999}, {"full_name": "x" * 151}]:
            with self.subTest(payload=payload):
                response = self.client.put(f"/api/users/{user_id}", headers=self.admin, json=payload)
                self.assertEqual(response.status_code, 400, response.get_json())

    def test_multprofile_login_requires_selection_and_temp_token_is_limited(self):
        user_id = self.user()
        with self.app.app_context():
            user = db.session.get(User, user_id)
            user.profiles = [Profile.query.filter_by(name="Técnico").one(),
                             db.session.get(Profile, self.admin_profile)]
            db.session.commit()
        response = self.client.post("/api/auth/login", json={"identifier": "test1@example.invalid",
                                                               "password": "Test-password-123!"})
        body = response.get_json()
        self.assertTrue(body["requires_profile_selection"])
        self.assertNotIn("refresh_token", body)
        temporary = self.headers(body["access_token"])
        self.assertEqual(self.client.get("/api/alerts/metrics", headers=temporary).status_code, 401)
        selected = self.client.post("/api/auth/select-profile", headers=temporary,
                                    json={"profile_id": self.admin_profile})
        self.assertEqual(selected.status_code, 200, selected.get_json())
        self.assertEqual(selected.get_json()["user"]["profile"]["name"], "Administrador")
        from flask_jwt_extended import decode_token
        with self.app.app_context():
            payload = decode_token(selected.get_json()["access_token"])
        self.assertEqual(payload["active_profile_id"], self.admin_profile)
        self.assertEqual(payload["active_profile_name"], "Administrador")

    def test_profile_selection_rejects_unassigned_and_inactive_profiles(self):
        user_id = self.user()
        with self.app.app_context():
            user = db.session.get(User, user_id)
            inactive = Profile(name="Perfil inactivo de prueba", state_id=self.inactive)
            db.session.add(inactive); db.session.flush()
            user.profiles = [Profile.query.filter_by(name="Técnico").one(),
                             db.session.get(Profile, self.admin_profile), inactive]
            db.session.commit(); inactive_id = inactive.id
        login = self.client.post("/api/auth/login", json={"identifier":"test1@example.invalid",
            "password":"Test-password-123!"}).get_json()
        token = self.headers(login["access_token"])
        self.assertEqual(self.client.post("/api/auth/select-profile", headers=token,
                                          json={"profile_id": 99999}).status_code, 403)
        self.assertEqual(self.client.post("/api/auth/select-profile", headers=token,
                                          json={"profile_id": inactive_id}).status_code, 403)

    def test_switch_and_refresh_preserve_only_active_profile_permissions(self):
        user_id = self.user()
        with self.app.app_context():
            technician_id = Profile.query.filter_by(name="Técnico").one().id
            user = db.session.get(User, user_id)
            user.profiles = [db.session.get(Profile, technician_id), db.session.get(Profile, self.admin_profile)]
            db.session.commit()
        pending = self.client.post("/api/auth/login", json={"identifier":"test1@example.invalid",
            "password":"Test-password-123!"}).get_json()
        admin_session = self.client.post("/api/auth/select-profile", headers=self.headers(pending["access_token"]),
                                         json={"profile_id":self.admin_profile}).get_json()
        self.assertEqual(self.client.get("/api/users/", headers=self.headers(admin_session["access_token"])).status_code, 200)
        switched = self.client.post("/api/auth/select-profile", headers=self.headers(admin_session["access_token"]),
                                    json={"profile_id":technician_id}).get_json()
        technician_access = self.headers(switched["access_token"])
        self.assertEqual(self.client.get("/api/users/", headers=technician_access).status_code, 403)
        refreshed = self.client.post("/api/auth/refresh", headers=self.headers(switched["refresh_token"])).get_json()
        self.assertEqual(self.client.get("/api/users/", headers=self.headers(refreshed["access_token"])).status_code, 403)

    def test_user_multprofile_create_and_partial_edit_preserves_assignments(self):
        with self.app.app_context():
            technician_id = Profile.query.filter_by(name="Técnico").one().id
        response = self.client.post("/api/users/", headers=self.admin, json={"dni":"87654321",
            "full_name":"Usuario Multiperfil", "email":"multi@example.invalid", "password":"Password-123!",
            "state_id":self.active, "profile_ids":[technician_id,self.admin_profile]})
        self.assertEqual(response.status_code, 201, response.get_json())
        user = response.get_json()["user"]
        self.assertEqual(user["profile_id"], technician_id)
        self.assertEqual({p["id"] for p in user["profiles"]}, {technician_id,self.admin_profile})
        edited = self.client.put(f"/api/users/{user['id']}", headers=self.admin,
                                 json={"full_name":"Nombre actualizado"}).get_json()["user"]
        self.assertEqual({p["id"] for p in edited["profiles"]}, {technician_id,self.admin_profile})

    def test_master_data_relations_and_alert_compatibility(self):
        client = self.client.post("/api/master-data/clients/", headers=self.admin, json={
            "document_type":"RUC", "document_number":"20123456789", "business_name":"Cliente Prueba",
            "state_id":self.active}).get_json()["record"]
        edited_client = self.client.put(f"/api/master-data/clients/{client['id']}", headers=self.admin,
                                        json={"contact_name":"Central de operaciones"})
        self.assertEqual(edited_client.status_code, 200, edited_client.get_json())
        self.assertEqual(edited_client.get_json()["record"]["contact_name"], "Central de operaciones")
        vehicle_response = self.client.post("/api/master-data/vehicles/", headers=self.admin, json={
            "client_id":client["id"], "plate":"ABC-123", "brand":"Toyota", "model":"Hilux",
            "state_id":self.active})
        self.assertEqual(vehicle_response.status_code, 201, vehicle_response.get_json())
        vehicle = vehicle_response.get_json()["record"]
        self.assertEqual(vehicle["client"]["id"], client["id"])
        self.assertEqual(self.client.post("/api/master-data/vehicles/", headers=self.admin, json={
            "client_id":client["id"], "plate":"abc-123", "state_id":self.active}).status_code, 400)
        device = self.client.post("/api/master-data/gps-devices/", headers=self.admin, json={
            "vehicle_id":vehicle["id"], "imei":"123456789012345", "state_id":self.active}).get_json()["record"]
        self.assertEqual(device["vehicle"]["id"], vehicle["id"])
        self.assertEqual(self.client.post("/api/master-data/gps-devices/", headers=self.admin, json={
            "vehicle_id":vehicle["id"], "imei":"123456789012345", "state_id":self.active}).status_code, 400)
        with self.app.app_context():
            event_id = db.session.query(__import__('app.models.master_data', fromlist=['EventType']).EventType.id).first()[0]
        alert = self.client.post("/api/alerts/", headers=self.admin, json={"title":"GPS", "client_id":client["id"],
            "vehicle_id":vehicle["id"], "gps_device_id":device["id"], "event_type_id":event_id})
        self.assertEqual(alert.status_code, 201, alert.get_json())
        self.assertEqual(alert.get_json()["alert"]["client"]["id"], client["id"])
        self.assertEqual(self.client.post("/api/alerts/", headers=self.admin,
                                         json={"title":"Alerta anterior"}).status_code, 201)

    def test_alert_rejects_inconsistent_client_vehicle_device(self):
        def client(number):
            return self.client.post("/api/master-data/clients/", headers=self.admin, json={
                "document_type":"RUC", "document_number":number, "business_name":number,
                "state_id":self.active}).get_json()["record"]
        first, second = client("20111111111"), client("20222222222")
        vehicle = self.client.post("/api/master-data/vehicles/", headers=self.admin, json={
            "client_id":first["id"], "plate":"XYZ-999", "state_id":self.active}).get_json()["record"]
        result = self.client.post("/api/alerts/", headers=self.admin, json={"title":"Inválida",
            "client_id":second["id"], "vehicle_id":vehicle["id"]})
        self.assertEqual(result.status_code, 400)

    def test_alerts_filter_by_client_and_vehicle_without_hiding_default_results(self):
        def create_client(number):
            return self.client.post("/api/master-data/clients/", headers=self.admin, json={
                "document_type": "RUC", "document_number": number,
                "business_name": f"Cliente {number}", "state_id": self.active,
            }).get_json()["record"]

        def create_vehicle(client_id, plate):
            return self.client.post("/api/master-data/vehicles/", headers=self.admin, json={
                "client_id": client_id, "plate": plate, "state_id": self.active,
            }).get_json()["record"]

        first, second = create_client("20500000001"), create_client("20500000002")
        first_vehicle = create_vehicle(first["id"], "CLI-001")
        second_vehicle = create_vehicle(first["id"], "CLI-002")
        other_vehicle = create_vehicle(second["id"], "CLI-003")
        for title, client, vehicle in [
            ("Primera", first, first_vehicle), ("Segunda", first, second_vehicle),
            ("Tercera", second, other_vehicle),
        ]:
            response = self.client.post("/api/alerts/", headers=self.admin, json={
                "title": title, "client_id": client["id"], "vehicle_id": vehicle["id"],
            })
            self.assertEqual(response.status_code, 201, response.get_json())

        all_alerts = self.client.get("/api/alerts/?per_page=200", headers=self.admin).get_json()
        self.assertGreaterEqual(all_alerts["total"], 3)
        by_client = self.client.get(
            f"/api/alerts/?client_id={first['id']}&per_page=200", headers=self.admin).get_json()
        self.assertEqual(by_client["total"], 2)
        self.assertTrue(all(item["client"]["id"] == first["id"] for item in by_client["alerts"]))
        by_vehicle = self.client.get(
            f"/api/alerts/?vehicle_id={first_vehicle['id']}&per_page=200", headers=self.admin).get_json()
        self.assertEqual(by_vehicle["total"], 1)
        self.assertEqual(by_vehicle["alerts"][0]["vehicle"]["id"], first_vehicle["id"])
        inconsistent = self.client.get(
            f"/api/alerts/?client_id={first['id']}&vehicle_id={other_vehicle['id']}",
            headers=self.admin,
        )
        self.assertEqual(inconsistent.status_code, 400)


class InstalledSchemaTests(unittest.TestCase):
    def test_models_match_the_incremental_fourteen_table_schema(self):
        from sqlalchemy.dialects import postgresql
        # Contrato independiente: estructura enviada por el usuario desde su PostgreSQL.
        definitions = {
            "states": "id INTEGER!; name VARCHAR(50)!; type VARCHAR(20)!; description VARCHAR(255); created_at TIMESTAMP",
            "profiles": "id INTEGER!; name VARCHAR(100)!; description VARCHAR(255); state_id INTEGER!; created_at TIMESTAMP; updated_at TIMESTAMP",
            "menu_options": "id INTEGER!; name VARCHAR(100)!; url VARCHAR(255); icon VARCHAR(100); parent_id INTEGER; order INTEGER; state_id INTEGER!; created_at TIMESTAMP; updated_at TIMESTAMP",
            "profile_menu_option": "profile_id INTEGER!; menu_option_id INTEGER!",
            "user_profile": "user_id INTEGER!; profile_id INTEGER!",
            "users": "id INTEGER!; dni VARCHAR(20)!; full_name VARCHAR(150)!; email VARCHAR(150)!; password_hash VARCHAR(256)!; profile_id INTEGER; state_id INTEGER!; last_login TIMESTAMP; created_at TIMESTAMP; updated_at TIMESTAMP",
            "alerts": "id INTEGER!; title VARCHAR(200)!; description TEXT; priority VARCHAR(20)!; service_type VARCHAR(100); location VARCHAR(200); source VARCHAR(100); state_id INTEGER!; vehicle_id INTEGER; gps_device_id INTEGER; event_type_id INTEGER; created_by INTEGER; opened_at TIMESTAMP; acknowledged_at TIMESTAMP; resolved_at TIMESTAMP; created_at TIMESTAMP; updated_at TIMESTAMP",
            "reports": "id INTEGER!; name VARCHAR(200)!; type VARCHAR(50)!; description TEXT; filters_json TEXT; date_range_start TIMESTAMP; date_range_end TIMESTAMP; generated_by INTEGER; result_json TEXT; created_at TIMESTAMP",
            "assignments": "id INTEGER!; alert_id INTEGER!; user_id INTEGER!; notes TEXT; assignment_type VARCHAR(20); assigned_at TIMESTAMP; completed_at TIMESTAMP; response_time_minutes DOUBLE PRECISION",
            "history": "id INTEGER!; alert_id INTEGER!; user_id INTEGER; profile_id INTEGER; action VARCHAR(50)!; previous_state VARCHAR(100); new_state VARCHAR(100); detail TEXT; timestamp TIMESTAMP",
            "clients": "id INTEGER!; document_type VARCHAR(20)!; document_number VARCHAR(30)!; business_name VARCHAR(180)!; contact_name VARCHAR(150); phone VARCHAR(30); email VARCHAR(150); address VARCHAR(255); state_id INTEGER!; created_at TIMESTAMP; updated_at TIMESTAMP",
            "vehicles": "id INTEGER!; client_id INTEGER!; plate VARCHAR(20)!; brand VARCHAR(100); model VARCHAR(100); color VARCHAR(50); vehicle_type VARCHAR(80); state_id INTEGER!; created_at TIMESTAMP; updated_at TIMESTAMP",
            "gps_devices": "id INTEGER!; vehicle_id INTEGER!; imei VARCHAR(40)!; serial_number VARCHAR(80); model VARCHAR(100); provider VARCHAR(100); sim_number VARCHAR(30); state_id INTEGER!; created_at TIMESTAMP; updated_at TIMESTAMP",
            "event_types": "id INTEGER!; code VARCHAR(50)!; name VARCHAR(150)!; description TEXT; default_priority VARCHAR(20)!; generates_alert BOOLEAN!; expected_action TEXT; state_id INTEGER!; created_at TIMESTAMP; updated_at TIMESTAMP",
        }
        relations = {
            "states": set(), "profiles": {("state_id", "states.id")},
            "menu_options": {("parent_id", "menu_options.id"), ("state_id", "states.id")},
            "profile_menu_option": {("profile_id", "profiles.id"), ("menu_option_id", "menu_options.id")},
            "user_profile": {("user_id", "users.id"), ("profile_id", "profiles.id")},
            "users": {("profile_id", "profiles.id"), ("state_id", "states.id")},
            "alerts": {("created_by", "users.id"), ("state_id", "states.id"), ("vehicle_id", "vehicles.id"), ("gps_device_id", "gps_devices.id"), ("event_type_id", "event_types.id")},
            "reports": {("generated_by", "users.id")},
            "assignments": {("alert_id", "alerts.id"), ("user_id", "users.id")},
            "history": {("alert_id", "alerts.id"), ("user_id", "users.id"), ("profile_id", "profiles.id")},
            "clients": {("state_id", "states.id")},
            "vehicles": {("client_id", "clients.id"), ("state_id", "states.id")},
            "gps_devices": {("vehicle_id", "vehicles.id"), ("state_id", "states.id")},
            "event_types": {("state_id", "states.id")},
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
                    (["profile_id", "menu_option_id"] if name == "profile_menu_option" else
                     ["user_id", "profile_id"] if name == "user_profile" else ["id"]))


class MigrationScriptTests(unittest.TestCase):
    def test_single_migration_is_safe_idempotent_and_includes_required_seeds(self):
        path = Path(__file__).resolve().parents[2] / "j2f_modulo_usuarios.sql"
        self.assertTrue(path.exists())
        sql = path.read_text(encoding="utf8")
        executable = "\n".join(line for line in sql.splitlines() if not line.lstrip().startswith("--"))
        self.assertNotRegex(executable.lower(), r"\b(drop|truncate)\b")
        lowered = sql.lower()
        self.assertIn("select id, profile_id from users", lowered)
        self.assertIn("on conflict (user_id, profile_id) do nothing", lowered)
        self.assertIn("j2f-demo-003", lowered)
        self.assertIn("datos de prueba j2f", lowered)
        self.assertGreaterEqual(lowered.count("where not exists"), 4)
        self.assertGreaterEqual(lowered.count("on conflict"), 3)


if __name__ == "__main__":
    unittest.main()
