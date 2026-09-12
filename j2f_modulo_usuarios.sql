-- Migración integral incremental e idempotente de J2F Monitoreo.
-- Puede ejecutarse desde psql o desde el editor SQL de Neon.
-- No crea otra base de datos, no usa DROP ni TRUNCATE y no elimina registros.

-- 001: relación multiperfil. Aplicar dentro de una transacción; no elimina datos.
BEGIN;
CREATE TABLE IF NOT EXISTS user_profile (
    user_id INTEGER NOT NULL REFERENCES users(id),
    profile_id INTEGER NOT NULL REFERENCES profiles(id),
    PRIMARY KEY (user_id, profile_id)
);
INSERT INTO user_profile (user_id, profile_id)
SELECT id, profile_id FROM users WHERE profile_id IS NOT NULL
ON CONFLICT (user_id, profile_id) DO NOTHING;
COMMIT;
-- Reversión segura: detener el despliegue nuevo y volver al código anterior.
-- No borrar user_profile: contiene asignaciones que users.profile_id no puede representar.



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



-- 004: perfil que ejecutó la acción; el historial anterior permanece con NULL.
BEGIN;
ALTER TABLE history ADD COLUMN IF NOT EXISTS profile_id INTEGER;
DO $$ BEGIN
 IF NOT EXISTS (SELECT 1 FROM pg_constraint
                WHERE conname='fk_history_profile' AND conrelid='history'::regclass) THEN
  ALTER TABLE history ADD CONSTRAINT fk_history_profile FOREIGN KEY(profile_id) REFERENCES profiles(id);
 END IF;
END $$;
CREATE INDEX IF NOT EXISTS ix_history_profile_id ON history(profile_id);
COMMIT;
-- Reversión: mantener la columna; es opcional y no afecta al código anterior.



-- 005: catálogo inicial idempotente.
BEGIN;
DO $$
BEGIN
 IF NOT EXISTS (SELECT 1 FROM states WHERE LOWER(BTRIM(name))='activo' AND type='user') THEN
  RAISE EXCEPTION 'No existe el estado Activo de tipo user';
 END IF;
END $$;
WITH active_state AS (
 SELECT id FROM states WHERE LOWER(BTRIM(name))='activo' AND type='user' ORDER BY id LIMIT 1
), seed(code,name,description,priority,generates,action) AS (VALUES
 ('SOS','Botón de pánico o SOS','Solicitud inmediata de auxilio','critical',TRUE,'Contactar al conductor y escalar según protocolo.'),
 ('SPEEDING','Exceso de velocidad','Superación del límite configurado','high',TRUE,'Verificar velocidad y contactar al responsable.'),
 ('GEOFENCE_EXIT','Salida de geocerca','Salida de una zona autorizada','high',TRUE,'Validar ruta y autorización de salida.'),
 ('GEOFENCE_ENTRY','Ingreso a geocerca','Ingreso a una zona configurada','low',FALSE,'Registrar el ingreso para trazabilidad.'),
 ('GPS_SIGNAL_LOSS','Pérdida de señal GPS','El equipo dejó de reportar posición','high',TRUE,'Comprobar cobertura y estado del dispositivo.'),
 ('POWER_CUT','Corte de alimentación del dispositivo','Pérdida de alimentación principal','critical',TRUE,'Contactar al conductor y revisar posible manipulación.'),
 ('LOW_BATTERY','Batería baja','Nivel de batería por debajo del umbral','medium',TRUE,'Programar revisión de alimentación.'),
 ('DEVICE_TAMPER','Manipulación o desconexión del dispositivo','Detección de desconexión o manipulación','critical',TRUE,'Escalar y validar físicamente el dispositivo.'),
 ('UNAUTHORIZED_MOVEMENT','Movimiento no autorizado','Movimiento fuera de una autorización vigente','critical',TRUE,'Contactar al responsable y activar protocolo de seguridad.'),
 ('OUT_OF_HOURS_IGNITION','Encendido fuera del horario permitido','Encendido detectado fuera del horario','high',TRUE,'Confirmar autorización de uso.'),
 ('PROLONGED_STOP','Parada o inactividad prolongada','Vehículo detenido más tiempo del permitido','medium',FALSE,'Revisar la operación y registrar la novedad.'),
 ('COMMUNICATION_FAILURE','Falla de comunicación del dispositivo','No se reciben tramas válidas del equipo','high',TRUE,'Revisar red, SIM y proveedor de comunicación.')
)
INSERT INTO event_types(code,name,description,default_priority,generates_alert,expected_action,state_id,created_at,updated_at)
SELECT s.code,s.name,s.description,s.priority,s.generates,s.action,a.id,CURRENT_TIMESTAMP,CURRENT_TIMESTAMP
FROM seed s CROSS JOIN active_state a
WHERE NOT EXISTS (SELECT 1 FROM event_types e WHERE e.code=s.code);
COMMIT;
-- Reversión: cambiar los registros a Inactivo; no eliminarlos si ya fueron utilizados.



