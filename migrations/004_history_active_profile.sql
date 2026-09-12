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
