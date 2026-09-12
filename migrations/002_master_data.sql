-- 002: datos maestros. Usa los estados Activo/Inactivo ya existentes.
BEGIN;
CREATE TABLE IF NOT EXISTS clients (
 id SERIAL PRIMARY KEY, document_type VARCHAR(20) NOT NULL,
 document_number VARCHAR(30) NOT NULL UNIQUE, business_name VARCHAR(180) NOT NULL,
 contact_name VARCHAR(150), phone VARCHAR(30), email VARCHAR(150), address VARCHAR(255),
 state_id INTEGER NOT NULL REFERENCES states(id), created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
 updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);
CREATE TABLE IF NOT EXISTS vehicles (
 id SERIAL PRIMARY KEY, client_id INTEGER NOT NULL REFERENCES clients(id),
 plate VARCHAR(20) NOT NULL UNIQUE, brand VARCHAR(100), model VARCHAR(100), color VARCHAR(50),
 vehicle_type VARCHAR(80), state_id INTEGER NOT NULL REFERENCES states(id),
 created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP, updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);
CREATE TABLE IF NOT EXISTS gps_devices (
 id SERIAL PRIMARY KEY, vehicle_id INTEGER NOT NULL REFERENCES vehicles(id),
 imei VARCHAR(40) NOT NULL UNIQUE, serial_number VARCHAR(80) UNIQUE, model VARCHAR(100),
 provider VARCHAR(100), sim_number VARCHAR(30), state_id INTEGER NOT NULL REFERENCES states(id),
 created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP, updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);
CREATE TABLE IF NOT EXISTS event_types (
 id SERIAL PRIMARY KEY, code VARCHAR(50) NOT NULL UNIQUE, name VARCHAR(150) NOT NULL,
 description TEXT, default_priority VARCHAR(20) NOT NULL DEFAULT 'medium',
 generates_alert BOOLEAN NOT NULL DEFAULT TRUE, expected_action TEXT,
 state_id INTEGER NOT NULL REFERENCES states(id), created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
 updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
 CONSTRAINT ck_event_types_priority CHECK (default_priority IN ('critical','high','medium','low'))
);
CREATE INDEX IF NOT EXISTS ix_clients_state_id ON clients(state_id);
CREATE INDEX IF NOT EXISTS ix_vehicles_client_id ON vehicles(client_id);
CREATE INDEX IF NOT EXISTS ix_vehicles_state_id ON vehicles(state_id);
CREATE INDEX IF NOT EXISTS ix_gps_devices_vehicle_id ON gps_devices(vehicle_id);
CREATE INDEX IF NOT EXISTS ix_gps_devices_state_id ON gps_devices(state_id);
CREATE INDEX IF NOT EXISTS ix_event_types_state_id ON event_types(state_id);
COMMIT;
-- Reversión segura: conservar tablas y desactivar sus opciones de menú. No eliminarlas
-- mientras alguna alerta pueda referenciarlas.