-- 006: menú actual con sus agrupaciones y permisos, sin duplicar rutas.
BEGIN;
DO $$
BEGIN
 IF NOT EXISTS (SELECT 1 FROM states WHERE LOWER(BTRIM(name))='activo' AND type='user') THEN
  RAISE EXCEPTION 'No existe el estado Activo de tipo user';
 END IF;
END $$;
WITH active_state AS (
 SELECT id FROM states WHERE LOWER(BTRIM(name))='activo' AND type='user' ORDER BY id LIMIT 1
), sections(name,icon,menu_order) AS (VALUES
 ('MONITOREO','folder',0),('SEGUIMIENTO','folder',40),('ADMINISTRACIÓN','folder',60)
)
INSERT INTO menu_options(name,url,icon,parent_id,"order",state_id,created_at,updated_at)
SELECT s.name,NULL,s.icon,NULL,s.menu_order,a.id,CURRENT_TIMESTAMP,CURRENT_TIMESTAMP
FROM sections s CROSS JOIN active_state a
WHERE NOT EXISTS (SELECT 1 FROM menu_options m WHERE m.url IS NULL AND LOWER(m.name)=LOWER(s.name));

WITH active_state AS (
 SELECT id FROM states WHERE LOWER(BTRIM(name))='activo' AND type='user' ORDER BY id LIMIT 1
), seed(name,url,icon,menu_order,parent_name) AS (VALUES
 ('Panel de control','/dashboard','dashboard',10,'MONITOREO'),
 ('Alertas','/alerts','alerts',20,'MONITOREO'),
 ('Asignaciones','/assignments','assignments',30,'MONITOREO'),
 ('Historial','/history','history',40,'SEGUIMIENTO'),
 ('Reportes','/reports','reports',50,'SEGUIMIENTO'),
 ('Usuarios','/admin/users','users',60,'ADMINISTRACIÓN'),
 ('Perfiles','/admin/profiles','profiles',70,'ADMINISTRACIÓN'),
 ('Opciones de menú','/admin/menu-options','menu',80,'ADMINISTRACIÓN'),
 ('Datos maestros','/admin/master-data','database',90,'ADMINISTRACIÓN')
)
INSERT INTO menu_options(name,url,icon,parent_id,"order",state_id,created_at,updated_at)
SELECT s.name,s.url,s.icon,(SELECT MIN(id) FROM menu_options WHERE url IS NULL AND LOWER(name)=LOWER(s.parent_name)),s.menu_order,a.id,CURRENT_TIMESTAMP,CURRENT_TIMESTAMP
FROM seed s CROSS JOIN active_state a WHERE NOT EXISTS (SELECT 1 FROM menu_options m WHERE m.url=s.url);

WITH mapping(url,parent_name) AS (VALUES
 ('/dashboard','MONITOREO'),('/alerts','MONITOREO'),('/assignments','MONITOREO'),
 ('/history','SEGUIMIENTO'),('/reports','SEGUIMIENTO'),('/admin/users','ADMINISTRACIÓN'),
 ('/admin/profiles','ADMINISTRACIÓN'),('/admin/menu-options','ADMINISTRACIÓN'),
 ('/admin/master-data','ADMINISTRACIÓN')
)
UPDATE menu_options child SET parent_id=parent.id,updated_at=CURRENT_TIMESTAMP
FROM mapping x JOIN menu_options parent ON parent.url IS NULL AND LOWER(parent.name)=LOWER(x.parent_name)
WHERE child.url=x.url AND child.parent_id IS DISTINCT FROM parent.id;

WITH access(url,role) AS (VALUES
 ('/dashboard','administrador'),('/alerts','administrador'),('/assignments','administrador'),('/history','administrador'),('/reports','administrador'),
 ('/admin/users','administrador'),('/admin/profiles','administrador'),('/admin/menu-options','administrador'),('/admin/master-data','administrador'),
 ('/dashboard','tecnico'),('/alerts','tecnico'),('/assignments','tecnico'),('/history','tecnico')
)
INSERT INTO profile_menu_option(profile_id,menu_option_id)
SELECT p.id,m.id FROM access a JOIN profiles p ON
 ((a.role='administrador' AND LOWER(BTRIM(p.name))='administrador') OR
  (a.role='tecnico' AND LOWER(BTRIM(p.name)) IN ('tecnico','técnico')))
