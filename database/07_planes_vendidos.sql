BEGIN;
CREATE OR REPLACE FUNCTION j2f_billing_catalog(p_user integer, p_profile integer)
RETURNS jsonb LANGUAGE plpgsql AS $$
DECLARE
    catalog jsonb;
    plans jsonb;
BEGIN
    catalog := j2f_billing('catalog','{}',p_user,p_profile);
    WITH billed AS (
        SELECT l.vehicle_id, i.id, i.number, l.period, l.gross,
               CASE WHEN l.concept='month' THEN 'Mensual' ELSE 'Anual' END AS plan,
               CASE WHEN l.concept='month' THEN interval '1 month' ELSE interval '1 year' END AS duration,
               extract(day FROM coalesce(i.sale_start,p.service_start,l.period))::integer - 1 AS day_offset
        FROM billing_lines l JOIN billing_invoices i ON i.id=l.invoice_id
        LEFT JOIN billing_plans p ON p.vehicle_id=l.vehicle_id
        WHERE l.concept IN ('month','first_year','renewal') AND i.external_id IS NOT NULL
          AND i.status IN ('created','sending','send_unknown','accepted')
    ), cycles AS (
        SELECT *, (period+duration)::date AS next_period FROM billed
    ), dates AS (
        -- Conserva el día de aniversario incluso cuando un mes más corto obliga a ajustarlo.
        SELECT *, least(period+day_offset,(period+interval '1 month')::date-1) AS starts,
               least(next_period+day_offset,(next_period+interval '1 month')::date-1)-1 AS ends,
               (current_timestamp AT TIME ZONE 'America/Lima')::date AS today FROM cycles
    ), ranked AS (
        SELECT *, CASE WHEN today BETWEEN starts AND ends THEN 'Vigente'
                       WHEN starts>today THEN 'Próximo' ELSE 'Vencido' END AS status,
               row_number() OVER (PARTITION BY vehicle_id ORDER BY
                   CASE WHEN today BETWEEN starts AND ends THEN 0 WHEN starts>today THEN 1 ELSE 2 END,
                   CASE WHEN starts>today THEN starts END, starts DESC, id DESC) AS position
        FROM dates
    ), summary AS (
        SELECT vehicle_id, jsonb_agg(DISTINCT plan ORDER BY plan) AS labels,
               jsonb_agg(jsonb_build_object('id',id,'number',number,'period',period,'start',starts,
                   'end',ends,'plan',plan,'amount',gross) ORDER BY period DESC, id DESC) AS periods,
               (jsonb_agg(jsonb_build_object('plan',plan,'start',starts,'end',ends,'status',status))
                FILTER (WHERE position=1))->0 AS coverage
        FROM ranked GROUP BY vehicle_id
    )
    SELECT jsonb_build_object('sold_plans',coalesce(jsonb_object_agg(vehicle_id,labels),'{}'),
                              'billed_periods',coalesce(jsonb_object_agg(vehicle_id,periods),'{}'),
                              'coverage',coalesce(jsonb_object_agg(vehicle_id,coverage),'{}'))
    INTO plans FROM summary;
    RETURN catalog || plans;
END $$;
COMMIT;
