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
