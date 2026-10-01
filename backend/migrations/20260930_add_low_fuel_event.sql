BEGIN;

INSERT INTO event_types (
    code, name, description, default_priority, generates_alert,
    expected_action, state_id, created_at, updated_at
)
SELECT
    'LOW_FUEL',
    'Combustible bajo',
    'Nivel simulado de combustible igual o menor al 10 %',
    'high',
    TRUE,
    'Coordinar una estación y confirmar el abastecimiento.',
    state.id,
    CURRENT_TIMESTAMP,
    CURRENT_TIMESTAMP
FROM states AS state
WHERE LOWER(BTRIM(state.name)) = 'activo'
  AND state.type = 'user'
  AND NOT EXISTS (SELECT 1 FROM event_types WHERE code = 'LOW_FUEL')
ORDER BY state.id
LIMIT 1;

COMMIT;
