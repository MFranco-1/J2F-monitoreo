BEGIN;

-- El convenio identifica a los clientes por su documento. La ficha administrativa
-- y los registros que solo tienen un código interno permanecen en J2F.
CREATE OR REPLACE FUNCTION j2f_export_clients()
RETURNS jsonb LANGUAGE sql STABLE AS $$
    SELECT jsonb_build_object('clients', coalesce(jsonb_agg(jsonb_build_object(
        'document_type', c.document_type,
        'document_number', c.document_number,
        'business_name', c.business_name,
        'phone', nullif(btrim(c.phone), ''),
        'email', nullif(btrim(c.email), ''),
        'address', nullif(btrim(c.address), '')
    ) ORDER BY c.id), '[]'::jsonb))
    FROM clients AS c
    WHERE c.document_type IN ('DNI', 'RUC', 'CE', 'PASAPORTE')
$$;

COMMIT;
