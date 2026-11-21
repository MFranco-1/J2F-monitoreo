BEGIN;

CREATE TABLE IF NOT EXISTS billing_rates (
    concept text PRIMARY KEY,
    label text NOT NULL,
    gross numeric(12,2) NOT NULL CHECK (gross > 0),
    igv numeric(5,2) NOT NULL CHECK (igv >= 0)
);
INSERT INTO billing_rates VALUES
    ('equipment','Equipo e instalación',250,18), ('month','Monitoreo mensual',37,18),
    ('first_year','Primer año con equipo e instalación',630,18),
    ('renewal','Renovación anual',444,18)
ON CONFLICT DO NOTHING;

CREATE TABLE IF NOT EXISTS billing_plans (
    vehicle_id integer PRIMARY KEY REFERENCES vehicles,
    plan text NOT NULL CHECK (plan IN ('monthly','annual')),
    service_start date NOT NULL,
    first_period date NOT NULL CHECK (extract(day FROM first_period)=1),
    equipment_paid boolean NOT NULL,
    CHECK (first_period >= date_trunc('month',service_start)::date)
);
CREATE TABLE IF NOT EXISTS billing_invoices (
    id serial PRIMARY KEY,
    reference uuid NOT NULL UNIQUE DEFAULT gen_random_uuid(),
    client_id integer NOT NULL REFERENCES clients,
    period date NOT NULL,
    recipient jsonb NOT NULL,
    issuer jsonb NOT NULL,
    total numeric(14,2) NOT NULL CHECK (total>0),
    issue_date date NOT NULL DEFAULT (now() AT TIME ZONE 'America/Lima')::date,
    created_by integer NOT NULL REFERENCES users,
    status text NOT NULL DEFAULT 'reserved' CHECK (status IN
      ('reserved','creating','uncertain','created','sending','send_unknown','accepted','rejected','mismatch')),
    external_id bigint,
    number text,
    sunat_status text,
    message text,
    version integer NOT NULL DEFAULT 0,
    updated_at timestamptz NOT NULL DEFAULT now(),
    UNIQUE (client_id,period)
);
CREATE TABLE IF NOT EXISTS billing_lines (
    invoice_id integer NOT NULL REFERENCES billing_invoices,
    vehicle_id integer NOT NULL REFERENCES vehicles,
    plate text NOT NULL,
    concept text NOT NULL REFERENCES billing_rates,
    label text NOT NULL,
    period date NOT NULL,
    gross numeric(12,2) NOT NULL,
    igv numeric(5,2) NOT NULL,
    PRIMARY KEY(vehicle_id,concept,period)
);
CREATE UNIQUE INDEX IF NOT EXISTS billing_equipment_once ON billing_lines(vehicle_id) WHERE concept='equipment';