JOIN menu_options m ON m.url=a.url
ON CONFLICT (profile_id,menu_option_id) DO NOTHING;

INSERT INTO profile_menu_option(profile_id,menu_option_id)
SELECT DISTINCT child_access.profile_id,parent.id FROM profile_menu_option child_access
JOIN menu_options child ON child.id=child_access.menu_option_id
JOIN menu_options parent ON parent.id=child.parent_id
ON CONFLICT (profile_id,menu_option_id) DO NOTHING;
COMMIT;
-- Reversión: desactivar las opciones nuevas desde el CRUD; no borrar permisos usados.



-- 007: datos de demostración para probar filtros cliente → vehículo → alerta.
-- Es idempotente y no modifica ni elimina registros existentes.
BEGIN;

DO $$
BEGIN
 IF NOT EXISTS (SELECT 1 FROM states WHERE LOWER(BTRIM(name))='activo' AND type='user') THEN
  RAISE EXCEPTION 'No existe el estado Activo de tipo user';
 END IF;
 IF NOT EXISTS (SELECT 1 FROM states WHERE name IN ('Abierto','En Progreso','Cerrado') AND type='alert') THEN
  RAISE EXCEPTION 'Faltan estados base de alertas';
 END IF;
END $$;

WITH active_state AS (
 SELECT id FROM states WHERE LOWER(BTRIM(name))='activo' AND type='user' ORDER BY id LIMIT 1
), seed(document_number,business_name,contact_name,phone,email,address) AS (VALUES
 ('J2F-DEMO-001','Transportes Andinos Demo','Ana Torres','900000001','andinos.demo@example.invalid','Lima'),
 ('J2F-DEMO-002','Logística del Pacífico Demo','Luis Medina','900000002','pacifico.demo@example.invalid','Callao'),
 ('J2F-DEMO-003','Distribuciones del Sur Demo','Rosa Vargas','900000003','sur.demo@example.invalid','Arequipa')
)
INSERT INTO clients(document_type,document_number,business_name,contact_name,phone,email,address,state_id,created_at,updated_at)
SELECT 'RUC',s.document_number,s.business_name,s.contact_name,s.phone,s.email,s.address,a.id,CURRENT_TIMESTAMP,CURRENT_TIMESTAMP
FROM seed s CROSS JOIN active_state a
ON CONFLICT (document_number) DO UPDATE SET
 business_name=EXCLUDED.business_name,contact_name=EXCLUDED.contact_name,phone=EXCLUDED.phone,
 email=EXCLUDED.email,address=EXCLUDED.address
WHERE (clients.business_name,clients.contact_name,clients.phone,clients.email,clients.address)
 IS DISTINCT FROM (EXCLUDED.business_name,EXCLUDED.contact_name,EXCLUDED.phone,EXCLUDED.email,EXCLUDED.address);

WITH active_state AS (
 SELECT id FROM states WHERE LOWER(BTRIM(name))='activo' AND type='user' ORDER BY id LIMIT 1
), seed(document_number,plate,brand,model,color,vehicle_type) AS (VALUES
 ('J2F-DEMO-001','J2F-A01','Toyota','Hilux','Blanco','Camioneta'),
 ('J2F-DEMO-001','J2F-A02','Hino','300','Azul','Camión'),
 ('J2F-DEMO-001','J2F-A03','Nissan','Frontier','Gris','Camioneta'),
 ('J2F-DEMO-002','J2F-P01','Volvo','FH','Rojo','Tráiler'),
 ('J2F-DEMO-002','J2F-P02','Scania','P360','Blanco','Camión'),
 ('J2F-DEMO-002','J2F-P03','Mercedes-Benz','Actros','Azul','Tráiler'),
 ('J2F-DEMO-003','J2F-S01','Kia','K2700','Blanco','Furgón'),
 ('J2F-DEMO-003','J2F-S02','Hyundai','H100','Plata','Furgón'),
 ('J2F-DEMO-003','J2F-S03','Isuzu','NPR','Blanco','Camión')
)
INSERT INTO vehicles(client_id,plate,brand,model,color,vehicle_type,state_id,created_at,updated_at)
SELECT c.id,s.plate,s.brand,s.model,s.color,s.vehicle_type,a.id,CURRENT_TIMESTAMP,CURRENT_TIMESTAMP
FROM seed s JOIN clients c ON c.document_number=s.document_number CROSS JOIN active_state a
ON CONFLICT (plate) DO UPDATE SET
 client_id=EXCLUDED.client_id,brand=EXCLUDED.brand,model=EXCLUDED.model,
 color=EXCLUDED.color,vehicle_type=EXCLUDED.vehicle_type
