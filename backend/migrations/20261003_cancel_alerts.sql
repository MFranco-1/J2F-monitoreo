-- Solo añade un estado terminal. No modifica alertas ni elimina datos.
BEGIN;
INSERT INTO states (name, type, description)
SELECT 'Anulado', 'alert', 'Caso anulado con motivo; no es una resolución'
WHERE NOT EXISTS (SELECT 1 FROM states WHERE name = 'Anulado');
COMMIT;
