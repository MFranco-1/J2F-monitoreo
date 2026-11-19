-- PostgreSQL: esquema original, generado a partir de los modelos del ZIP recibido.
-- Ejecutar sobre una base VACÍA; para base existente usar 03_actualizacion.sql.
BEGIN;

CREATE TABLE states (
	id SERIAL NOT NULL,
	name VARCHAR(50) NOT NULL,
	type VARCHAR(20) NOT NULL,
	description VARCHAR(255),
	created_at TIMESTAMP WITHOUT TIME ZONE,
	PRIMARY KEY (id),
	UNIQUE (name)
)

;

CREATE TABLE clients (
	id SERIAL NOT NULL,
	document_type VARCHAR(20) NOT NULL,
	document_number VARCHAR(30) NOT NULL,
	business_name VARCHAR(180) NOT NULL,
	contact_name VARCHAR(150),
	phone VARCHAR(30),
	email VARCHAR(150),
	address VARCHAR(255),
	verification_json TEXT,
	state_id INTEGER NOT NULL,
	created_at TIMESTAMP WITHOUT TIME ZONE,
	updated_at TIMESTAMP WITHOUT TIME ZONE,
	PRIMARY KEY (id),
	FOREIGN KEY(state_id) REFERENCES states (id)
)

;
CREATE INDEX ix_clients_state_id ON clients (state_id);
CREATE UNIQUE INDEX ix_clients_document_number ON clients (document_number);

CREATE TABLE event_types (
	id SERIAL NOT NULL,
	code VARCHAR(50) NOT NULL,
	name VARCHAR(150) NOT NULL,
	description TEXT,
	default_priority VARCHAR(20) NOT NULL,
	generates_alert BOOLEAN NOT NULL,
	expected_action TEXT,
	state_id INTEGER NOT NULL,
	created_at TIMESTAMP WITHOUT TIME ZONE,
	updated_at TIMESTAMP WITHOUT TIME ZONE,
	PRIMARY KEY (id),
	FOREIGN KEY(state_id) REFERENCES states (id)
)

;
CREATE INDEX ix_event_types_state_id ON event_types (state_id);
CREATE UNIQUE INDEX ix_event_types_code ON event_types (code);

CREATE TABLE menu_options (
	id SERIAL NOT NULL,
	name VARCHAR(100) NOT NULL,
	url VARCHAR(255),
	icon VARCHAR(100),
	parent_id INTEGER,
	"order" INTEGER,
	state_id INTEGER NOT NULL,
	created_at TIMESTAMP WITHOUT TIME ZONE,
	updated_at TIMESTAMP WITHOUT TIME ZONE,
	PRIMARY KEY (id),
	FOREIGN KEY(parent_id) REFERENCES menu_options (id),
	FOREIGN KEY(state_id) REFERENCES states (id)
)

;

CREATE TABLE profiles (
	id SERIAL NOT NULL,
	name VARCHAR(100) NOT NULL,
	description VARCHAR(255),
	state_id INTEGER NOT NULL,
	created_at TIMESTAMP WITHOUT TIME ZONE,
	updated_at TIMESTAMP WITHOUT TIME ZONE,
	PRIMARY KEY (id),
	UNIQUE (name),
	FOREIGN KEY(state_id) REFERENCES states (id)
)

;

CREATE TABLE profile_menu_option (
	profile_id INTEGER NOT NULL,
	menu_option_id INTEGER NOT NULL,
	PRIMARY KEY (profile_id, menu_option_id),
	FOREIGN KEY(profile_id) REFERENCES profiles (id),
	FOREIGN KEY(menu_option_id) REFERENCES menu_options (id)
)

;

CREATE TABLE users (
	id SERIAL NOT NULL,
	dni VARCHAR(20) NOT NULL,
	full_name VARCHAR(150) NOT NULL,
	email VARCHAR(150) NOT NULL,
	password_hash VARCHAR(256) NOT NULL,
	profile_id INTEGER,
	state_id INTEGER NOT NULL,
	last_login TIMESTAMP WITHOUT TIME ZONE,
	created_at TIMESTAMP WITHOUT TIME ZONE,
	updated_at TIMESTAMP WITHOUT TIME ZONE,
	PRIMARY KEY (id),
	FOREIGN KEY(profile_id) REFERENCES profiles (id),
	FOREIGN KEY(state_id) REFERENCES states (id)
)

;
CREATE UNIQUE INDEX ix_users_dni ON users (dni);
CREATE UNIQUE INDEX ix_users_email ON users (email);

CREATE TABLE vehicles (
	id SERIAL NOT NULL,
	client_id INTEGER NOT NULL,
	plate VARCHAR(20) NOT NULL,
	brand VARCHAR(100),
	model VARCHAR(100),
	color VARCHAR(50),
	vehicle_type VARCHAR(80),
	state_id INTEGER NOT NULL,
	created_at TIMESTAMP WITHOUT TIME ZONE,
	updated_at TIMESTAMP WITHOUT TIME ZONE,
	PRIMARY KEY (id),
	FOREIGN KEY(client_id) REFERENCES clients (id),
	FOREIGN KEY(state_id) REFERENCES states (id)
)

