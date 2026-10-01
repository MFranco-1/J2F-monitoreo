-- Conserva registros e historial; solo corrige los datos iniciales identificables.
BEGIN;

UPDATE clients SET
  document_type = 'Código interno',
  document_number = CASE document_number
    WHEN 'J2F-DEMO-001' THEN 'J2F-001'
    WHEN 'J2F-DEMO-002' THEN 'J2F-002'
    WHEN 'J2F-DEMO-003' THEN 'J2F-003'
  END,
  business_name = REPLACE(business_name, ' Demo', ''),
  email = NULL,
  updated_at = CURRENT_TIMESTAMP
WHERE document_number IN ('J2F-DEMO-001', 'J2F-DEMO-002', 'J2F-DEMO-003')
  AND NOT EXISTS (
    SELECT 1 FROM clients other_client
    WHERE other_client.document_number = REPLACE(clients.document_number, '-DEMO-', '-')
  );

UPDATE alerts SET
  description = 'Registro inicial de monitoreo.',
  location = 'Ubicación no informada',
  source = 'Carga inicial J2F',
  updated_at = CURRENT_TIMESTAMP
WHERE source = 'Datos de prueba J2F';

WITH seed(document_number, plate, brand, model, color, vehicle_type) AS (VALUES
  ('J2F-001', 'J2F-A04', 'Toyota', 'Hilux', 'Azul', 'Camioneta'),
  ('J2F-002', 'J2F-P04', 'Volvo', 'FH', 'Blanco', 'Tráiler'),
  ('J2F-003', 'J2F-S04', 'Hyundai', 'H100', 'Gris', 'Furgón')
), active_state AS (
  SELECT id FROM states WHERE LOWER(BTRIM(name)) = 'activo' AND type = 'user' ORDER BY id LIMIT 1
)
INSERT INTO vehicles(client_id, plate, brand, model, color, vehicle_type, state_id, created_at, updated_at)
SELECT c.id, s.plate, s.brand, s.model, s.color, s.vehicle_type, a.id, CURRENT_TIMESTAMP, CURRENT_TIMESTAMP
FROM seed s JOIN clients c ON c.document_number = s.document_number CROSS JOIN active_state a
WHERE NOT EXISTS (SELECT 1 FROM vehicles v WHERE v.plate = s.plate);

COMMIT;