-- A vehicle without an explicit contract has no billable history.
CREATE OR REPLACE FUNCTION j2f_billing_preview(p_client integer,p_period date)
RETURNS jsonb LANGUAGE sql STABLE AS $$
 WITH due AS (
   SELECT v.id vehicle_id,v.plate,r.concept,r.label,p_period period,r.gross,r.igv
   FROM vehicles v JOIN states vs ON vs.id=v.state_id AND vs.is_active
   JOIN billing_plans p ON p.vehicle_id=v.id CROSS JOIN billing_rates r
   WHERE v.client_id=p_client AND p_period>=p.first_period AND (
     (p.plan='monthly' AND (r.concept='month' OR (r.concept='equipment' AND NOT p.equipment_paid
       AND NOT EXISTS (SELECT 1 FROM billing_lines l WHERE l.vehicle_id=v.id AND l.concept='equipment'))))
     OR (p.plan='annual' AND extract(month FROM p_period)=extract(month FROM p.service_start)
       AND r.concept=CASE WHEN extract(year FROM p_period)=extract(year FROM p.service_start)
                     THEN 'first_year' ELSE 'renewal' END))
     AND NOT EXISTS (SELECT 1 FROM billing_lines l WHERE l.vehicle_id=v.id AND l.concept=r.concept AND l.period=p_period)
 ), summary AS (
   SELECT coalesce(jsonb_agg(to_jsonb(due) ORDER BY vehicle_id,concept),'[]') lines,coalesce(sum(gross),0) total FROM due
 )
 SELECT jsonb_build_object('lines',lines,'total',total,'recipient',recipient,
    'signature',md5(jsonb_build_array(lines,recipient,p_period)::text),'missing',
    to_jsonb(array_remove(ARRAY[
      CASE WHEN c.document_type <> 'RUC' OR c.document_number !~ '^[0-9]{11}$' THEN 'RUC del cliente (11 dígitos)' END,
      CASE WHEN trim(c.business_name)='' THEN 'Razón social del cliente' END,
      CASE WHEN length(c.address)>255 THEN 'Dirección de hasta 255 caracteres' END,
      CASE WHEN length(c.business_name)>255 THEN 'Razón social de hasta 255 caracteres' END,
      CASE WHEN NOT s.is_active THEN 'Cliente activo' END],NULL)))
 FROM clients c JOIN states s ON s.id=c.state_id CROSS JOIN summary
 CROSS JOIN LATERAL (SELECT jsonb_build_object('tipo_documento','6','numero_documento',c.document_number,
    'razon_social',c.business_name,'direccion',c.address) recipient) customer WHERE c.id=p_client
$$;

CREATE OR REPLACE FUNCTION j2f_billing_invoice(p_id integer) RETURNS jsonb LANGUAGE sql STABLE AS $$
 SELECT to_jsonb(i)||jsonb_build_object('lines',(SELECT jsonb_agg(to_jsonb(l) ORDER BY vehicle_id,concept)
   FROM billing_lines l WHERE invoice_id=i.id)) FROM billing_invoices i WHERE i.id=p_id
$$;

CREATE OR REPLACE FUNCTION j2f_billing(p_action text,p_data jsonb,p_user integer,p_profile integer)
RETURNS jsonb LANGUAGE plpgsql AS $$
DECLARE
    cid integer := (p_data->>'client_id')::integer;
    vid integer := (p_data->>'vehicle_id')::integer;
    per date := (p_data->>'period')::date;
    iid integer := (p_data->>'id')::integer;
    inv billing_invoices;
    preview jsonb;
    next_status text := p_data->>'status';
