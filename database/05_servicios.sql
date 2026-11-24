BEGIN;

ALTER TABLE billing_invoices ADD COLUMN IF NOT EXISTS service_vehicle_id integer REFERENCES vehicles;
ALTER TABLE billing_invoices ADD COLUMN IF NOT EXISTS created_at timestamptz;
-- Las facturas anteriores conservan su fecha de emisión sin atribuirles una hora ficticia.
ALTER TABLE billing_invoices ALTER COLUMN created_at SET DEFAULT now();
ALTER TABLE billing_invoices DROP CONSTRAINT IF EXISTS billing_invoices_client_id_period_key;
CREATE UNIQUE INDEX IF NOT EXISTS billing_grouped_period ON billing_invoices(client_id, period)
    WHERE service_vehicle_id IS NULL;
UPDATE menu_options SET name='Servicio' WHERE url='/billing' AND name='Facturación';

CREATE OR REPLACE FUNCTION j2f_service(p_action text, p_data jsonb, p_user integer, p_profile integer)
RETURNS jsonb LANGUAGE plpgsql AS $$
DECLARE
    cid integer := (p_data->>'client_id')::integer;
    vid integer := (p_data->>'vehicle_id')::integer;
    per date := (p_data->>'period')::date;
    concepts jsonb := p_data->'concepts';
    summary jsonb;
    items jsonb;
    amount numeric;
    iid integer;
BEGIN
    PERFORM j2f_require(p_user,p_profile,'billing');
    IF p_action='history' THEN
        RETURN jsonb_build_object('items', (SELECT coalesce(jsonb_agg(to_jsonb(row) ORDER BY id DESC),'[]')
            FROM (SELECT id, number, issue_date, created_at, status, total, external_id,
                         recipient->>'razon_social' AS client_name
                  FROM billing_invoices WHERE id < coalesce((p_data->>'before')::bigint,2147483648)
                  ORDER BY id DESC LIMIT 30) row));
    END IF;
    IF p_action NOT IN ('preview','reserve') OR per IS NULL OR extract(day FROM per)<>1 THEN
        RAISE EXCEPTION 'Selecciona un servicio y un mes válido';
    END IF;
    -- El mismo bloqueo protege tanto los cobros individuales como la emisión agrupada anterior.
    PERFORM 1 FROM clients WHERE id=cid FOR UPDATE;
    IF NOT FOUND THEN RAISE NO_DATA_FOUND; END IF;
    IF vid IS NULL THEN
        SELECT id INTO iid FROM billing_invoices WHERE client_id=cid AND period=per AND service_vehicle_id IS NULL;
        IF FOUND THEN RETURN j2f_billing_invoice(iid); END IF;
    ELSIF NOT EXISTS (SELECT FROM vehicles WHERE id=vid AND client_id=cid) THEN
        RAISE EXCEPTION 'El vehículo no pertenece al cliente';
    END IF;
    summary := j2f_billing_preview(cid,per);
    IF vid IS NOT NULL THEN
        SELECT coalesce(jsonb_agg(line ORDER BY line->>'concept'),'[]'),
               coalesce(sum((line->>'gross')::numeric),0)
        INTO items, amount FROM jsonb_array_elements(summary->'lines') line
        WHERE (line->>'vehicle_id')::integer=vid AND (concepts IS NULL OR concepts ? (line->>'concept'));
        IF concepts IS NOT NULL AND jsonb_array_length(concepts)<>jsonb_array_length(items) THEN
            RAISE EXCEPTION 'Uno de los servicios ya no está pendiente. Vuelve a consultar';
        END IF;
        summary := summary || jsonb_build_object('lines',items,'total',amount,'signature',
            md5(jsonb_build_array(cid,vid,per,items,summary->'recipient')::text));
    END IF;
    IF p_action='preview' THEN RETURN summary; END IF;
    IF jsonb_array_length(summary->'missing')>0 OR jsonb_array_length(summary->'lines')=0 THEN
        RAISE EXCEPTION 'Faltan datos fiscales o no hay cargos pendientes';
    END IF;
    IF summary->>'signature' IS DISTINCT FROM p_data->>'signature' THEN
        RAISE EXCEPTION 'La vista previa cambió. Revísala de nuevo';
    END IF;
    INSERT INTO billing_invoices(client_id,service_vehicle_id,period,recipient,issuer,total,created_by)
    VALUES(cid,vid,per,summary->'recipient',p_data->'issuer',(summary->>'total')::numeric,p_user)
    RETURNING id INTO iid;
    INSERT INTO billing_lines SELECT iid,l.* FROM jsonb_to_recordset(summary->'lines') AS
        l(vehicle_id integer,plate text,concept text,label text,period date,gross numeric,igv numeric);
    RETURN j2f_billing_invoice(iid);
END $$;
COMMIT;
