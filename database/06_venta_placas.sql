BEGIN;
ALTER TABLE billing_invoices ADD COLUMN IF NOT EXISTS sale_start date;
-- Las facturas agrupadas antiguas siguen siendo únicas por cliente y mes.
DROP INDEX IF EXISTS billing_grouped_period;
CREATE UNIQUE INDEX billing_grouped_period ON billing_invoices(client_id,period)
    WHERE service_vehicle_id IS NULL AND sale_start IS NULL;

CREATE OR REPLACE FUNCTION j2f_service(p_action text, p_data jsonb, p_user integer, p_profile integer)
RETURNS jsonb LANGUAGE plpgsql AS $$
DECLARE
    cid integer := (p_data->>'client_id')::integer;
    vid integer := (p_data->>'vehicle_id')::integer;
    per date := (p_data->>'period')::date;
    ids integer[] := ARRAY(SELECT jsonb_array_elements_text(p_data->'vehicles')::integer);
    sale_start date := (p_data->>'start')::date;
    concepts jsonb := p_data->'concepts';
    summary jsonb;
    items jsonb;
    amount numeric;
    page_size CONSTANT integer := 30;
    unavailable text;
    iid integer;
BEGIN
    PERFORM j2f_require(p_user,p_profile,'billing');
    IF p_action='history' THEN
        WITH page AS (
            SELECT id, number, issue_date, created_at, status, total, external_id,
                   recipient->>'razon_social' AS client_name
            FROM billing_invoices
            WHERE (p_data->>'before' IS NULL OR id<(p_data->>'before')::bigint)
              AND (cid IS NULL OR client_id=cid)
              AND (p_data->>'from' IS NULL OR issue_date >= (p_data->>'from')::date)
              AND (p_data->>'to' IS NULL OR issue_date <= (p_data->>'to')::date)
            ORDER BY id DESC LIMIT page_size+1
        ), shown AS (SELECT * FROM page ORDER BY id DESC LIMIT page_size)
        SELECT jsonb_build_object('items',coalesce(jsonb_agg(to_jsonb(shown) ORDER BY id DESC),'[]'),
                                  'has_more', (SELECT count(*)>page_size FROM page))
        INTO summary FROM shown;
        RETURN summary;
    END IF;
    IF p_action NOT IN ('preview','reserve') OR per IS NULL OR extract(day FROM per)<>1 THEN
        RAISE EXCEPTION 'Selecciona un servicio y un mes válido';
    END IF;
    -- El mismo bloqueo protege tanto los cobros individuales como la emisión agrupada anterior.
    PERFORM 1 FROM clients WHERE id=cid FOR UPDATE;
    IF NOT FOUND THEN RAISE NO_DATA_FOUND; END IF;
    IF cardinality(ids)>0 THEN
        IF sale_start IS NULL OR date_trunc('month',sale_start)::date<>per OR EXISTS (
            SELECT FROM unnest(ids) id_requested
            WHERE NOT EXISTS (SELECT FROM vehicles v JOIN billing_plans b ON b.vehicle_id=v.id
                WHERE v.id=id_requested AND v.client_id=cid AND b.service_start<=sale_start)
        ) THEN RAISE EXCEPTION 'Revisa las placas y su fecha de inicio'; END IF;
    ELSIF vid IS NULL THEN
        SELECT id INTO iid FROM billing_invoices WHERE client_id=cid AND period=per AND service_vehicle_id IS NULL AND billing_invoices.sale_start IS NULL;
        IF FOUND THEN RETURN j2f_billing_invoice(iid); END IF;
    ELSIF NOT EXISTS (SELECT FROM vehicles WHERE id=vid AND client_id=cid) THEN
        RAISE EXCEPTION 'El vehículo no pertenece al cliente';
    END IF;
    summary := j2f_billing_preview(cid,per);
    IF vid IS NOT NULL OR cardinality(ids)>0 THEN
        SELECT coalesce(jsonb_agg(line ORDER BY (line->>'vehicle_id')::integer,line->>'concept'),'[]'),
               coalesce(sum((line->>'gross')::numeric),0)
        INTO items, amount FROM jsonb_array_elements(summary->'lines') line
        WHERE ((line->>'vehicle_id')::integer=vid OR (line->>'vehicle_id')::integer=ANY(ids)) AND (concepts IS NULL OR concepts ? (line->>'concept'));
        IF cardinality(ids)>0 THEN
            SELECT string_agg(v.plate, ', ' ORDER BY v.plate) INTO unavailable FROM vehicles v
            WHERE v.id=ANY(ids) AND NOT EXISTS (
                SELECT FROM jsonb_array_elements(items) l WHERE (l->>'vehicle_id')::integer=v.id);
            IF unavailable IS NOT NULL THEN
                RAISE EXCEPTION 'Sin cargos pendientes para esa fecha: %. Revisa la selección', unavailable;
            END IF;
        END IF;
        IF concepts IS NOT NULL AND jsonb_array_length(concepts)<>jsonb_array_length(items) THEN
            RAISE EXCEPTION 'Uno de los servicios ya no está pendiente. Vuelve a consultar';
        END IF;
        summary := summary || jsonb_build_object('lines',items,'total',amount,'signature',
            md5(jsonb_build_array(cid,vid,ids,sale_start,per,items,summary->'recipient')::text));
    END IF;
    IF p_action='preview' THEN RETURN summary; END IF;
    IF jsonb_array_length(summary->'missing')>0 OR jsonb_array_length(summary->'lines')=0 THEN
        RAISE EXCEPTION 'Faltan datos fiscales o no hay cargos pendientes';
    END IF;
    IF summary->>'signature' IS DISTINCT FROM p_data->>'signature' THEN
        RAISE EXCEPTION 'La vista previa cambió. Revísala de nuevo';
    END IF;
    INSERT INTO billing_invoices(client_id,service_vehicle_id,sale_start,period,recipient,issuer,total,created_by)
    VALUES(cid,vid,sale_start,per,summary->'recipient',p_data->'issuer',(summary->>'total')::numeric,p_user)
    RETURNING id INTO iid;
    INSERT INTO billing_lines SELECT iid,l.* FROM jsonb_to_recordset(summary->'lines') AS
        l(vehicle_id integer,plate text,concept text,label text,period date,gross numeric,igv numeric);
    RETURN j2f_billing_invoice(iid);
END $$;
COMMIT;
