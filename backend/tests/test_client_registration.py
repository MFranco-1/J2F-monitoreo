"""Registro manual de clientes y GPS: pruebas SQLite, sin APIs ni Neon."""
import json
import unittest
from unittest.mock import patch
from app import create_app, db
from app.models import Profile, State, User
from app.models.master_data import Client


class ClientRegistrationTests(unittest.TestCase):
    def setUp(self):
        self.app = create_app("testing")
        self.client = self.app.test_client()
        tokens = self.client.post('/api/auth/login', json={
            'identifier': 'admin@j2f.com', 'password': 'Admin@J2F2024'}).get_json()
        self.admin = {'Authorization': 'Bearer ' + tokens['access_token']}
        with self.app.app_context():
            self.active = State.query.filter_by(name='Activo', type='user').one().id
        self.data = {'document_type': 'RUC', 'document_number': '20123456786',
                     'business_name': 'Empresa de prueba S.A.C.', 'state_id': self.active}

    def tearDown(self):
        with self.app.app_context():
            db.session.remove()
            db.engine.dispose()

    def create(self, **changes):
        return self.client.post('/api/master-data/clients/', headers=self.admin, json={**self.data, **changes})

    def test_client_can_be_saved_without_token_external_query_or_observation(self):
        with patch('urllib.request.OpenerDirector.open', side_effect=AssertionError('No se debe consultar una API')):
            response = self.create()
        self.assertEqual(response.status_code, 201, response.get_json())
        record = response.get_json()['record']
        self.assertEqual(record['business_name'], self.data['business_name'])
        self.assertNotEqual(record['verification']['status'], 'verified_api')
        self.assertEqual(self.client.get(f"/api/master-data/clients/{record['id']}", headers=self.admin)
                         .get_json()['client']['document_number'], self.data['document_number'])

    def test_external_lookup_endpoint_is_removed(self):
        response = self.client.post('/api/master-data/clients/ruc-lookup', headers=self.admin,
                                    json={'document_number': self.data['document_number']})
        self.assertEqual(response.status_code, 404)

    def test_local_ruc_validation_still_rejects_invalid_prefix_control_and_characters(self):
        from app.validation import validate_ruc
        for control in ['20000000061', '20000000010', '20131312955']:
            self.assertEqual(validate_ruc(control), control)
        for number in ['20123456789', '84545454445', '123', '2012345678h', '２０１２３４５６７８６']:
            with self.subTest(number=number):
                self.assertEqual(self.create(document_number=number).status_code, 400)
        with self.app.app_context():
            self.assertEqual(Client.query.count(), 0)

    def test_client_identity_can_be_edited_without_additional_api_requirements(self):
        record = self.create().get_json()['record']
        path = f"/api/master-data/clients/{record['id']}"
        for body in [{'business_name':'Empresa actualizada'}, {'document_number':'20123456794'},
                     {'document_type':'DNI','document_number':'12345678'},
                     {'document_type':'RUC','document_number':self.data['document_number']}]:
            response = self.client.put(path, headers=self.admin, json=body)
            self.assertEqual(response.status_code, 200, response.get_json())
        self.assertEqual(self.client.put(path, headers=self.admin, json={'document_number':'20123456789'}).status_code, 400)

    def test_previous_history_is_preserved_and_old_verification_not_reused_for_new_identity(self):
        record = self.create().get_json()['record']
        previous = {'status':'verified_api', 'source':'historic', 'audit':[{'status':'verified_api',
                    'document_number':self.data['document_number'], 'business_name':self.data['business_name']}]}
        with self.app.app_context():
            db.session.get(Client, record['id']).verification_json = json.dumps(previous)
            db.session.commit()
        path = f"/api/master-data/clients/{record['id']}"
        response = self.client.put(path, headers=self.admin, json={'phone':'987654321'})
        self.assertEqual(response.get_json()['record']['verification'], previous)
        response = self.client.put(path, headers=self.admin, json={'business_name':'Empresa actualizada'})
        self.assertEqual(response.status_code, 200, response.get_json())
        verification = response.get_json()['record']['verification']
        self.assertEqual(verification['status'], 'pending')
        self.assertEqual(verification['audit'][0], previous['audit'][0])
        self.assertEqual(len(verification['audit']), 2)
        self.assertEqual(self.client.put(path, headers=self.admin, json={'verification_json':'verified_api'}).status_code, 400)

    def test_old_invalid_document_remains_unchanged_on_state_only_update(self):
        with self.app.app_context():
            old = Client(document_type='RUC', document_number='84545454445', business_name='A', state_id=self.active)
            db.session.add(old); db.session.commit(); old_id = old.id
        response = self.client.put(f'/api/master-data/clients/{old_id}', headers=self.admin, json={'state_id':self.active})
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.get_json()['record']['document_number'], '84545454445')

    def test_gps_identification_and_permissions_are_preserved(self):
        customer = self.create().get_json()['record']
        vehicle = self.client.post('/api/master-data/vehicles/', headers=self.admin,
            json={'client_id':customer['id'], 'plate':'ABC-123', 'state_id':self.active}).get_json()['record']
        self.assertEqual(vehicle['gps_devices'], [])
        body = {'vehicle_id':vehicle['id'], 'imei':'860000000000001', 'state_id':self.active}
        response = self.client.post('/api/master-data/gps-devices/', headers=self.admin, json=body)
        self.assertEqual(response.status_code, 201, response.get_json())
        self.assertEqual(self.client.post('/api/master-data/gps-devices/', headers=self.admin, json=body).status_code, 400)
        vehicles = self.client.get('/api/master-data/vehicles/', headers=self.admin).get_json()['vehicles']
        self.assertEqual(vehicles[0]['gps_devices'][0]['imei'], body['imei'])
        mapped = self.client.get('/api/alerts/map/vehicles', headers=self.admin).get_json()['vehicles']
        self.assertEqual(mapped[0]['gps_device']['imei'], body['imei'])
        with self.app.app_context():
            technician = User(dni='12345678', full_name='Técnico Prueba', email='tech@test.invalid',
                              profile_id=Profile.query.filter_by(name='Técnico').one().id, state_id=self.active)
            technician.set_password('Test-password-123!'); db.session.add(technician); db.session.commit()
        token = self.client.post('/api/auth/login', json={'identifier':'tech@test.invalid', 'password':'Test-password-123!'}).get_json()['access_token']
        headers = {'Authorization':'Bearer ' + token}
        self.assertEqual(self.client.post('/api/master-data/gps-devices/', headers=headers, json=body).status_code, 403)
        self.assertEqual(self.client.post('/api/master-data/clients/', headers=headers, json=self.data).status_code, 403)
        self.assertEqual(self.client.get('/api/master-data/vehicles/', headers=headers).get_json()['vehicles'], [])
        self.assertEqual(self.client.get('/api/master-data/gps-devices/', headers=headers).get_json()['gps_devices'], [])


if __name__ == '__main__':
    unittest.main()
