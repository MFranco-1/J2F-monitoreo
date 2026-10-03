"""Formato y teléfono internacional de clientes: solo SQLite, sin Neon ni APIs."""
import unittest
from app import create_app, db
from app.models import Profile, State, User
from app.models.master_data import Client


class ClientFormatTests(unittest.TestCase):
    def setUp(self):
        self.app = create_app('testing')
        self.client = self.app.test_client()
        login = self.client.post('/api/auth/login', json={
            'identifier': 'admin@j2f.com', 'password': 'Admin@J2F2024'}).get_json()
        self.headers = {'Authorization': 'Bearer ' + login['access_token']}
        with self.app.app_context():
            self.active = State.query.filter_by(name='Activo', type='user').one().id
            self.inactive = State.query.filter_by(name='Inactivo', type='user').one().id
        self.data = {'document_type': 'RUC', 'document_number': '20123456786',
                     'business_name': 'Transportes andinos s.a.c.', 'state_id': self.active}

    def tearDown(self):
        with self.app.app_context():
            db.session.remove()
            db.engine.dispose()

    def create(self, **changes):
        return self.client.post('/api/master-data/clients/', headers=self.headers, json={**self.data, **changes})

    def test_names_normalized_on_create_edit_and_reload_without_altering_other_clients(self):
        response = self.create(business_name='  TRANSPORTES   ÑANDÚ S.A.C.  ', contact_name="  aNA   PÉREZ D'ÁVILA  ")
        self.assertEqual(response.status_code, 201, response.get_json())
        record = response.get_json()['record']
        self.assertEqual(record['business_name'], 'Transportes ñandú s.a.c.')
        self.assertEqual(record['contact_name'], "Ana pérez d'ávila")
        with self.app.app_context():
            old = Client(document_type='DNI', document_number='01234567', business_name='EMPRESA ANTERIOR', state_id=self.active)
            db.session.add(old); db.session.commit(); old_id = old.id
        path = f"/api/master-data/clients/{record['id']}"
        changed = self.client.put(path, headers=self.headers, json={'business_name': 'lOGÍSTICA mUÑOZ', 'contact_name': 'jOSÉ mUÑOZ'})
        self.assertEqual(changed.status_code, 200, changed.get_json())
        reloaded = self.client.get(path, headers=self.headers).get_json()['client']
        self.assertEqual(reloaded['business_name'], 'Logística muñoz')
        self.assertEqual(reloaded['contact_name'], 'José muñoz')
        with self.app.app_context():
            self.assertEqual(db.session.get(Client, old_id).business_name, 'EMPRESA ANTERIOR')

    def test_company_name_cannot_be_only_a_legal_suffix(self):
        for name in ['S.A.C.', 'sac', 'S.A.', 'E.I.R.L.', '  S. R. L.  ']:
            with self.subTest(name=name):
                response = self.create(business_name=name)
                self.assertEqual(response.status_code, 400, response.get_json())
                self.assertIn('Razón social', response.get_json()['error'])
        with self.app.app_context():
            self.assertEqual(Client.query.count(), 0)

    def test_addresses_reject_disallowed_symbols_atomically_on_create_and_edit(self):
        symbols = ['"', "'", '!', '¡', '?', '¿', '+', '=', '<', '>', '*', '%', '(', ')', '[', ']', '{', '}', '@', '\\', '$', '&', ';', '\n', '\t', '\u200b', '\x00']
        for symbol in symbols:
            response = self.create(address=f'Av. Perú {symbol} 123')
            self.assertEqual(response.status_code, 400, (symbol, response.get_json()))
        with self.app.app_context():
            self.assertEqual(Client.query.count(), 0)
        record = self.create(address='Av. Perú 123, Dpto. 301 / A - Lote # 15').get_json()['record']
        path = f"/api/master-data/clients/{record['id']}"
        for symbol in symbols:
            response = self.client.put(path, headers=self.headers, json={'address': f'Av. Perú {symbol} 123', 'state_id': self.inactive})
            self.assertEqual(response.status_code, 400, (symbol, response.get_json()))
            unchanged = self.client.get(path, headers=self.headers).get_json()['client']
            self.assertEqual(unchanged['address'], record['address'])
            self.assertEqual(unchanged['state_id'], self.active)

    def test_valid_international_numbers_round_trip_without_losing_italian_leading_zero(self):
        examples = [('PE', '987654321', '+51987654321'), ('US', '2025550123', '+12025550123'),
                    ('CA', '4165550123', '+14165550123'), ('CO', '3001234567', '+573001234567'),
                    ('ES', '612345678', '+34612345678'), ('CL', '961234567', '+56961234567'),
                    ('GB', '2079460018', '+442079460018'), ('IT', '0212345678', '+390212345678'),
                    ('BR', '11987654321', '+5511987654321')]
        for index, (country, number, canonical) in enumerate(examples, 1):
            response = self.create(document_type='DNI', document_number=f'{index:08}', phone_country=country, phone=number)
            self.assertEqual(response.status_code, 201, (country, response.get_json()))
            record = response.get_json()['record']
            self.assertEqual(record['phone'], canonical)
            self.assertEqual(record['phone_country'], country)
            path = f"/api/master-data/clients/{record['id']}"
            edited = self.client.put(path, headers=self.headers, json={'phone_country': country, 'phone': number})
            self.assertEqual(edited.status_code, 200, edited.get_json())
            self.assertEqual(edited.get_json()['record']['phone'], canonical)
            self.assertEqual(self.client.get(path, headers=self.headers).get_json()['client']['phone'], canonical)

    def test_invalid_phone_or_country_rejected_and_not_silently_corrected(self):
        cases = [('PE', '9876543211111'), ('PE', '98765432'), ('PE', '123456789'),
                 ('PE', '987654321h'), ('PE', '987 654 321'), ('PE', '987-654-321'),
                 ('PE', '(987)654321'), ('PE', '９８７６５４３２１'), ('PE', '000000000'),
                 ('XX', '987654321'), ('51', '987654321'), ('', '987654321'),
                 (False, '987654321'), ('PE', 987654321), ('PE', '+12025550123'),
                 ('US', '4165550123'), ('PE', '3001234567')]
        for country, number in cases:
            response = self.create(phone_country=country, phone=number)
            self.assertEqual(response.status_code, 400, (country, number, response.get_json()))
        with self.app.app_context():
            self.assertEqual(Client.query.count(), 0)
        record = self.create(phone_country='PE', phone='987654321').get_json()['record']
        path = f"/api/master-data/clients/{record['id']}"
        response = self.client.put(path, headers=self.headers, json={'phone_country': 'US', 'phone': '987654321', 'state_id': self.inactive})
        self.assertEqual(response.status_code, 400)
        self.assertEqual(self.client.put(path, headers=self.headers, json={'phone_country': 'US'}).status_code, 400)
        unchanged = self.client.get(path, headers=self.headers).get_json()['client']
        self.assertEqual(unchanged['phone'], '+51987654321')
        self.assertEqual(unchanged['state_id'], self.active)

    def test_optional_phone_and_legacy_records_remain_compatible(self):
        record = self.create(phone_country='PE', phone='').get_json()['record']
        self.assertEqual(record['phone'], '')
        self.assertIsNone(record['phone_country'])
        path = f"/api/master-data/clients/{record['id']}"
        for number in ['987654321', '51987654321', '+51987654321']:
            response = self.client.put(path, headers=self.headers, json={'phone': number})
            self.assertEqual(response.status_code, 200, response.get_json())
            self.assertEqual(response.get_json()['record']['phone'], '+51987654321')
        with self.app.app_context():
            old = Client(document_type='DNI', document_number='01234567', business_name='ANTERIOR',
                         phone='987654321h', address='$@? thruno mz 9666', state_id=self.active)
            db.session.add(old); db.session.commit(); old_id = old.id
        path = f'/api/master-data/clients/{old_id}'
        self.assertIsNone(self.client.get(path, headers=self.headers).get_json()['client']['phone_country'])
        updated = self.client.put(path, headers=self.headers, json={'state_id': self.inactive})
        self.assertEqual(updated.status_code, 200)
        self.assertEqual(updated.get_json()['record']['phone'], '987654321h')
        self.assertEqual(updated.get_json()['record']['address'], '$@? thruno mz 9666')
        self.assertEqual(updated.get_json()['record']['business_name'], 'ANTERIOR')

    def test_new_fields_do_not_grant_permissions_to_other_roles(self):
        for index, name in enumerate(['Operador', 'Supervisor', 'Técnico'], 1):
            with self.app.app_context():
                user = User(dni=f'7700000{index}', full_name='Usuario del perfil', email=f'format{index}@test.invalid',
                            profile_id=Profile.query.filter_by(name=name).one().id, state_id=self.active)
                user.set_password('Test-password-123!'); db.session.add(user); db.session.commit()
            login = self.client.post('/api/auth/login', json={'identifier':f'format{index}@test.invalid', 'password':'Test-password-123!'}).get_json()
            headers = {'Authorization':'Bearer ' + login['access_token']}
            response = self.client.post('/api/master-data/clients/', headers=headers, json={**self.data, 'phone_country':'PE', 'phone':'987654321'})
            self.assertEqual(response.status_code, 403, (name, response.get_json()))
        with self.app.app_context():
            self.assertEqual(Client.query.count(), 0)


if __name__ == '__main__':
    unittest.main()
