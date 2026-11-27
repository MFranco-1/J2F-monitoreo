BEGIN;

-- El maestro y el formulario comparten el catálogo de formatos.
UPDATE document_types SET pattern = '^[A-Za-z0-9]{9,12}$'
WHERE code = 'CE' AND pattern IS DISTINCT FROM '^[A-Za-z0-9]{9,12}$';

-- También localizar documentos alfanuméricos heredados que se guardaron en minúsculas.
CREATE INDEX IF NOT EXISTS ix_clients_import_document ON clients (upper(btrim(document_number)));

CREATE TABLE IF NOT EXISTS coolbox_import_batches (
    id serial PRIMARY KEY,
    requested_by integer REFERENCES users(id) ON DELETE SET NULL,
    started_at timestamptz NOT NULL DEFAULT now(),
    finished_at timestamptz,
    status text NOT NULL DEFAULT 'receiving' CHECK (status IN ('receiving', 'completed', 'failed')),
    next_page integer NOT NULL DEFAULT 1,
    error text
);

CREATE TABLE IF NOT EXISTS coolbox_client_staging (
    batch_id integer NOT NULL REFERENCES coolbox_import_batches(id),
    page integer NOT NULL,
    position integer NOT NULL,
    fields jsonb NOT NULL,
    phone_e164 text,
    outcome text NOT NULL DEFAULT 'pending'
        CHECK (outcome IN ('pending', 'created', 'updated', 'unchanged', 'conflict', 'rejected')),
    reason text,
    PRIMARY KEY (batch_id, page, position)
);

CREATE OR REPLACE FUNCTION j2f_coolbox_batch(p_user integer, p_profile integer, p_batch integer)
RETURNS jsonb LANGUAGE plpgsql AS $$
DECLARE
    batch coolbox_import_batches;
BEGIN
    PERFORM j2f_require(p_user, p_profile, (SELECT write_permission FROM app_resources WHERE code = 'clients'));
    IF p_batch IS NULL THEN
        INSERT INTO coolbox_import_batches(requested_by) VALUES (p_user) RETURNING * INTO batch;
    ELSE
        SELECT * INTO STRICT batch FROM coolbox_import_batches WHERE id = p_batch AND requested_by = p_user;
        IF batch.status <> 'receiving' THEN RAISE EXCEPTION 'El lote ya finalizó'; END IF;
    END IF;
    RETURN jsonb_build_object('batch_id', batch.id, 'next_page', batch.next_page);
END $$;

CREATE OR REPLACE FUNCTION j2f_coolbox_merge(p_row coolbox_client_staging, p_user integer, p_profile integer)
RETURNS text LANGUAGE plpgsql AS $$
DECLARE
    doc_type text := upper(btrim(p_row.fields->>'tipo_documento'));
    doc text := upper(btrim(p_row.fields->>'numero_documento'));
    name text := btrim(p_row.fields->>'nombre_completo');
    email text := nullif(btrim(p_row.fields->>'email'), '');
    address text := nullif(btrim(p_row.fields->>'direccion'), '');
    data jsonb;
    existing clients;
    ruc_sum integer;
BEGIN
    IF doc_type IS NULL OR doc_type NOT IN ('DNI', 'RUC', 'CE', 'PASAPORTE') THEN
        RAISE EXCEPTION 'Tipo de documento no admitido';
    END IF;
    IF NOT EXISTS (SELECT 1 FROM document_types WHERE code = doc_type AND doc ~ pattern) THEN
        RAISE EXCEPTION 'Número de documento inválido para %', doc_type;
    END IF;
    IF doc_type = 'RUC' THEN
        IF left(doc, 2) NOT IN ('10', '15', '17', '20') THEN RAISE EXCEPTION 'Prefijo de RUC no admitido por COOLBOX'; END IF;
        SELECT sum(weight * substr(doc, pos::integer, 1)::integer) INTO ruc_sum
        FROM unnest(ARRAY[5,4,3,2,7,6,5,4,3,2]) WITH ORDINALITY AS weights(weight, pos);
        IF (11 - ruc_sum % 11) % 10 <> right(doc, 1)::integer THEN RAISE EXCEPTION 'Dígito verificador del RUC inválido'; END IF;
    END IF;
    IF name IS NULL OR length(name) NOT BETWEEN 3 AND 180
       OR name COLLATE pg_catalog."und-x-icu" !~ '[[:alpha:]].*[[:alpha:]]' THEN
        RAISE EXCEPTION 'Nombre o razón social inválido (entre 3 y 180 caracteres)';
    END IF;
    IF email IS NOT NULL AND (length(email) > 150 OR email !~ '^[^[:space:]@]+@[^[:space:]@]+[.][^[:space:]@]+$') THEN
        RAISE EXCEPTION 'Correo electrónico inválido';
    END IF;
    IF address IS NOT NULL AND (length(address) NOT BETWEEN 5 AND 255
       OR address COLLATE pg_catalog."und-x-icu" ~ '[^[:alpha:]0-9 .,/#-]') THEN
        RAISE EXCEPTION 'Dirección inválida (entre 5 y 255 caracteres; letras, números, espacios y . , / # -)';
    END IF;
    IF nullif(btrim(p_row.fields->>'telefono'), '') IS NOT NULL AND p_row.phone_e164 IS NULL THEN
        RAISE EXCEPTION 'Teléfono peruano inválido';
    END IF;

    -- El índice local reserva el número incluso cuando otro tipo tiene el mismo valor.
    BEGIN
        SELECT * INTO STRICT existing FROM clients WHERE upper(btrim(document_number)) = doc;
    EXCEPTION
        WHEN no_data_found THEN NULL;
        WHEN too_many_rows THEN RETURN 'ambiguous';
    END;
    IF existing.id IS NOT NULL AND existing.document_type <> doc_type THEN RETURN 'conflict'; END IF;
    data := jsonb_strip_nulls(jsonb_build_object(
        'business_name', name, 'phone', p_row.phone_e164, 'email', email, 'address', address
    ));
    IF existing.id IS NULL THEN
        data := data || jsonb_build_object('document_type', doc_type, 'document_number', doc);
    END IF;
    IF existing.id IS NOT NULL AND to_jsonb(existing) @> data THEN RETURN 'unchanged'; END IF;
    PERFORM j2f_save('clients', existing.id, data, p_user, p_profile);
    RETURN CASE WHEN existing.id IS NULL THEN 'created' ELSE 'updated' END;
