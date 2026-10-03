"""Vinculación GPS idempotente y no destructiva, solo SQLite temporal."""
import unittest
from app import create_app, db
from app.models import State
from app.models.master_data import Client, Vehicle, GpsDevice
from register_fleet_gps import generated_imei, register_missing_gps


class FleetGpsTests(unittest.TestCase):
    def setUp(self):
        self.app = create_app("testing")
        with self.app.app_context():
            active = State.query.filter_by(name="Activo", type="user").one().id
            inactive = State.query.filter_by(name="Inactivo", type="user").one().id
            client = Client(document_type="DNI", document_number="12345678", business_name="Cliente Flota", state_id=active)
            db.session.add(client); db.session.flush()
            units = [Vehicle(client_id=client.id, plate=plate, state_id=state)
                     for plate, state in [("ABC-101",active),("ABC-102",active),("ABC-103",inactive)]]
            db.session.add_all(units); db.session.commit()
            self.active = active
            self.ids = [unit.id for unit in units]

    def tearDown(self):
        with self.app.app_context():
            db.session.remove(); db.engine.dispose()

    def test_identifiers_are_unique_15_digits_and_have_luhn_control(self):
        identifiers = [generated_imei(value) for value in [1,2,46,48,2147483647]]
        self.assertEqual(len(set(identifiers)), len(identifiers))
        for value in identifiers:
            self.assertRegex(value, r"00[0-9]{13}")
            digits = [int(digit) for digit in reversed(value)]
            total = sum((digit*2)//10 + (digit*2)%10 if index%2 else digit
                        for index,digit in enumerate(digits))
            self.assertEqual(total%10,0)

    def test_plan_does_not_write_and_apply_is_idempotent(self):
        with self.app.app_context():
            with db.engine.begin() as connection:
                plan = register_missing_gps(connection)
            self.assertEqual([row["plate"] for row in plan], ["ABC-101","ABC-102"])
            self.assertEqual(GpsDevice.query.count(),0)
            with db.engine.begin() as connection:
                created = register_missing_gps(connection,apply=True)
                self.assertEqual(register_missing_gps(connection,apply=True),[])
            self.assertEqual(len(created),2)
            self.assertEqual(GpsDevice.query.count(),2)
            self.assertEqual(Vehicle.query.count(),3)
            self.assertEqual({device.vehicle_id for device in GpsDevice.query.all()}, set(self.ids[:2]))
            self.assertTrue(all(device.serial_number == "GPS-" + device.vehicle.plate for device in GpsDevice.query.all()))

    def test_existing_inactive_device_is_not_replaced_or_reactivated(self):
        with self.app.app_context():
            inactive = State.query.filter_by(name="Inactivo",type="user").one().id
            existing = GpsDevice(vehicle_id=self.ids[0],imei="860000000000001",serial_number="EQUIPO-001",state_id=inactive)
            db.session.add(existing); db.session.commit()
            original_id = existing.id
            with db.engine.begin() as connection:
                plan = register_missing_gps(connection,apply=True)
            self.assertEqual([row["vehicle_id"] for row in plan],[self.ids[1]])
            db.session.expire_all()
            preserved = db.session.get(GpsDevice,original_id)
            self.assertEqual((preserved.imei,preserved.serial_number,preserved.state_id),
                             ("860000000000001","EQUIPO-001",inactive))

    def test_identifier_collision_rolls_back_without_changing_existing_device(self):
        with self.app.app_context():
            existing = GpsDevice(vehicle_id=self.ids[1],imei=generated_imei(self.ids[0]),state_id=self.active)
            db.session.add(existing); db.session.commit()
            with self.assertRaises(ValueError):
                with db.engine.begin() as connection:
                    register_missing_gps(connection,apply=True)
            self.assertEqual(GpsDevice.query.count(),1)
            self.assertEqual(GpsDevice.query.one().vehicle_id,self.ids[1])


if __name__ == "__main__":
    unittest.main()