BEGIN
    PERFORM j2f_require(p_user,p_profile,'billing');
    IF p_action='catalog' THEN
        RETURN jsonb_build_object('clients',(SELECT coalesce(jsonb_agg(jsonb_build_object('id',id,'name',business_name) ORDER BY business_name,id),'[]') FROM clients),
          'vehicles',(SELECT coalesce(jsonb_agg(jsonb_build_object('id',v.id,'plate',v.plate,'client_id',v.client_id,'contract',to_jsonb(p)) ORDER BY v.plate),'[]')
          FROM vehicles v LEFT JOIN billing_plans p ON p.vehicle_id=v.id));
    END IF;
    IF p_action='plan' THEN
        SELECT client_id INTO STRICT cid FROM vehicles WHERE id=vid FOR UPDATE;
        PERFORM 1 FROM clients WHERE id=cid FOR UPDATE;
        IF EXISTS(SELECT 1 FROM billing_lines WHERE vehicle_id=vid) THEN RAISE EXCEPTION 'El plan ya tiene cargos registrados'; END IF;
        INSERT INTO billing_plans VALUES (vid,p_data->>'plan',(p_data->>'service_start')::date,
          (p_data->>'first_period')::date,(p_data->>'equipment_paid')::boolean)
        ON CONFLICT(vehicle_id) DO UPDATE SET plan=excluded.plan,service_start=excluded.service_start,
          first_period=excluded.first_period,equipment_paid=excluded.equipment_paid;
        RETURN jsonb_build_object('vehicle_id',vid);
    END IF;
    IF p_action IN ('preview','reserve') THEN
        IF per IS NULL OR extract(day FROM per)<>1 THEN RAISE EXCEPTION 'Elige un período mensual válido'; END IF;
        PERFORM 1 FROM clients WHERE id=cid FOR UPDATE;
        IF NOT FOUND THEN RAISE NO_DATA_FOUND; END IF;
        SELECT * INTO inv FROM billing_invoices WHERE client_id=cid AND period=per;
        IF FOUND THEN RETURN j2f_billing_invoice(inv.id); END IF;
        preview:=j2f_billing_preview(cid,per);
        IF p_action='preview' THEN RETURN preview; END IF;
        IF jsonb_array_length(preview->'missing')>0 OR jsonb_array_length(preview->'lines')=0 THEN
            RAISE EXCEPTION 'Faltan datos fiscales o no hay cargos pendientes para este período';
        END IF;
        IF preview->>'signature' IS DISTINCT FROM p_data->>'signature' THEN RAISE EXCEPTION 'La vista previa cambió. Revísala de nuevo'; END IF;
        INSERT INTO billing_invoices(client_id,period,recipient,issuer,total,created_by)
        VALUES(cid,per,preview->'recipient',p_data->'issuer',(preview->>'total')::numeric,p_user) RETURNING id INTO iid;
        INSERT INTO billing_lines SELECT iid,l.* FROM jsonb_to_recordset(preview->'lines') AS
          l(vehicle_id integer,plate text,concept text,label text,period date,gross numeric,igv numeric);
        RETURN j2f_billing_invoice(iid);
    END IF;
    SELECT * INTO STRICT inv FROM billing_invoices WHERE id=iid FOR UPDATE;
    IF p_action='get' THEN RETURN j2f_billing_invoice(iid); END IF;
    IF inv.version IS DISTINCT FROM (p_data->>'version')::integer THEN RAISE EXCEPTION 'La factura cambió. Consulta su estado'; END IF;
    IF p_action='claim_create' AND inv.status='reserved' THEN next_status:='creating';
    ELSIF p_action='claim_send' AND inv.status IN ('created','rejected') AND inv.external_id IS NOT NULL THEN next_status:='sending';
    ELSIF p_action='result' AND (
       (inv.status IN ('creating','uncertain') AND next_status IN ('uncertain','created','mismatch','accepted','rejected'))
       OR (inv.status IN ('creating','uncertain') AND next_status='reserved')
       OR (inv.status IN ('sending','send_unknown','created','rejected') AND next_status IN ('created','accepted','rejected','send_unknown','mismatch'))
    ) THEN NULL;
    ELSE RAISE EXCEPTION 'Hay una operación pendiente o la factura ya finalizó'; END IF;
    UPDATE billing_invoices SET status=next_status,version=version+1,updated_at=clock_timestamp(),
      external_id=coalesce(external_id,(p_data->>'external_id')::bigint),number=coalesce(number,p_data->>'number'),
      sunat_status=coalesce(p_data->>'sunat_status',sunat_status),message=p_data->>'message' WHERE id=iid;
    RETURN j2f_billing_invoice(iid);
END $$;

INSERT INTO permissions VALUES ('billing','Gestionar planes y facturación de prueba') ON CONFLICT DO NOTHING;
INSERT INTO profile_permissions SELECT id,'billing' FROM profiles WHERE role_code='admin' ON CONFLICT DO NOTHING;
INSERT INTO menu_options(name,url,icon,parent_id,"order",state_id)
SELECT 'Facturación','/billing','reports',parent_id,20,j2f_state('default_state_code')
FROM menu_options WHERE url='/reports' AND NOT EXISTS(SELECT 1 FROM menu_options WHERE url='/billing') ORDER BY id LIMIT 1;
INSERT INTO profile_menu_option SELECT p.id,m.id FROM profiles p CROSS JOIN menu_options m
WHERE p.role_code='admin' AND m.url='/billing' ON CONFLICT DO NOTHING;
COMMIT;