END $$;

CREATE OR REPLACE FUNCTION j2f_coolbox_page(p_user integer, p_profile integer, p_batch integer, p_page integer, p_data jsonb)
RETURNS jsonb LANGUAGE plpgsql AS $$
DECLARE
    batch coolbox_import_batches;
    staged coolbox_client_staging;
    result text;
    detail text;
BEGIN
    PERFORM j2f_require(p_user, p_profile, (SELECT write_permission FROM app_resources WHERE code = 'clients'));
    SELECT * INTO STRICT batch FROM coolbox_import_batches WHERE id = p_batch AND requested_by = p_user FOR UPDATE;
    IF batch.status <> 'receiving' OR batch.next_page <> p_page THEN RAISE EXCEPTION 'Esta página ya fue procesada'; END IF;
    IF p_data ? 'error' THEN
        UPDATE coolbox_import_batches SET status = 'failed', finished_at = now(), error = p_data->>'error' WHERE id = p_batch;
        RETURN jsonb_build_object('batch_id', p_batch, 'error', p_data->>'error');
    END IF;
    INSERT INTO coolbox_client_staging(batch_id, page, position, fields, phone_e164, reason)
    SELECT p_batch, p_page, pos, item->'fields', item->>'phone', item->>'error'
    FROM jsonb_array_elements(p_data->'rows') WITH ORDINALITY AS rows(item, pos);
    IF NOT (p_data->>'last')::boolean THEN
        UPDATE coolbox_import_batches SET next_page = p_page + 1 WHERE id = p_batch;
        RETURN jsonb_build_object('batch_id', p_batch, 'next_page', p_page + 1);
    END IF;

    -- La consulta HTTP ya terminó. Desde aquí el lote se incorpora de forma atómica;
    -- otra importación o un alta manual debe ver el resultado antes de decidir si inserta.
    LOCK TABLE clients IN SHARE ROW EXCLUSIVE MODE;
    FOR staged IN SELECT * FROM coolbox_client_staging WHERE batch_id = p_batch ORDER BY page, position LOOP
        detail := staged.reason;
        result := 'rejected';
        IF detail IS NULL THEN
            BEGIN
                result := j2f_coolbox_merge(staged, p_user, p_profile);
                IF result = 'conflict' THEN detail := 'El número ya existe con otro tipo de documento'; END IF;
                IF result = 'ambiguous' THEN
                    result := 'conflict';
                    detail := 'Más de una ficha local coincide con el número de documento';
                END IF;
            EXCEPTION WHEN raise_exception THEN
                detail := SQLERRM;
            END;
        END IF;
        UPDATE coolbox_client_staging SET outcome = result, reason = detail
        WHERE batch_id = p_batch AND page = staged.page AND position = staged.position;
    END LOOP;
    UPDATE coolbox_import_batches SET status = 'completed', finished_at = now() WHERE id = p_batch;
    RETURN (SELECT jsonb_build_object(
        'batch_id', p_batch, 'total', count(*),
        'created', count(*) FILTER (WHERE outcome = 'created'),
        'updated', count(*) FILTER (WHERE outcome = 'updated'),
        'unchanged', count(*) FILTER (WHERE outcome = 'unchanged'),
        'rejected', count(*) FILTER (WHERE outcome IN ('conflict','rejected')),
        'rejections', coalesce(jsonb_agg(jsonb_build_object(
            'page', page, 'position', position, 'document_type', fields->>'tipo_documento',
            'document_number', fields->>'numero_documento', 'reason', reason
        ) ORDER BY page, position) FILTER (WHERE reason IS NOT NULL), '[]'::jsonb)
    ) FROM coolbox_client_staging WHERE batch_id = p_batch);
END $$;
COMMIT;
