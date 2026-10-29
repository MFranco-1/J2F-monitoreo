"""HU-12: exportación de resultados persistidos y permisos, solo SQLite."""
import csv
import io
import json
import unittest
from app import create_app, db
from app.models import History, Profile, Report, State, User


class ReportExportTests(unittest.TestCase):
    def setUp(self):
        self.app = create_app('testing')
        self.client = self.app.test_client()
        self.admin = self.login('admin@j2f.com', 'Admin@J2F2024')

    def tearDown(self):
        with self.app.app_context():
            db.session.remove(); db.engine.dispose()

    def login(self, email, password='Password-123!'):
        response = self.client.post('/api/auth/login', json={'identifier': email, 'password': password})
        self.assertEqual(response.status_code, 200, response.get_json())
        return {'Authorization': 'Bearer ' + response.get_json()['access_token']}

    def actor(self, role, index):
        with self.app.app_context():
            user = User(dni=f'{index:08d}', full_name=f'Persona {role}', email=f'report{index}@example.invalid',
                        state_id=State.query.filter_by(name='Activo', type='user').one().id,
                        profile_id=Profile.query.filter_by(name=role).one().id)
            user.set_password('Password-123!'); db.session.add(user); db.session.commit()
        return self.login(f'report{index}@example.invalid')

    def report(self, kind='alerts_summary', **extra):
        result = self.client.post('/api/reports/', headers=self.admin, json={
            'name': 'Reporte de atención y señal', 'type': kind, **extra})
        self.assertEqual(result.status_code, 201, result.get_json())
        return result.get_json()['report']['id']

    def test_each_report_type_exports_csv_and_json_without_changing_snapshot_or_history(self):
        for kind in ('alerts_summary', 'operator_performance', 'response_times'):
            with self.subTest(kind=kind):
                report_id = self.report(kind, filters={'priority': 'high'})
                generated = self.client.post(f'/api/reports/{report_id}/generate', headers=self.admin)
                self.assertEqual(generated.status_code, 200, generated.get_json())
                snapshot = generated.get_json()['report']['result_json']
                with self.app.app_context():
                    before = History.query.count()
                csv_response = self.client.get(f'/api/reports/{report_id}/export?format=csv', headers=self.admin)
                self.assertEqual(csv_response.status_code, 200)
                self.assertIn('attachment;', csv_response.headers['Content-Disposition'])
                self.assertIn('text/csv', csv_response.content_type)
                rows = list(csv.reader(io.StringIO(csv_response.data.decode('utf-8-sig'))))
                self.assertIn(['Prioridad', 'Alta'], rows)
                self.assertIn(['Generado por', 'Administrador J2F'], rows)
                self.assertEqual(csv_response.headers['Cache-Control'], 'no-store')
                exported = self.client.get(f'/api/reports/{report_id}/export?format=json', headers=self.admin)
                self.assertEqual(exported.status_code, 200)
                self.assertEqual(exported.get_json()['result'], json.loads(snapshot))
                with self.app.app_context():
                    self.assertEqual(db.session.get(Report, report_id).result_json, snapshot)
                    self.assertEqual(History.query.count(), before)

    def test_supervisor_generation_records_actual_actor_without_replacing_creator(self):
        supervisor = self.actor('Supervisor', 1)
        report_id = self.report(date_range_start='2026-01-01', date_range_end='2026-01-31')
        response = self.client.post(f'/api/reports/{report_id}/generate', headers=supervisor)
        self.assertEqual(response.status_code, 200, response.get_json())
        report = response.get_json()['report']
        result = json.loads(report['result_json'])
        self.assertEqual(report['generator']['full_name'], 'Administrador J2F')
        self.assertEqual(result['generated_by']['full_name'], 'Persona Supervisor')
        self.assertTrue(result['generated_at'])
        self.assertEqual(result['date_range']['start'], '2026-01-01T00:00:00Z')
        self.assertEqual(result['date_range']['end'], '2026-01-31T23:59:59.999999Z')
        self.assertEqual(self.client.get(f'/api/reports/{report_id}/export', headers=supervisor).status_code, 200)

    def test_operator_technician_anonymous_cannot_export_or_generate(self):
        report_id = self.report()
        for role, index in (('Operador', 1), ('Técnico', 2)):
            headers = self.actor(role, index)
            self.assertEqual(self.client.get(f'/api/reports/{report_id}/export', headers=headers).status_code, 403)
            self.assertEqual(self.client.post(f'/api/reports/{report_id}/generate', headers=headers).status_code, 403)
        self.assertEqual(self.client.get(f'/api/reports/{report_id}/export').status_code, 401)

    def test_no_result_bad_json_and_unsupported_format_do_not_crash(self):
        report_id = self.report()
        self.assertEqual(self.client.get(f'/api/reports/{report_id}/export', headers=self.admin).status_code, 409)
        self.assertEqual(self.client.get(f'/api/reports/{report_id}/export?format=pdf', headers=self.admin).status_code, 400)
        with self.app.app_context():
            db.session.get(Report, report_id).result_json = '{invalid'
            db.session.commit()
        self.assertEqual(self.client.get(f'/api/reports/{report_id}/export', headers=self.admin).status_code, 409)
        self.assertEqual(self.client.get('/api/reports/999999/export', headers=self.admin).status_code, 404)

    def test_csv_escapes_formulas_without_losing_unicode_or_json_original(self):
        name = '=SUM(1,2) Atención de vehículos'
        report_id = self.report(name=name)
        self.client.post(f'/api/reports/{report_id}/generate', headers=self.admin)
        response = self.client.get(f'/api/reports/{report_id}/export', headers=self.admin)
        rows = list(csv.reader(io.StringIO(response.data.decode('utf-8-sig'))))
        self.assertEqual(rows[0], ['Reporte', "'" + name])
        exported = self.client.get(f'/api/reports/{report_id}/export?format=json', headers=self.admin).get_json()
        self.assertEqual(exported['report']['name'], name)

    def test_malformed_nested_results_return_conflict_instead_of_server_error(self):
        report_id = self.report()
        for result in (
            {'type': 'alerts_summary', 'by_priority': []},
            {'type': 'alerts_summary', 'generated_by': 'Autor'},
            {'type': 'operator_performance', 'rows': [None]},
            {'type': 'response_times', 'by_priority': {'high': 1}},
        ):
            with self.subTest(result=result):
                with self.app.app_context():
                    db.session.get(Report, report_id).result_json = json.dumps(result)
                    db.session.commit()
                for export_format in ('csv', 'json'):
                    response = self.client.get(f'/api/reports/{report_id}/export?format={export_format}',
                                               headers=self.admin)
                    self.assertEqual(response.status_code, 409)
                with self.app.app_context():
                    self.assertEqual(json.loads(db.session.get(Report, report_id).result_json), result)

    def test_legacy_result_does_not_invent_generation_author(self):
        report_id = self.report()
        with self.app.app_context():
            db.session.get(Report, report_id).result_json = json.dumps({
                'type': 'alerts_summary', 'total_alerts': 0, 'by_priority': {}, 'by_state': {}, 'filters': {}})
            db.session.commit()
        response = self.client.get(f'/api/reports/{report_id}/export', headers=self.admin)
        rows = list(csv.reader(io.StringIO(response.data.decode('utf-8-sig'))))
        self.assertIn(['Generado por', 'Autor de generación no documentado'], rows)