WHERE (vehicles.client_id,vehicles.brand,vehicles.model,vehicles.color,vehicles.vehicle_type)
 IS DISTINCT FROM (EXCLUDED.client_id,EXCLUDED.brand,EXCLUDED.model,EXCLUDED.color,EXCLUDED.vehicle_type);

WITH seed(plate,event_code,label,priority,state_name,hours_ago) AS (VALUES
 ('J2F-A01','SPEEDING','Exceso de velocidad','high','Abierto',2),
 ('J2F-A01','GPS_SIGNAL_LOSS','Pérdida de señal','critical','En Progreso',8),
 ('J2F-A02','GEOFENCE_EXIT','Salida de geocerca','high','Cerrado',25),
 ('J2F-A02','LOW_BATTERY','Batería baja','medium','Abierto',4),
 ('J2F-A03','POWER_CUT','Corte de alimentación','critical','En Progreso',12),
 ('J2F-A03','PROLONGED_STOP','Inactividad prolongada','low','Cerrado',48),
 ('J2F-P01','SPEEDING','Exceso de velocidad','high','En Progreso',3),
 ('J2F-P01','DEVICE_TAMPER','Manipulación de dispositivo','critical','Abierto',7),
 ('J2F-P02','OUT_OF_HOURS_IGNITION','Encendido fuera de horario','high','Cerrado',30),
 ('J2F-P02','GPS_SIGNAL_LOSS','Pérdida de señal','medium','Abierto',5),
 ('J2F-P03','UNAUTHORIZED_MOVEMENT','Movimiento no autorizado','critical','En Progreso',10),
 ('J2F-P03','COMMUNICATION_FAILURE','Falla de comunicación','high','Cerrado',52),
 ('J2F-S01','GEOFENCE_EXIT','Salida de geocerca','high','Abierto',1),
 ('J2F-S01','LOW_BATTERY','Batería baja','medium','En Progreso',6),
 ('J2F-S02','POWER_CUT','Corte de alimentación','critical','Cerrado',28),
 ('J2F-S02','SPEEDING','Exceso de velocidad','high','Abierto',9),
 ('J2F-S03','COMMUNICATION_FAILURE','Falla de comunicación','high','En Progreso',14),
 ('J2F-S03','PROLONGED_STOP','Inactividad prolongada','low','Cerrado',60)
)
INSERT INTO alerts(title,description,priority,service_type,location,source,state_id,vehicle_id,event_type_id,
                   opened_at,acknowledged_at,resolved_at,created_at,updated_at)
SELECT seed.label || ' - ' || seed.plate,
       'Alerta de demostración para validar la consulta por cliente y vehículo.',
       seed.priority,'Monitoreo GPS','Ubicación de prueba','Datos de prueba J2F',state.id,vehicle.id,event_type.id,
       CURRENT_TIMESTAMP-(seed.hours_ago::text || ' hours')::interval,
       CASE WHEN seed.state_name IN ('En Progreso','Cerrado') THEN CURRENT_TIMESTAMP-((seed.hours_ago-1)::text || ' hours')::interval END,
       CASE WHEN seed.state_name='Cerrado' THEN CURRENT_TIMESTAMP-((seed.hours_ago-2)::text || ' hours')::interval END,
       CURRENT_TIMESTAMP-(seed.hours_ago::text || ' hours')::interval,CURRENT_TIMESTAMP
FROM seed
JOIN vehicles vehicle ON vehicle.plate=seed.plate
JOIN states state ON state.name=seed.state_name AND state.type='alert'
LEFT JOIN event_types event_type ON event_type.code=seed.event_code
WHERE NOT EXISTS (
 SELECT 1 FROM alerts existing
 WHERE existing.source='Datos de prueba J2F' AND existing.vehicle_id=vehicle.id
   AND existing.event_type_id=event_type.id
);

UPDATE alerts demo
SET title=event_type.name || ' - ' || vehicle.plate,
    description='Alerta de demostración para validar la consulta por cliente y vehículo.',
    location='Ubicación de prueba'
FROM vehicles vehicle CROSS JOIN event_types event_type
WHERE demo.source='Datos de prueba J2F' AND demo.vehicle_id=vehicle.id
  AND event_type.id=demo.event_type_id
  AND vehicle.plate LIKE 'J2F-%'
  AND (demo.title,demo.description,demo.location) IS DISTINCT FROM
      (event_type.name || ' - ' || vehicle.plate,
       'Alerta de demostración para validar la consulta por cliente y vehículo.',
       'Ubicación de prueba');

COMMIT;
-- Reversión segura: conservar los registros. Pueden identificarse por source='Datos de prueba J2F'
-- y desactivarse desde los CRUD; no borrarlos si ya tienen asignaciones o historial.
