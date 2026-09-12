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
