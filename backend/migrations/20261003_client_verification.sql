-- Migración incremental: conserva clientes, vehículos, GPS e historial existentes.
BEGIN;
ALTER TABLE clients ADD COLUMN IF NOT EXISTS verification_json TEXT;
COMMIT;
