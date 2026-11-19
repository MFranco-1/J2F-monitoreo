-- Catálogos iniciales: son datos editables en PostgreSQL, no listas en Python/HTML.
BEGIN;
CREATE TABLE IF NOT EXISTS app_parameters(key text PRIMARY KEY,value jsonb NOT NULL,description text NOT NULL);
CREATE TABLE IF NOT EXISTS priorities(code varchar(20) PRIMARY KEY,label text NOT NULL,rank integer NOT NULL UNIQUE);
CREATE TABLE IF NOT EXISTS document_types(code varchar(20) PRIMARY KEY,label text NOT NULL,pattern text NOT NULL);
CREATE TABLE IF NOT EXISTS report_types(code varchar(50) PRIMARY KEY,label text NOT NULL);
CREATE TABLE IF NOT EXISTS permissions(code text PRIMARY KEY,description text NOT NULL);
CREATE TABLE IF NOT EXISTS profile_permissions(profile_id integer REFERENCES profiles(id) ON DELETE CASCADE,permission_code text REFERENCES permissions(code),PRIMARY KEY(profile_id,permission_code));
ALTER TABLE states ADD COLUMN IF NOT EXISTS code text;
ALTER TABLE states ADD COLUMN IF NOT EXISTS is_active boolean NOT NULL DEFAULT false;
ALTER TABLE states ADD COLUMN IF NOT EXISTS is_terminal boolean NOT NULL DEFAULT false;
ALTER TABLE states ADD COLUMN IF NOT EXISTS is_resolution boolean NOT NULL DEFAULT false;
ALTER TABLE profiles ADD COLUMN IF NOT EXISTS role_code text;
ALTER TABLE users ADD COLUMN IF NOT EXISTS session_version integer NOT NULL DEFAULT 0;
CREATE TABLE IF NOT EXISTS alert_transitions(from_state_id integer REFERENCES states(id),to_state_id integer REFERENCES states(id),PRIMARY KEY(from_state_id,to_state_id));
CREATE TABLE IF NOT EXISTS simulated_events(event_type_id integer PRIMARY KEY REFERENCES event_types(id));
CREATE TABLE IF NOT EXISTS app_resources(code text PRIMARY KEY,table_name text NOT NULL UNIQUE,singular text NOT NULL,write_permission text NOT NULL REFERENCES permissions(code));
INSERT INTO priorities VALUES ('critical','Crítica',1),('high','Alta',2),('medium','Media',3),('low','Baja',4) ON CONFLICT DO NOTHING;
INSERT INTO document_types VALUES ('RUC','RUC','^[0-9]{11}$'),('DNI','DNI','^[0-9]{8}$'),('CE','Carné de extranjería','^[0-9]{9,12}$'),('PASAPORTE','Pasaporte','^[A-Z0-9]{6,12}$'),('Código interno','Código interno','^.{1,30}$') ON CONFLICT DO NOTHING;
INSERT INTO report_types VALUES ('alerts_summary','Resumen de alertas'),('operator_performance','Rendimiento por técnico'),('response_times','Tiempos de respuesta') ON CONFLICT DO NOTHING;
INSERT INTO permissions VALUES ('admin','Administrar catálogos, usuarios y perfiles'),('assign','Crear alertas y distribuir trabajo'),('reports','Consultar y generar reportes'),('cancel','Anular alertas'),('view_all','Consultar toda la operación'),('attend','Atender casos asignados'),('supervise','Supervisar la operación') ON CONFLICT DO NOTHING;
INSERT INTO states(name,type,code,is_active,is_terminal,is_resolution) VALUES
('Activo','user','active',true,false,false),('Inactivo','user','inactive',false,false,false),
('Abierto','alert','open',false,false,false),('En Progreso','alert','in_progress',false,false,false),
('Escalado','alert','escalated',false,false,false),('Cerrado','alert','closed',false,true,true),('Anulado','alert','cancelled',false,true,false)
ON CONFLICT(name) DO UPDATE SET code=EXCLUDED.code,is_active=EXCLUDED.is_active,is_terminal=EXCLUDED.is_terminal,is_resolution=EXCLUDED.is_resolution;
CREATE UNIQUE INDEX IF NOT EXISTS ux_states_code ON states(code);
INSERT INTO profiles(name,description,state_id,created_at,updated_at) SELECT v.name,v.description,s.id,now(),now() FROM (VALUES ('Administrador','Administración'),('Supervisor','Supervisión'),('Operador','Monitoreo y asignación'),('Técnico','Atención de casos')) v(name,description) CROSS JOIN states s WHERE s.code='active' ON CONFLICT(name) DO NOTHING;
UPDATE profiles SET role_code=CASE lower(translate(name,'éÉ','eE')) WHEN 'administrador' THEN 'admin' WHEN 'supervisor' THEN 'supervisor' WHEN 'operador' THEN 'operator' WHEN 'tecnico' THEN 'technician' ELSE role_code END WHERE role_code IS NULL;
INSERT INTO profile_permissions SELECT p.id,v.permission FROM profiles p JOIN (VALUES
('admin','admin'),('admin','assign'),('admin','reports'),('admin','cancel'),('admin','view_all'),('admin','attend'),
('supervisor','supervise'),('supervisor','assign'),('supervisor','reports'),('supervisor','cancel'),('supervisor','view_all'),
('operator','assign'),('operator','view_all'),('technician','attend')) v(role,permission) ON p.role_code=v.role ON CONFLICT DO NOTHING;
INSERT INTO user_profile SELECT id,profile_id FROM users WHERE profile_id IS NOT NULL ON CONFLICT DO NOTHING;
INSERT INTO alert_transitions SELECT a.id,b.id FROM (VALUES ('open','in_progress'),('open','escalated'),('open','closed'),('in_progress','closed'),('in_progress','escalated'),('in_progress','open'),('escalated','in_progress'),('escalated','closed')) v(a,b) JOIN states a ON a.code=v.a JOIN states b ON b.code=v.b ON CONFLICT DO NOTHING;
INSERT INTO event_types(code,name,description,default_priority,generates_alert,state_id,created_at,updated_at) SELECT v.code,v.name,v.name,v.priority,true,s.id,now(),now() FROM (VALUES ('SPEEDING','Exceso de velocidad','high'),('GPS_SIGNAL_LOSS','Pérdida de señal GPS','high'),('SOS','Botón de pánico','critical'),('LOW_FUEL','Combustible bajo','high')) v(code,name,priority) CROSS JOIN states s WHERE s.code='active' ON CONFLICT(code) DO NOTHING;
INSERT INTO simulated_events SELECT id FROM event_types WHERE code IN ('SPEEDING','GPS_SIGNAL_LOSS','SOS','LOW_FUEL') ON CONFLICT DO NOTHING;
INSERT INTO app_resources VALUES ('users','users','user','admin'),('profiles','profiles','profile','admin'),('menu-options','menu_options','menu_option','admin'),('clients','clients','record','admin'),('vehicles','vehicles','record','admin'),('gps-devices','gps_devices','record','admin'),('event-types','event_types','record','admin'),('alerts','alerts','alert','assign'),('assignments','assignments','assignment','assign'),('reports','reports','report','reports') ON CONFLICT DO NOTHING;
INSERT INTO app_parameters VALUES ('simulation', '{"movementIntervalMs": 2000, "eventsIntervalMs": 10000, "confirmedFuelPercent": 70, "lowFuelInitialPercent": 8, "triggeredLowFuelPercent": 9, "initialFuelMinPercent": 58, "initialFuelSpread": 30, "minSpeedKmh": 38, "initialSpeedSpread": 42, "speedSpread": 43, "speedVariationPerTick": 3, "fuelConsumedPerTick": 0.015, "speedingEventKmh": 96, "initialPositionSpacing": 37, "vehicleVariation": 7, "speedVehicleVariation": 11, "stationCandidates": 8, "center": [-12.083, -77.052], "initialZoom": 11, "maxZoom": 18, "tileUrl": "https://tile.openstreetmap.org/{z}/{x}/{y}.png", "routes": [[{"lat": -12.0478, "lng": -77.0622}, {"lat": -12.1047, "lng": -77.0306}], [{"lat": -12.0526, "lng": -77.1171}, {"lat": -12.0964, "lng": -77.0473}], [{"lat": -12.1177, "lng": -77.0357}, {"lat": -12.1738, "lng": -76.987}]]}'::jsonb, 'Parámetro simulation') ON CONFLICT DO NOTHING;
INSERT INTO app_parameters VALUES ('low_fuel_threshold', '10'::jsonb, 'Parámetro low_fuel_threshold') ON CONFLICT DO NOTHING;
INSERT INTO app_parameters VALUES ('default_priority', '"medium"'::jsonb, 'Parámetro default_priority') ON CONFLICT DO NOTHING;
INSERT INTO app_parameters VALUES ('default_report_type', '"alerts_summary"'::jsonb, 'Parámetro default_report_type') ON CONFLICT DO NOTHING;
INSERT INTO app_parameters VALUES ('fuel_event_code', '"LOW_FUEL"'::jsonb, 'Parámetro fuel_event_code') ON CONFLICT DO NOTHING;
INSERT INTO app_parameters VALUES ('page_size', '20'::jsonb, 'Parámetro page_size') ON CONFLICT DO NOTHING;
INSERT INTO app_parameters VALUES ('max_page_size', '100'::jsonb, 'Parámetro max_page_size') ON CONFLICT DO NOTHING;
INSERT INTO app_parameters VALUES ('critical_list_limit', '7'::jsonb, 'Parámetro critical_list_limit') ON CONFLICT DO NOTHING;
INSERT INTO app_parameters VALUES ('station_search', '{"radius": 3000, "minimum": 100, "maximum": 10000, "timeout": 10}'::jsonb, 'Parámetro station_search') ON CONFLICT DO NOTHING;
INSERT INTO app_parameters VALUES ('default_phone_country', '"PE"'::jsonb, 'Parámetro default_phone_country') ON CONFLICT DO NOTHING;
INSERT INTO app_parameters VALUES ('default_state_code', '"active"'::jsonb, 'Parámetro default_state_code') ON CONFLICT DO NOTHING;
INSERT INTO app_parameters VALUES ('initial_alert_state_code', '"open"'::jsonb, 'Parámetro initial_alert_state_code') ON CONFLICT DO NOTHING;
INSERT INTO app_parameters VALUES ('working_alert_state_code', '"in_progress"'::jsonb, 'Parámetro working_alert_state_code') ON CONFLICT DO NOTHING;
INSERT INTO app_parameters VALUES ('resolved_alert_state_code', '"closed"'::jsonb, 'Parámetro resolved_alert_state_code') ON CONFLICT DO NOTHING;
INSERT INTO app_parameters VALUES ('cancelled_alert_state_code', '"cancelled"'::jsonb, 'Parámetro cancelled_alert_state_code') ON CONFLICT DO NOTHING;
-- Las columnas que antes recibían fechas/defaults desde SQLAlchemy ahora los reciben en la BD.
DO $$ DECLARE c record; BEGIN FOR c IN SELECT table_name,column_name FROM information_schema.columns WHERE table_schema='public' AND column_name IN ('created_at','updated_at','opened_at','assigned_at','timestamp') LOOP EXECUTE format('ALTER TABLE %I ALTER COLUMN %I SET DEFAULT timezone(''UTC'',now())',c.table_name,c.column_name); END LOOP; END $$;
ALTER TABLE users ALTER COLUMN password_hash SET DEFAULT '';
ALTER TABLE alerts ALTER COLUMN priority SET DEFAULT 'medium';
ALTER TABLE event_types ALTER COLUMN default_priority SET DEFAULT 'medium';
ALTER TABLE event_types ALTER COLUMN generates_alert SET DEFAULT true;
ALTER TABLE assignments ALTER COLUMN assignment_type SET DEFAULT 'manual';
ALTER TABLE menu_options ALTER COLUMN "order" SET DEFAULT 0;
-- Menú semilla: su estructura, etiquetas y orden se administran desde las tablas.
INSERT INTO menu_options(name,icon,"order",state_id) SELECT v.name,'folder',v.ord,s.id FROM (VALUES ('MONITOREO',1),('SEGUIMIENTO',2),('ADMINISTRACIÓN',3)) v(name,ord) CROSS JOIN states s WHERE s.code='active' AND NOT EXISTS(SELECT 1 FROM menu_options m WHERE m.name=v.name AND m.parent_id IS NULL);
INSERT INTO menu_options(name,url,icon,parent_id,"order",state_id) SELECT v.name,v.url,v.icon,m.id,v.ord,s.id FROM (VALUES
('Panel de control','/dashboard','dashboard','MONITOREO',1),('Alertas','/alerts','alerts','MONITOREO',2),('Asignaciones','/assignments','assignments','MONITOREO',3),('Historial','/history','history','SEGUIMIENTO',1),('Reportes','/reports','reports','SEGUIMIENTO',2),('Usuarios','/admin/users','users','ADMINISTRACIÓN',1),('Perfiles','/admin/profiles','profiles','ADMINISTRACIÓN',2),('Opciones de menú','/admin/menu-options','menu','ADMINISTRACIÓN',3),('Datos maestros','/master-data','database','ADMINISTRACIÓN',4)) v(name,url,icon,parent,ord) JOIN menu_options m ON m.name=v.parent AND m.parent_id IS NULL CROSS JOIN states s WHERE s.code='active' AND NOT EXISTS(SELECT 1 FROM menu_options x WHERE x.url=v.url);
INSERT INTO profile_menu_option SELECT p.id,m.id FROM profiles p CROSS JOIN menu_options m WHERE p.role_code='admin' OR (p.role_code='supervisor' AND (m.url IS NULL OR m.url NOT LIKE '/admin/%') AND coalesce(m.url,'')<>'/master-data') OR (p.role_code IN ('operator','technician') AND (m.url IN ('/dashboard','/alerts','/assignments','/history') OR m.name IN ('MONITOREO','SEGUIMIENTO'))) ON CONFLICT DO NOTHING;
COMMIT;
