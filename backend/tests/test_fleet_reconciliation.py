"""Reparación de estados heredados: únicamente SQLite aislada."""
import unittest
from app import create_app, db
from app.models import State, Alert, History
from app.models.master_data import Client, Vehicle, GpsDevice, EventType
from reconcile_fleet_states import reconciliation_plan, apply_reconciliation


class FleetReconciliationTests(unittest.TestCase):
    def setUp(self):
        self.app = create_app('testing')
        with self.app.app_context():
            self.active = State.query.filter_by(name='Activo', type='user').one().id
            self.inactive = State.query.filter_by(name='Inactivo', type='user').one().id
            parent = Client(document_type='DNI', document_number='12345678', business_name='Cliente anterior', state_id=self.inactive)
            healthy = Client(document_type='DNI', document_number='87654321', business_name='Cliente vigente', state_id=self.active)
            db.session.add_all([parent, healthy]); db.session.flush()
            units = [Vehicle(client_id=parent.id, plate='OLD-101', state_id=self.active),
                     Vehicle(client_id=healthy.id, plate='NEW-102', state_id=self.active)]
            db.session.add_all(units); db.session.flush()
            db.session.add_all([GpsDevice(vehicle_id=unit.id, imei=f'{index:015d}', state_id=self.active)
                                for index, unit in enumerate(units, 1)])
            db.session.commit()
            self.vehicle, self.healthy = units[0].id, units[1].id

    def tearDown(self):
        with self.app.app_context():
            db.session.remove(); db.engine.dispose()

    def test_plan_is_read_only_apply_is_scoped_and_idempotent(self):
        with self.app.app_context():
            before = (Client.query.count(), Vehicle.query.count(), GpsDevice.query.count(), Alert.query.count(), History.query.count())
            with db.engine.begin() as connection:
                plan = reconciliation_plan(connection)
            self.assertEqual([unit['id'] for unit in plan['vehicles']], [self.vehicle])
            self.assertEqual(db.session.get(Vehicle, self.vehicle).state_id, self.active)
            with db.engine.begin() as connection:
                apply_reconciliation(connection, reconciliation_plan(connection, lock=True))
                self.assertEqual(reconciliation_plan(connection)['vehicles'], [])
                self.assertEqual(reconciliation_plan(connection)['gps_devices'], [])
            db.session.expire_all()
            self.assertEqual(db.session.get(Vehicle, self.vehicle).state_id, self.inactive)
            self.assertEqual(db.session.get(Vehicle, self.healthy).state_id, self.active)
            self.assertEqual((Client.query.count(), Vehicle.query.count(), GpsDevice.query.count(), Alert.query.count(), History.query.count()), before)

    def test_pending_fuel_blocks_entire_apply_without_partial_updates(self):
        with self.app.app_context():
            alert = Alert(title='Combustible pendiente', description='Requiere abastecimiento documentado', vehicle_id=self.vehicle,
                          event_type_id=EventType.query.filter_by(code='LOW_FUEL').one().id,
                          state_id=State.query.filter_by(name='Abierto', type='alert').one().id)
            db.session.add(alert); db.session.commit()
            with self.assertRaises(ValueError), db.engine.begin() as connection:
                apply_reconciliation(connection, reconciliation_plan(connection))
            db.session.expire_all()
            self.assertEqual(db.session.get(Vehicle, self.vehicle).state_id, self.active)
            self.assertTrue(all(gps.state_id == self.active for gps in GpsDevice.query.all()))
