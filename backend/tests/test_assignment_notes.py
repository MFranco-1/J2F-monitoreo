"""Notas independientes y permisos: exclusivamente SQLite de pruebas."""
import unittest
from app import create_app, db
from app.models import Assignment, History, Profile, State, User


class AssignmentNotesTests(unittest.TestCase):
    def setUp(self):
        self.app = create_app('testing')
        self.client = self.app.test_client()
        self.admin = self.login('admin@j2f.com', 'Admin@J2F2024')
        with self.app.app_context():
            active = State.query.filter_by(name='Activo', type='user').one().id
            self.ids = {}
            for index, role in enumerate(('Técnico', 'Técnico', 'Supervisor', 'Operador'), 1):
                profile = Profile.query.filter_by(name=role).one()
                user = User(dni=f'{index:08d}', full_name=f'Persona {index}',
                            email=f'notes{index}@example.invalid', profile_id=profile.id,
                            state_id=active)
                user.set_password('Password-123!')
                db.session.add(user)
                db.session.flush()
                self.ids[index] = user.id
            db.session.commit()
        self.tech = self.login('notes1@example.invalid')
        self.other = self.login('notes2@example.invalid')
        self.supervisor = self.login('notes3@example.invalid')
        self.operator = self.login('notes4@example.invalid')
        response = self.client.post('/api/alerts/', headers=self.admin,
                                    json={'title': 'Incidencia de unidad',
                                          'description': 'Se requiere revisar la unidad y coordinar atención'})
        self.assertEqual(response.status_code, 201, response.get_json())
        self.alert_id = response.get_json()['alert']['id']
        self.assignment_id = self.assign(self.ids[1])

    def tearDown(self):
        with self.app.app_context():
            db.session.remove()
            db.engine.dispose()

    def login(self, email, password='Password-123!'):
        response = self.client.post('/api/auth/login', json={'identifier': email, 'password': password})
        self.assertEqual(response.status_code, 200, response.get_json())
        return {'Authorization': 'Bearer ' + response.get_json()['access_token']}

    def assign(self, user_id, **extra):
        response = self.client.post('/api/assignments/', headers=self.admin,
                                    json={'alert_id': self.alert_id, 'user_id': user_id, **extra})
        self.assertEqual(response.status_code, 201, response.get_json())
        return response.get_json()['assignment']['id']

    def post_note(self, content, headers=None, assignment_id=None, **extra):
        return self.client.post(f'/api/assignments/{assignment_id or self.assignment_id}/notes',
                                headers=headers or self.tech, json={'notes': content, **extra})

    def notes(self, headers=None, assignment_id=None):
        response = self.client.get(f'/api/assignments/{assignment_id or self.assignment_id}/notes',
                                   headers=headers or self.tech)
        self.assertEqual(response.status_code, 200, response.get_json())
        return response.get_json()

    def test_multiple_notes_preserve_author_profile_time_and_do_not_replace_each_other(self):
        entries = []
        for content, actor, category in (
                ('Revisé el cableado del GPS', self.tech, 'technical'),
                ('Se coordinó la intervención', self.supervisor, 'coordination'),
                ('Conductor disponible para revisión', self.admin, 'coordination'),
                ('Conexión revisada, falta probar señal', self.tech, 'technical')):
            response = self.post_note(content, actor)
            self.assertEqual(response.status_code, 201, response.get_json())
            note = response.get_json()['note']
            self.assertEqual(note['detail'], content)
            self.assertEqual(note['metadata']['category'], category)
            self.assertEqual(note['metadata']['assignment_id'], self.assignment_id)
            self.assertTrue(note['timestamp'].endswith('Z'))
            self.assertTrue(note['user']['full_name'])
            self.assertTrue(note['profile']['name'])
            entries.append(note)
        self.assertEqual(self.notes()['notes'], entries)
        self.assertEqual(self.notes(self.supervisor)['notes'], entries)
        with self.app.app_context():
            self.assertIsNone(db.session.get(Assignment, self.assignment_id).notes)
            self.assertEqual(History.query.filter_by(alert_id=self.alert_id, action='note_added').count(), 4)
        for method in ('put', 'patch', 'delete'):
            response = getattr(self.client, method)(f'/api/assignments/{self.assignment_id}/notes',
                                                      headers=self.admin, json={'notes': 'Reemplazo ajeno'})
            self.assertEqual(response.status_code, 405)
        self.assertEqual(self.notes()['notes'], entries)

    def test_new_technician_reads_previous_case_notes_but_previous_cannot_write(self):
        self.post_note('Revisión iniciada por el técnico anterior')
        self.post_note('Conductor informado por supervisión', self.supervisor)
        previous = self.notes()['notes']
        second = self.assign(self.ids[2])
        self.assertEqual(self.notes(self.other, second)['notes'], previous)
        self.assertEqual(self.notes(self.other, self.assignment_id)['notes'], previous)
        self.assertFalse(self.notes(self.tech)['can_add'])
        self.assertEqual(self.post_note('No debe modificar la atención anterior').status_code, 409)
        self.assertEqual(self.post_note('No debe escribir en la atención nueva', assignment_id=second).status_code, 403)
        self.assertEqual(self.post_note('Continúo con la revisión documentada', self.other, second).status_code, 201)
        self.assertEqual(len(self.notes(self.other, second)['notes']), 3)
        self.assertEqual(self.notes(self.other, second)['notes'][:2], previous)

    def test_new_note_keeps_name_and_profile_as_recorded_when_account_is_renamed(self):
        self.assertEqual(self.post_note('Revisión registrada con autor verificable').status_code, 201)
        with self.app.app_context():
            user = db.session.get(User, self.ids[1])
            user.full_name = 'Nombre actualizado'
            profile = Profile.query.filter_by(name='Técnico').one()
            profile.name = 'Técnico actualizado'
            db.session.commit()
            note = History.query.filter_by(alert_id=self.alert_id, action='note_added').one().to_dict()
        self.assertEqual(note['user']['full_name'], 'Persona 1')
        self.assertEqual(note['profile']['name'], 'Técnico')

    def test_permission_scope_supervisor_notes_not_closure_and_operator_read_only(self):
        self.assertEqual(self.client.get(f'/api/assignments/{self.assignment_id}/notes').status_code, 401)
        self.assertEqual(self.client.post(f'/api/assignments/{self.assignment_id}/notes', json={}).status_code, 401)
        self.assertEqual(self.client.get(f'/api/assignments/{self.assignment_id}/notes', headers=self.other).status_code, 403)
        self.assertEqual(self.post_note('Observación no autorizada', self.other).status_code, 403)
        self.assertFalse(self.notes(self.operator)['can_add'])
        self.assertEqual(self.post_note('Observación del operador no permitida', self.operator).status_code, 403)
        self.assertEqual(self.post_note('Observación de supervisión permitida', self.supervisor).status_code, 201)
        response = self.client.put(f'/api/assignments/{self.assignment_id}', headers=self.supervisor,
                                   json={'complete': True, 'solution': 'Cierre no autorizado'})
        self.assertEqual(response.status_code, 403)
        self.assertEqual(len(self.notes()['notes']), 1)

    def test_legacy_put_appends_and_payload_cannot_forge_author_or_edit_note(self):
        url = f'/api/assignments/{self.assignment_id}'
        for content in ('Primera nota de revisión', 'Segunda nota de revisión'):
            self.assertEqual(self.client.put(url, headers=self.tech, json={'notes': content}).status_code, 200)
        for invalid in (None, '', '   ', 'A', '...', '123456', 'a' * 2001):
            self.assertEqual(self.post_note(invalid).status_code, 400)
        self.assertEqual(self.post_note('Texto con autor falso', user_id=self.ids[2]).status_code, 400)
        self.assertEqual(self.post_note('Texto con perfil falso', profile_id=1).status_code, 400)
        self.assertEqual(self.post_note('Texto con fecha falsa', timestamp='2020-01-01').status_code, 400)
        for actor in (self.tech, self.supervisor, self.admin):
            self.assertEqual(self.client.put(url, headers=actor,
                json={'note_id': self.notes()['notes'][0]['id'], 'notes': 'Reemplazo prohibido'}).status_code, 400)
        self.assertEqual([note['detail'] for note in self.notes()['notes']],
                         ['Primera nota de revisión', 'Segunda nota de revisión'])

    def test_legacy_texts_and_audits_remain_readable_without_invented_authorship(self):
        with self.app.app_context():
            db.session.get(Assignment, self.assignment_id).notes = 'Texto heredado escrito antes del cambio'
            legacy = History(alert_id=self.alert_id, user_id=1, action='note_added',
                             detail='Notas anteriores. Antes: primera revisión. Ahora: segunda revisión')
            db.session.add(legacy)
            db.session.commit()
        self.post_note('Nueva nota que no reemplaza la anterior')
        second = self.assign(self.ids[2])
        result = self.notes(self.other, second)
        self.assertEqual(result['legacy_notes'], [{'assignment_id': self.assignment_id,
            'detail': 'Texto heredado escrito antes del cambio'}])
        self.assertEqual(len(result['legacy_audits']), 1)
        self.assertIsNone(result['legacy_audits'][0]['metadata'])
        self.assertEqual(len(result['notes']), 1)
        self.assertEqual(self.client.put(f'/api/assignments/{second}', headers=self.other,
            json={'complete': True, 'solution': 'Se completaron las pruebas de señal'}).status_code, 200)
        self.assertEqual(self.notes(self.other, second)['legacy_notes'], result['legacy_notes'])
        self.assertEqual(self.notes(self.other, second)['notes'], result['notes'])

    def test_closing_or_cancelling_keeps_notes_readable_and_blocks_new_notes(self):
        self.post_note('Se verificó la incidencia reportada')
        entries = self.notes()['notes']
        for actor in (self.tech, self.supervisor, self.admin):
            # Cierre con solución inválida no puede guardar una nota parcialmente.
            response = self.client.put(f'/api/assignments/{self.assignment_id}', headers=actor,
                                       json={'notes': 'No guardar parcialmente', 'complete': True, 'solution': 'A'})
            self.assertIn(response.status_code, (400, 403))
        self.assertEqual(self.notes()['notes'], entries)
        for _ in range(2):
            self.assertEqual(self.client.put(f'/api/assignments/{self.assignment_id}', headers=self.tech,
                json={'complete': True, 'solution': 'Conexión restablecida y verificada'}).status_code, 200)
        for actor in (self.tech, self.supervisor, self.admin):
            self.assertEqual(self.post_note('Nota posterior al cierre', actor).status_code, 409)
            self.assertEqual(self.client.put(f'/api/assignments/{self.assignment_id}', headers=actor,
                                           json={'notes': 'Cambio posterior al cierre'}).status_code, 409)
        self.assertEqual(self.notes()['notes'], entries)
        # Otro caso anulado también conserva lectura y bloquea escrituras.
        created = self.client.post('/api/alerts/', headers=self.admin,
            json={'title': 'Otro caso pendiente', 'description': 'Incidencia para verificar anulación'}).get_json()
        self.alert_id = created['alert']['id']
        self.assignment_id = self.assign(self.ids[1])
        self.post_note('Observación previa a la anulación')
        self.assertEqual(self.client.post(f'/api/alerts/{self.alert_id}/cancel', headers=self.admin,
            json={'reason': 'Incidencia registrada por duplicado'}).status_code, 200)
        self.assertEqual(self.post_note('No registrar después de anular').status_code, 409)
        self.assertEqual(len(self.notes()['notes']), 1)
        self.assertFalse(self.notes()['can_add'])

    def test_initial_assignment_instructions_have_actual_author_and_survive_reassignment(self):
        response = self.client.post('/api/assignments/', headers=self.operator,
            json={'alert_id': self.alert_id, 'user_id': self.ids[2], 'notes': 'Llamar al conductor antes de intervenir'})
        self.assertEqual(response.status_code, 201, response.get_json())
        assignment = response.get_json()['assignment']['id']
        note = self.notes(self.other, assignment)['notes'][0]
        self.assertEqual(note['user_id'], self.ids[4])
        self.assertEqual(note['profile']['name'], 'Operador')
        self.assertEqual(note['metadata']['category'], 'assignment')
        self.assertEqual(self.notes(self.other, assignment)['legacy_notes'], [])

    def test_multirole_uses_active_profile_and_new_sessions_keep_notes(self):
        with self.app.app_context():
            user = db.session.get(User, self.ids[2])
            user.profiles = [Profile.query.filter_by(name='Técnico').one(),
                             Profile.query.filter_by(name='Supervisor').one()]
            db.session.commit()
            supervisor_id = Profile.query.filter_by(name='Supervisor').one().id
            technician_id = Profile.query.filter_by(name='Técnico').one().id
        tokens = self.client.post('/api/auth/login', json={'identifier': 'notes2@example.invalid',
            'password': 'Password-123!'}).get_json()
        self.assertTrue(tokens['requires_profile_selection'])
        session = {'Authorization': 'Bearer ' + tokens['access_token']}
        def select(profile_id):
            nonlocal session
            result = self.client.post('/api/auth/select-profile', headers=session,
                                      json={'profile_id': profile_id})
            self.assertEqual(result.status_code, 200, result.get_json())
            session = {'Authorization': 'Bearer ' + result.get_json()['access_token']}
            return session
        tech_profile = select(technician_id)
        self.assertEqual(self.post_note('No usar permisos del perfil supervisor', tech_profile).status_code, 403)
        supervisor_profile = select(supervisor_id)
        self.assertEqual(self.post_note('Coordinación con perfil seleccionado', supervisor_profile).status_code, 201)
        entries = self.notes()['notes']
        self.assertEqual(entries[0]['profile_id'], supervisor_id)
        self.assertEqual(entries[0]['metadata']['category'], 'coordination')
        fresh_session = self.login('notes1@example.invalid')
        self.assertEqual(self.notes(fresh_session)['notes'], entries)


if __name__ == '__main__':
    unittest.main()
