-- 003: relaciones opcionales; las alertas existentes conservan NULL.
BEGIN;
ALTER TABLE alerts ADD COLUMN IF NOT EXISTS vehicle_id INTEGER;
ALTER TABLE alerts ADD COLUMN IF NOT EXISTS gps_device_id INTEGER;
ALTER TABLE alerts ADD COLUMN IF NOT EXISTS event_type_id INTEGER;
DO $$ BEGIN
 IF NOT EXISTS (SELECT 1 FROM pg_constraint
                WHERE conname='fk_alerts_vehicle' AND conrelid='alerts'::regclass) THEN
  ALTER TABLE alerts ADD CONSTRAINT fk_alerts_vehicle FOREIGN KEY(vehicle_id) REFERENCES vehicles(id);
 END IF;
 IF NOT EXISTS (SELECT 1 FROM pg_constraint
                WHERE conname='fk_alerts_gps_device' AND conrelid='alerts'::regclass) THEN
  ALTER TABLE alerts ADD CONSTRAINT fk_alerts_gps_device FOREIGN KEY(gps_device_id) REFERENCES gps_devices(id);
 END IF;
 IF NOT EXISTS (SELECT 1 FROM pg_constraint
                WHERE conname='fk_alerts_event_type' AND conrelid='alerts'::regclass) THEN
  ALTER TABLE alerts ADD CONSTRAINT fk_alerts_event_type FOREIGN KEY(event_type_id) REFERENCES event_types(id);
 END IF;
END $$;
CREATE INDEX IF NOT EXISTS ix_alerts_vehicle_id ON alerts(vehicle_id);
CREATE INDEX IF NOT EXISTS ix_alerts_gps_device_id ON alerts(gps_device_id);
CREATE INDEX IF NOT EXISTS ix_alerts_event_type_id ON alerts(event_type_id);
COMMIT;
-- Reversión: el código anterior ignora estas columnas. No quitarlas sin comprobar NULL y respaldar.