;
CREATE INDEX ix_vehicles_client_id ON vehicles (client_id);
CREATE INDEX ix_vehicles_state_id ON vehicles (state_id);
CREATE UNIQUE INDEX ix_vehicles_plate ON vehicles (plate);

CREATE TABLE gps_devices (
	id SERIAL NOT NULL,
	vehicle_id INTEGER NOT NULL,
	imei VARCHAR(40) NOT NULL,
	serial_number VARCHAR(80),
	model VARCHAR(100),
	provider VARCHAR(100),
	sim_number VARCHAR(30),
	state_id INTEGER NOT NULL,
	created_at TIMESTAMP WITHOUT TIME ZONE,
	updated_at TIMESTAMP WITHOUT TIME ZONE,
	PRIMARY KEY (id),
	FOREIGN KEY(vehicle_id) REFERENCES vehicles (id),
	UNIQUE (serial_number),
	FOREIGN KEY(state_id) REFERENCES states (id)
)

;
CREATE INDEX ix_gps_devices_state_id ON gps_devices (state_id);
CREATE UNIQUE INDEX ix_gps_devices_imei ON gps_devices (imei);
CREATE INDEX ix_gps_devices_vehicle_id ON gps_devices (vehicle_id);

CREATE TABLE reports (
	id SERIAL NOT NULL,
	name VARCHAR(200) NOT NULL,
	type VARCHAR(50) NOT NULL,
	description TEXT,
	filters_json TEXT,
	date_range_start TIMESTAMP WITHOUT TIME ZONE,
	date_range_end TIMESTAMP WITHOUT TIME ZONE,
	generated_by INTEGER,
	result_json TEXT,
	created_at TIMESTAMP WITHOUT TIME ZONE,
	PRIMARY KEY (id),
	FOREIGN KEY(generated_by) REFERENCES users (id)
)

;

CREATE TABLE user_profile (
	user_id INTEGER NOT NULL,
	profile_id INTEGER NOT NULL,
	PRIMARY KEY (user_id, profile_id),
	FOREIGN KEY(user_id) REFERENCES users (id),
	FOREIGN KEY(profile_id) REFERENCES profiles (id)
)

;

CREATE TABLE alerts (
	id SERIAL NOT NULL,
	title VARCHAR(200) NOT NULL,
	description TEXT,
	priority VARCHAR(20) NOT NULL,
	service_type VARCHAR(100),
	location VARCHAR(200),
	source VARCHAR(100),
	state_id INTEGER NOT NULL,
	vehicle_id INTEGER,
	gps_device_id INTEGER,
	event_type_id INTEGER,
	created_by INTEGER,
	opened_at TIMESTAMP WITHOUT TIME ZONE,
	acknowledged_at TIMESTAMP WITHOUT TIME ZONE,
	resolved_at TIMESTAMP WITHOUT TIME ZONE,
	created_at TIMESTAMP WITHOUT TIME ZONE,
	updated_at TIMESTAMP WITHOUT TIME ZONE,
	PRIMARY KEY (id),
	FOREIGN KEY(state_id) REFERENCES states (id),
	FOREIGN KEY(vehicle_id) REFERENCES vehicles (id),
	FOREIGN KEY(gps_device_id) REFERENCES gps_devices (id),
	FOREIGN KEY(event_type_id) REFERENCES event_types (id),
	FOREIGN KEY(created_by) REFERENCES users (id)
)

;
CREATE INDEX ix_alerts_priority ON alerts (priority);
CREATE INDEX ix_alerts_state_id ON alerts (state_id);
CREATE INDEX ix_alerts_gps_device_id ON alerts (gps_device_id);
CREATE INDEX ix_alerts_event_type_id ON alerts (event_type_id);
CREATE INDEX ix_alerts_vehicle_id ON alerts (vehicle_id);

CREATE TABLE assignments (
	id SERIAL NOT NULL,
	alert_id INTEGER NOT NULL,
	user_id INTEGER NOT NULL,
	notes TEXT,
	assignment_type VARCHAR(20),
	assigned_at TIMESTAMP WITHOUT TIME ZONE,
	completed_at TIMESTAMP WITHOUT TIME ZONE,
	response_time_minutes FLOAT,
	PRIMARY KEY (id),
	FOREIGN KEY(alert_id) REFERENCES alerts (id),
	FOREIGN KEY(user_id) REFERENCES users (id)
)

;
CREATE INDEX ix_assignments_user_id ON assignments (user_id);
CREATE INDEX ix_assignments_alert_id ON assignments (alert_id);

CREATE TABLE history (
	id SERIAL NOT NULL,
	alert_id INTEGER NOT NULL,
	user_id INTEGER,
	profile_id INTEGER,
	action VARCHAR(50) NOT NULL,
	previous_state VARCHAR(100),
	new_state VARCHAR(100),
	detail TEXT,
	timestamp TIMESTAMP WITHOUT TIME ZONE,
	PRIMARY KEY (id),
	FOREIGN KEY(alert_id) REFERENCES alerts (id),
	FOREIGN KEY(user_id) REFERENCES users (id),
	FOREIGN KEY(profile_id) REFERENCES profiles (id)
)

;
CREATE INDEX ix_history_alert_id ON history (alert_id);
CREATE INDEX ix_history_timestamp ON history (timestamp);
COMMIT;
