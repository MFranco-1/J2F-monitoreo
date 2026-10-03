"""Observaciones de presentación: SQLite aislado; no modificar Neon."""
import unittest
from app import create_app, db
from app.models import Alert, History, State
from app.models.master_data import Client, Vehicle, GpsDevice, EventType
from client_fixtures import client_fixture


class OperationalObservationTests(unittest.TestCase):
    def setUp(self):
        self.app = create_app('testing')
        self.client = self.app.test_client()
        self.admin = self.login('admin@j2f.com', 'Admin@J2F2024')
        with self.app.app_context():
            self.active = State.query.filter_by(name='Activo', type='user').one().id
            self.inactive = State.query.filter_by(name='Inactivo', type='user').one().id
            from app.models import Profile
            self.profiles = {profile.name: profile.id for profile in Profile.query.all()}

    def tearDown(self):
        with self.app.app_context():
            db.session.remove(); db.engine.dispose()

    def login(self, identifier, password='Password-123!'):
        response = self.client.post('/api/auth/login', json={'identifier':identifier, 'password':password})
        self.assertEqual(response.status_code, 200, response.get_json())
        return {'Authorization':'Bearer ' + response.get_json()['access_token']}

    def post(self, path, body, headers=None):
        response = self.client.post(path, json=body, headers=headers or self.admin)
        self.assertEqual(response.status_code, 201, response.get_json())
        return response.get_json()

    def user(self, index, role):
        user = self.post('/api/users/', {'dni':f'{index:08}', 'full_name':f'Usuario {role}',
            'email':f'observacion{index}@example.invalid', 'password':'Password-123!',
            'state_id':self.active, 'profile_ids':[self.profiles[role]]})['user']
        return user['id'], self.login(user['email'])

    def fleet(self, index=1):
        customer = self.post('/api/master-data/clients/', {**client_fixture(f'4000000{index}'),
            'business_name':f'Transportes del cliente {index}', 'state_id':self.active})['record']
        vehicles, devices = [], []
        for unit in (1, 2):
            vehicle = self.post('/api/master-data/vehicles/', {'plate':f'C{index}V-10{unit}',
                'client_id':customer['id'], 'state_id':self.active})['record']
            vehicles.append(vehicle)
            devices.append(self.post('/api/master-data/gps-devices/', {'imei':f'860000000000{index}0{unit}',
                'vehicle_id':vehicle['id'], 'state_id':self.active})['record'])
        return customer, vehicles, devices

    def alert(self, **changes):
        return self.post('/api/alerts/', {'title':'Incidencia registrada',
            'description':'La unidad requiere una revisión documentada', **changes})['alert']

    def state(self, model, record_id):
        with self.app.app_context():
            return db.session.get(model, record_id).state.name

    def test_deactivating_client_updates_its_vehicles_and_gps_not_other_clients_or_history(self):
        customer, vehicles, devices = self.fleet()
        other, other_vehicles, other_devices = self.fleet(2)
        alert = self.alert(client_id=customer['id'], vehicle_id=vehicles[0]['id'], gps_device_id=devices[0]['id'])
        with self.app.app_context():
            history_count = History.query.count()
        response = self.client.put(f"/api/master-data/clients/{customer['id']}", headers=self.admin, json={'state_id':self.inactive})
        self.assertEqual(response.status_code, 200, response.get_json())
        self.assertEqual(self.state(Client, customer['id']), 'Inactivo')
        for vehicle, device in zip(vehicles, devices):
            self.assertEqual(self.state(Vehicle, vehicle['id']), 'Inactivo')
            self.assertEqual(self.state(GpsDevice, device['id']), 'Inactivo')
        self.assertEqual(self.state(Client, other['id']), 'Activo')
        for vehicle, device in zip(other_vehicles, other_devices):
            self.assertEqual(self.state(Vehicle, vehicle['id']), 'Activo')
            self.assertEqual(self.state(GpsDevice, device['id']), 'Activo')
        visible = self.client.get('/api/alerts/map/vehicles', headers=self.admin).get_json()['vehicles']
        self.assertEqual({vehicle['id'] for vehicle in visible}, {vehicle['id'] for vehicle in other_vehicles})
        persisted = self.client.get(f"/api/alerts/{alert['id']}", headers=self.admin).get_json()['alert']
        self.assertEqual(persisted['vehicle_id'], vehicles[0]['id'])
        self.assertEqual(persisted['state']['name'], 'Abierto')
        with self.app.app_context():
            self.assertEqual(History.query.count(), history_count)
        self.assertEqual(self.client.put(f"/api/master-data/clients/{customer['id']}", headers=self.admin,
            json={'state_id':self.inactive}).status_code, 200)

    def test_validation_error_and_pending_fuel_leave_entire_fleet_unchanged(self):
        customer, vehicles, devices = self.fleet()
        with self.app.app_context():
            fuel_id = EventType.query.filter_by(code='LOW_FUEL').one().id
        alert = self.alert(client_id=customer['id'], vehicle_id=vehicles[0]['id'], event_type_id=fuel_id)
        path = f"/api/master-data/clients/{customer['id']}"
        response = self.client.put(path, headers=self.admin, json={'state_id':self.inactive, 'business_name':'A'})
        self.assertEqual(response.status_code, 400)
        response = self.client.put(path, headers=self.admin, json={'state_id':self.inactive})
        self.assertEqual(response.status_code, 409)
        self.assertIn(str(alert['id']), response.get_json()['error'])
        for model, records in [(Client,[customer]), (Vehicle,vehicles), (GpsDevice,devices)]:
            for record in records: self.assertEqual(self.state(model, record['id']), 'Activo')
        self.assertEqual(self.client.post(f"/api/alerts/{alert['id']}/cancel", headers=self.admin,
            json={'reason':'Se atiende el evento original; caso duplicado'}).status_code, 200)
        self.assertEqual(self.client.put(path, headers=self.admin, json={'state_id':self.inactive}).status_code, 200)
        self.assertEqual(self.state(GpsDevice, devices[0]['id']), 'Inactivo')

    def test_parent_activation_does_not_reactivate_children_and_active_child_cannot_bypass_parent(self):
        customer, vehicles, devices = self.fleet()
        customer_path = f"/api/master-data/clients/{customer['id']}"
        vehicle_path = f"/api/master-data/vehicles/{vehicles[0]['id']}"
        gps_path = f"/api/master-data/gps-devices/{devices[0]['id']}"
        self.assertEqual(self.client.put(customer_path, headers=self.admin, json={'state_id':self.inactive}).status_code, 200)
        self.assertEqual(self.client.put(vehicle_path, headers=self.admin, json={'state_id':self.active}).status_code, 400)
        self.assertEqual(self.client.put(gps_path, headers=self.admin, json={'state_id':self.active}).status_code, 400)
        self.assertEqual(self.client.post('/api/master-data/vehicles/', headers=self.admin,
            json={'plate':'NUE-123', 'client_id':customer['id'], 'state_id':self.active}).status_code, 400)
        self.assertEqual(self.client.post('/api/master-data/gps-devices/', headers=self.admin,
            json={'imei':'860000000000099', 'vehicle_id':vehicles[0]['id'], 'state_id':self.active}).status_code, 400)
        self.assertEqual(self.client.put(customer_path, headers=self.admin, json={'state_id':self.active}).status_code, 200)
        self.assertEqual(self.state(Vehicle, vehicles[0]['id']), 'Inactivo')
        self.assertEqual(self.state(GpsDevice, devices[0]['id']), 'Inactivo')
        self.assertEqual(self.client.put(gps_path, headers=self.admin, json={'state_id':self.active}).status_code, 400)
        self.assertEqual(self.client.put(vehicle_path, headers=self.admin, json={'state_id':self.active}).status_code, 200)
        self.assertEqual(self.state(GpsDevice, devices[0]['id']), 'Inactivo')
        self.assertEqual(self.client.put(gps_path, headers=self.admin, json={'state_id':self.active}).status_code, 200)
        self.assertEqual(self.client.put(vehicle_path, headers=self.admin, json={'state_id':self.inactive}).status_code, 200)
        self.assertEqual(self.state(GpsDevice, devices[0]['id']), 'Inactivo')

    def test_legacy_active_units_of_inactive_client_do_not_appear_as_available(self):
        customer, vehicles, devices = self.fleet()
        with self.app.app_context():
            db.session.get(Client, customer['id']).state_id = self.inactive
            db.session.commit()
        self.assertEqual(self.client.get('/api/alerts/map/vehicles', headers=self.admin).get_json()['vehicles'], [])
        self.assertEqual(self.client.get('/api/master-data/vehicles/?active=true', headers=self.admin).get_json()['vehicles'], [])
        self.assertEqual(self.client.get('/api/master-data/gps-devices/?active=true', headers=self.admin).get_json()['gps_devices'], [])
        self.assertEqual(len(self.client.get('/api/master-data/vehicles/', headers=self.admin).get_json()['vehicles']), 2)
        self.assertEqual(self.client.put(f"/api/master-data/clients/{customer['id']}", headers=self.admin,
            json={'state_id':self.inactive}).status_code, 200)
        self.assertEqual(self.state(Vehicle, vehicles[0]['id']), 'Inactivo')
        self.assertEqual(self.state(GpsDevice, devices[0]['id']), 'Inactivo')

    def test_cascade_permissions_remain_admin_only(self):
        customer, vehicles, devices = self.fleet()
        for index, role in enumerate(['Operador','Supervisor','Técnico'], 1):
            _, headers = self.user(index, role)
            response = self.client.put(f"/api/master-data/clients/{customer['id']}", headers=headers, json={'state_id':self.inactive})
            self.assertEqual(response.status_code, 403)
        self.assertEqual(self.state(Client, customer['id']), 'Activo')
        self.assertEqual(self.state(GpsDevice, devices[0]['id']), 'Activo')

    def test_new_alert_requires_description_and_edits_cannot_clear_it_but_legacy_alert_is_readable(self):
        for description in [None, '', '   ', 'A', '...', '12345', 'AAAAA']:
            body = {'title':'Título sin información suficiente'}
            if description is not None: body['description'] = description
            response = self.client.post('/api/alerts/', headers=self.admin, json=body)
            self.assertEqual(response.status_code, 400, response.get_json())
        with self.app.app_context():
            self.assertEqual(Alert.query.count(), 0); self.assertEqual(History.query.count(), 0)
        alert = self.alert()
        for value in [None, '', '  ', 'A']:
            response = self.client.put(f"/api/alerts/{alert['id']}", headers=self.admin,
                json={'description':value, 'title':'No guardar este título'})
            self.assertEqual(response.status_code, 400)
            reloaded = self.client.get(f"/api/alerts/{alert['id']}", headers=self.admin).get_json()['alert']
            self.assertEqual(reloaded['title'], alert['title']); self.assertEqual(reloaded['description'], alert['description'])
        with self.app.app_context():
            legacy = Alert(title='Caso heredado', state=State.query.filter_by(name='Abierto', type='alert').one(), created_by=1)
            db.session.add(legacy); db.session.commit(); legacy_id = legacy.id
        self.assertEqual(self.client.get(f'/api/alerts/{legacy_id}', headers=self.admin).status_code, 200)
        self.assertEqual(self.client.post(f'/api/alerts/{legacy_id}/cancel', headers=self.admin,
            json={'reason':'Caso anterior incompleto; anulación documentada'}).status_code, 200)

    def test_workload_requeries_reflect_assign_reassign_cancel_and_close_with_permissions(self):
        first, technician = self.user(1, 'Técnico')
        second, _ = self.user(2, 'Técnico')
        def counts():
            response = self.client.get('/api/assignments/technicians', headers=self.admin)
            self.assertEqual(response.status_code, 200)
            return {row['id']:row['active_assignments_count'] for row in response.get_json()['technicians']}
        alert = self.alert()
        self.assertEqual(counts(), {first:0, second:0})
        self.post('/api/assignments/', {'alert_id':alert['id'], 'user_id':first})
        self.assertEqual(counts(), {first:1, second:0})
        self.post('/api/assignments/', {'alert_id':alert['id'], 'user_id':second})
        self.assertEqual(counts(), {first:0, second:1})
        self.assertEqual(self.client.post(f"/api/alerts/{alert['id']}/cancel", headers=self.admin,
            json={'reason':'Incidencia duplicada; se mantiene el caso original'}).status_code, 200)
        self.assertEqual(counts(), {first:0, second:0})
        other = self.alert()
        self.post('/api/assignments/', {'alert_id':other['id'], 'user_id':first})
        self.assertEqual(self.client.put(f"/api/alerts/{other['id']}", headers=technician,
            json={'state_name':'Cerrado', 'notes':'La incidencia fue corregida y verificada'}).status_code, 200)
        self.assertEqual(counts(), {first:0, second:0})
        self.assertEqual(self.client.get('/api/assignments/technicians', headers=technician).status_code, 403)


if __name__ == '__main__':
    unittest.main()
