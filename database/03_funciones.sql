-- Toda consulta y escritura operacional reside en funciones PL/pgSQL.
-- Las funciones no reciben SQL del aplicativo. Los valores viajan en parámetros JSON.
BEGIN;
CREATE OR REPLACE FUNCTION j2f_param(p_key text) RETURNS jsonb LANGUAGE plpgsql STABLE AS $$
DECLARE v jsonb; BEGIN SELECT value INTO v FROM app_parameters WHERE key=p_key; IF v IS NULL THEN RAISE EXCEPTION 'Falta parámetro: %',p_key; END IF; RETURN v; END $$;
CREATE OR REPLACE FUNCTION j2f_state(p_key text) RETURNS integer LANGUAGE sql STABLE AS $$ SELECT id FROM states WHERE code=j2f_param(p_key)#>>'{}' $$;
CREATE OR REPLACE FUNCTION j2f_has(p_user integer,p_profile integer,p_permission text) RETURNS boolean LANGUAGE sql STABLE AS $$
 SELECT EXISTS(SELECT 1 FROM users u JOIN states us ON us.id=u.state_id JOIN user_profile up ON up.user_id=u.id JOIN profiles p ON p.id=up.profile_id JOIN states ps ON ps.id=p.state_id JOIN profile_permissions pp ON pp.profile_id=p.id WHERE u.id=p_user AND p.id=p_profile AND us.is_active AND ps.is_active AND pp.permission_code=p_permission)
$$;
CREATE OR REPLACE FUNCTION j2f_require(p_user integer,p_profile integer,p_permission text) RETURNS void LANGUAGE plpgsql AS $$ BEGIN IF NOT j2f_has(p_user,p_profile,p_permission) THEN RAISE EXCEPTION USING ERRCODE='42501',MESSAGE='El perfil activo no tiene permiso para esta operación'; END IF; END $$;
CREATE OR REPLACE FUNCTION j2f_can_view(p_alert integer,p_user integer,p_profile integer) RETURNS boolean LANGUAGE sql STABLE AS $$ SELECT j2f_has(p_user,p_profile,'view_all') OR (j2f_has(p_user,p_profile,'attend') AND EXISTS(SELECT 1 FROM assignments WHERE alert_id=p_alert AND user_id=p_user)) $$;
CREATE OR REPLACE FUNCTION j2f_can_attend(p_alert integer,p_user integer,p_profile integer) RETURNS boolean LANGUAGE sql STABLE AS $$ SELECT j2f_has(p_user,p_profile,'admin') OR (j2f_has(p_user,p_profile,'attend') AND EXISTS(SELECT 1 FROM assignments WHERE alert_id=p_alert AND user_id=p_user AND completed_at IS NULL)) $$;
CREATE OR REPLACE FUNCTION j2f_profile(p_id integer) RETURNS jsonb LANGUAGE sql STABLE AS $$
 SELECT to_jsonb(p)||jsonb_build_object('state',to_jsonb(s),'permissions',coalesce((SELECT jsonb_agg(permission_code ORDER BY permission_code) FROM profile_permissions WHERE profile_id=p.id),'[]'::jsonb),'menu_options',coalesce((SELECT jsonb_agg(to_jsonb(m) ORDER BY m."order",m.id) FROM profile_menu_option pm JOIN menu_options m ON m.id=pm.menu_option_id WHERE pm.profile_id=p.id),'[]'::jsonb)) FROM profiles p JOIN states s ON s.id=p.state_id WHERE p.id=p_id
$$;
CREATE OR REPLACE FUNCTION j2f_user(p_id integer,p_profile integer DEFAULT NULL) RETURNS jsonb LANGUAGE sql STABLE AS $$
 SELECT (to_jsonb(u)-'password_hash'-'session_version')||jsonb_build_object('state',to_jsonb(s),'profile',j2f_profile(coalesce(p_profile,u.profile_id)),'profiles',coalesce((SELECT jsonb_agg(j2f_profile(p.id) ORDER BY p.name) FROM user_profile up JOIN profiles p ON p.id=up.profile_id JOIN states ps ON ps.id=p.state_id WHERE up.user_id=u.id AND ps.is_active),'[]'::jsonb)) FROM users u JOIN states s ON s.id=u.state_id WHERE u.id=p_id
$$;
CREATE OR REPLACE FUNCTION j2f_json_or_null(p_text text) RETURNS jsonb LANGUAGE plpgsql IMMUTABLE AS $$
BEGIN RETURN p_text::jsonb; EXCEPTION WHEN invalid_text_representation THEN RETURN NULL; END $$;
CREATE OR REPLACE FUNCTION j2f_history_entry(h history) RETURNS jsonb LANGUAGE sql STABLE AS $$
 SELECT to_jsonb(h)||jsonb_build_object('user',coalesce(m.metadata->'author',jsonb_build_object('id',u.id,'full_name',u.full_name)),'profile',coalesce(m.metadata->'profile',jsonb_build_object('id',p.id,'name',p.name)),'metadata',m.metadata,'detail',coalesce(m.metadata->>'text',m.metadata->>'observacion',h.detail))
 FROM (SELECT j2f_json_or_null(h.detail) AS metadata) m
 LEFT JOIN users u ON u.id=h.user_id
 LEFT JOIN profiles p ON p.id=h.profile_id
$$;
CREATE OR REPLACE FUNCTION j2f_history(p_alert integer) RETURNS jsonb LANGUAGE sql STABLE AS $$
 SELECT coalesce(jsonb_agg(j2f_history_entry(h) ORDER BY h.timestamp,h.id),'[]'::jsonb)
 FROM history h WHERE h.alert_id=p_alert
$$;
CREATE OR REPLACE FUNCTION j2f_log(p_alert integer,p_user integer,p_profile integer,p_action text,p_detail text,p_old text DEFAULT NULL,p_new text DEFAULT NULL) RETURNS integer LANGUAGE plpgsql AS $$
DECLARE v_id integer; BEGIN
 IF p_action='note_added' THEN
 p_detail:=(coalesce(j2f_json_or_null(p_detail),'{}'::jsonb)||jsonb_build_object('author',jsonb_build_object('id',p_user,'full_name',(SELECT full_name FROM users WHERE id=p_user)),'profile',jsonb_build_object('id',p_profile,'name',(SELECT name FROM profiles WHERE id=p_profile)),'category',CASE WHEN j2f_has(p_user,p_profile,'attend') AND NOT j2f_has(p_user,p_profile,'admin') THEN 'technical' ELSE 'coordination' END))::text;
 END IF;
 INSERT INTO history(alert_id,user_id,profile_id,action,detail,previous_state,new_state) VALUES(p_alert,p_user,p_profile,p_action,p_detail,p_old,p_new) RETURNING id INTO v_id; RETURN v_id; END $$;
-- Serialización central. Identificadores SQL proceden exclusivamente de app_resources.
CREATE OR REPLACE FUNCTION j2f_record(p_resource text,p_id integer,p_depth integer DEFAULT 0) RETURNS jsonb LANGUAGE plpgsql STABLE AS $$
DECLARE t text; v jsonb; x jsonb; BEGIN
 SELECT table_name INTO t FROM app_resources WHERE code=p_resource; IF t IS NULL THEN RETURN NULL; END IF;
 EXECUTE format('SELECT to_jsonb(r) FROM %I r WHERE id=$1',t) INTO v USING p_id;
 IF v IS NULL THEN RETURN NULL; END IF;
 IF p_resource='users' THEN RETURN j2f_user(p_id); END IF;
 IF p_resource='profiles' THEN RETURN j2f_profile(p_id); END IF;
 IF v ? 'state_id' THEN SELECT to_jsonb(s) INTO x FROM states s WHERE id=(v->>'state_id')::integer; v:=v||jsonb_build_object('state',x); END IF;
 IF p_resource='clients' THEN v:=v||jsonb_build_object('verification',coalesce((v->>'verification_json')::jsonb,jsonb_build_object('status','pending','audit','[]'::jsonb))); END IF;
 IF p_resource='vehicles' THEN
 v:=v||jsonb_build_object('client',j2f_record('clients',(v->>'client_id')::integer,1),'gps_devices',coalesce((SELECT jsonb_agg(j2f_record('gps-devices',id,1) ORDER BY id) FROM gps_devices WHERE vehicle_id=p_id),'[]'::jsonb));
 END IF;
 IF p_resource='gps-devices' AND p_depth=0 THEN v:=v||jsonb_build_object('vehicle',j2f_record('vehicles',(v->>'vehicle_id')::integer,1)); END IF;
 IF p_resource='alerts' THEN
 SELECT j2f_user(user_id)-'profiles'-'profile' INTO x FROM assignments WHERE alert_id=p_id AND completed_at IS NULL ORDER BY assigned_at DESC,id DESC LIMIT 1;
 v:=v||jsonb_build_object('vehicle',j2f_record('vehicles',(v->>'vehicle_id')::integer,1),'client',(SELECT j2f_record('clients',client_id,1) FROM vehicles WHERE id=(v->>'vehicle_id')::integer),'gps_device',j2f_record('gps-devices',(v->>'gps_device_id')::integer,1),'event_type',j2f_record('event-types',(v->>'event_type_id')::integer,1),'current_assignee',x,'history',j2f_history(p_id),'response_time_minutes',CASE WHEN v->>'resolved_at' IS NOT NULL THEN round(extract(epoch FROM ((v->>'resolved_at')::timestamp-(v->>'opened_at')::timestamp))/60,2) ELSE NULL END);
 END IF;
 IF p_resource='assignments' THEN
 v:=v||jsonb_build_object('user',j2f_user((v->>'user_id')::integer)-'profiles'-'profile','alert_state',(SELECT s.name FROM alerts a JOIN states s ON s.id=a.state_id WHERE a.id=(v->>'alert_id')::integer),'event_type_code',(SELECT e.code FROM alerts a JOIN event_types e ON e.id=a.event_type_id WHERE a.id=(v->>'alert_id')::integer),'status',CASE WHEN v->>'completed_at' IS NULL THEN 'En Curso' WHEN EXISTS(SELECT 1 FROM assignments n WHERE n.alert_id=(v->>'alert_id')::integer AND n.id>p_id) THEN 'Reasignada' WHEN EXISTS(SELECT 1 FROM alerts a JOIN states s ON s.id=a.state_id WHERE a.id=(v->>'alert_id')::integer AND s.is_terminal AND NOT s.is_resolution) THEN 'Anulada' ELSE 'Completada' END);
 END IF;
 IF p_resource='menu-options' THEN
 v:=v||jsonb_build_object('parent',(SELECT jsonb_build_object('id',id,'name',name) FROM menu_options WHERE id=(v->>'parent_id')::integer),'profiles',coalesce((SELECT jsonb_agg(jsonb_build_object('id',p.id,'name',p.name)) FROM profile_menu_option pm JOIN profiles p ON p.id=pm.profile_id WHERE pm.menu_option_id=p_id),'[]'::jsonb),'children',CASE WHEN p_depth<20 THEN coalesce((SELECT jsonb_agg(j2f_record('menu-options',id,p_depth+1) ORDER BY "order",id) FROM menu_options WHERE parent_id=p_id),'[]'::jsonb) ELSE '[]'::jsonb END);
 END IF;
 IF p_resource='reports' THEN v:=v||jsonb_build_object('generator',j2f_user((v->>'generated_by')::integer)-'profiles'-'profile','has_result',v->>'result_json' IS NOT NULL); END IF;
 RETURN v;
END $$;
CREATE OR REPLACE FUNCTION j2f_catalogs() RETURNS jsonb LANGUAGE sql STABLE AS $$
 SELECT jsonb_build_object('priorities',(SELECT jsonb_agg(to_jsonb(p) ORDER BY rank) FROM priorities p),'document_types',(SELECT jsonb_agg(to_jsonb(d) ORDER BY code) FROM document_types d WHERE code<>'Código interno'),'report_types',(SELECT jsonb_agg(jsonb_build_object('value',code,'label',label) ORDER BY code) FROM report_types),'states',(SELECT jsonb_agg(to_jsonb(s) ORDER BY id) FROM states s),'transitions',coalesce((SELECT jsonb_object_agg(name,targets) FROM (SELECT s.name,coalesce(jsonb_agg(t.name ORDER BY t.id) FILTER(WHERE t.id IS NOT NULL),'[]'::jsonb) targets FROM states s LEFT JOIN alert_transitions a ON a.from_state_id=s.id LEFT JOIN states t ON t.id=a.to_state_id WHERE s.type='alert' GROUP BY s.id) x),'{}'::jsonb),'parameters',(SELECT jsonb_object_agg(key,value) FROM app_parameters),'permissions',(SELECT jsonb_agg(to_jsonb(p)) FROM permissions p),'simulated_events',(SELECT jsonb_agg(e.code) FROM simulated_events se JOIN event_types e ON e.id=se.event_type_id))
$$;
-- Autenticación: el hash se comprueba con Werkzeug; nunca se devuelve al navegador.
CREATE OR REPLACE FUNCTION j2f_auth(p_action text,p_data jsonb) RETURNS jsonb LANGUAGE plpgsql AS $$
DECLARE u users; pid integer; profiles_json jsonb; BEGIN
 IF p_action='lookup' THEN
 SELECT * INTO u FROM users WHERE lower(email)=lower(p_data->>'identifier') OR dni=p_data->>'identifier';
 IF u.id IS NULL THEN RETURN NULL; END IF;
 RETURN jsonb_build_object('id',u.id,'password_hash',u.password_hash,'session_version',u.session_version);
 END IF;
 SELECT * INTO u FROM users WHERE id=(p_data->>'user_id')::integer FOR UPDATE;
 IF u.id IS NULL OR NOT EXISTS(SELECT 1 FROM states WHERE id=u.state_id AND is_active) THEN RAISE EXCEPTION USING ERRCODE='42501',MESSAGE='Cuenta no disponible'; END IF;
 IF p_action='status' THEN RETURN jsonb_build_object('session_version',u.session_version,'user',j2f_user(u.id,(p_data->>'profile_id')::integer)); END IF;
 IF p_action='logout' THEN UPDATE users SET session_version=session_version+1 WHERE id=u.id; RETURN '{}'::jsonb; END IF;
 profiles_json:=j2f_user(u.id)->'profiles';
 IF jsonb_array_length(profiles_json)=0 THEN RAISE EXCEPTION USING ERRCODE='42501',MESSAGE='La cuenta no tiene perfiles activos'; END IF;
 pid:=(p_data->>'profile_id')::integer;
 IF p_action='login' AND jsonb_array_length(profiles_json)=1 THEN pid:=(profiles_json->0->>'id')::integer; END IF;
 IF pid IS NOT NULL AND NOT EXISTS(SELECT 1 FROM user_profile up JOIN profiles p ON p.id=up.profile_id JOIN states s ON s.id=p.state_id WHERE up.user_id=u.id AND p.id=pid AND s.is_active) THEN RAISE EXCEPTION USING ERRCODE='42501',MESSAGE='Perfil no asignado o inactivo'; END IF;
 UPDATE users SET session_version=session_version+1,last_login=timezone('UTC',now()) WHERE id=u.id RETURNING * INTO u;
 RETURN jsonb_build_object('user',j2f_user(u.id,pid)||jsonb_build_object('profile',j2f_profile(pid)),'profiles',profiles_json,'active_profile_id',pid,'session_version',u.session_version,'requires_profile_selection',pid IS NULL);
END $$;
-- Lecturas filtradas: también se aplican permisos en la base, sin confiar en Angular.
CREATE OR REPLACE FUNCTION j2f_list(p_resource text,p_filters jsonb,p_user integer,p_profile integer) RETURNS jsonb LANGUAGE plpgsql STABLE AS $$
DECLARE result_children jsonb; r app_resources; v jsonb; rows_json jsonb:='[]'; row_id integer; where_sql text:='true'; total integer; pg integer; sz integer; BEGIN
 SELECT * INTO r FROM app_resources WHERE code=p_resource; IF r.code IS NULL THEN RAISE EXCEPTION 'Recurso desconocido'; END IF;
 IF p_resource IN ('users','profiles') THEN PERFORM j2f_require(p_user,p_profile,'admin'); END IF;
 IF p_resource='reports' THEN PERFORM j2f_require(p_user,p_profile,'reports'); END IF;
 IF p_resource='menu-options' AND coalesce(p_filters->>'navigation','false')<>'true' THEN PERFORM j2f_require(p_user,p_profile,'admin'); END IF;
 FOR row_id IN EXECUTE format('SELECT id FROM %I ORDER BY id',r.table_name) LOOP
 v:=j2f_record(p_resource,row_id);
 IF p_resource='alerts' AND NOT j2f_can_view(row_id,p_user,p_profile) THEN CONTINUE; END IF;
 IF p_resource='assignments' AND NOT j2f_can_view((v->>'alert_id')::integer,p_user,p_profile) THEN CONTINUE; END IF;
 IF p_resource IN ('clients','vehicles','gps-devices') AND NOT j2f_has(p_user,p_profile,'view_all') AND NOT j2f_has(p_user,p_profile,'admin') THEN
 IF NOT EXISTS(SELECT 1 FROM alerts a LEFT JOIN vehicles veh ON veh.id=a.vehicle_id WHERE j2f_can_view(a.id,p_user,p_profile) AND CASE p_resource WHEN 'clients' THEN veh.client_id=row_id WHEN 'vehicles' THEN a.vehicle_id=row_id ELSE a.gps_device_id=row_id END) THEN CONTINUE; END IF;
 END IF;
 IF coalesce(p_filters->>'active','false')='true' AND NOT coalesce((v->'state'->>'is_active')::boolean,false) THEN CONTINUE; END IF;
 IF p_resource='menu-options' AND coalesce(p_filters->>'navigation','false')='true' THEN
 IF NOT (v->'state'->>'is_active')::boolean OR NOT EXISTS(SELECT 1 FROM profile_menu_option WHERE profile_id=p_profile AND menu_option_id=row_id) THEN CONTINUE; END IF;
 END IF;
 IF p_resource='menu-options' AND (coalesce(p_filters->>'parent_only','false')='true' OR coalesce(p_filters->>'navigation','false')='true') AND v->>'parent_id' IS NOT NULL THEN CONTINUE; END IF;
 IF nullif(p_filters->>'state','') IS NOT NULL AND v->'state'->>'name'<>p_filters->>'state' THEN CONTINUE; END IF;
 IF nullif(p_filters->>'priority','') IS NOT NULL AND v->>'priority'<>p_filters->>'priority' THEN CONTINUE; END IF;
 IF nullif(p_filters->>'client_id','') IS NOT NULL AND coalesce(v->>'client_id',v->'vehicle'->>'client_id') IS DISTINCT FROM p_filters->>'client_id' THEN CONTINUE; END IF;
 IF nullif(p_filters->>'vehicle_id','') IS NOT NULL AND v->>'vehicle_id' IS DISTINCT FROM p_filters->>'vehicle_id' THEN CONTINUE; END IF;
 IF nullif(p_filters->>'alert_id','') IS NOT NULL AND v->>'alert_id' IS DISTINCT FROM p_filters->>'alert_id' THEN CONTINUE; END IF;
 IF nullif(p_filters->>'user_id','') IS NOT NULL AND v->>'user_id' IS DISTINCT FROM p_filters->>'user_id' THEN CONTINUE; END IF;
 IF nullif(p_filters->>'profile_id','') IS NOT NULL AND NOT EXISTS(SELECT 1 FROM user_profile WHERE user_id=row_id AND profile_id=(p_filters->>'profile_id')::integer) THEN CONTINUE; END IF;
 IF coalesce(p_filters->>'active_only','false')='true' AND v->>'completed_at' IS NOT NULL THEN CONTINUE; END IF;
 IF nullif(p_filters->>'search','') IS NOT NULL AND v::text NOT ILIKE '%'||(p_filters->>'search')||'%' THEN CONTINUE; END IF;
 IF nullif(p_filters->>'date_from','') IS NOT NULL AND (v->>'created_at')::timestamp<(p_filters->>'date_from')::timestamp THEN CONTINUE; END IF;
 IF nullif(p_filters->>'date_to','') IS NOT NULL AND (v->>'created_at')::timestamp>=(p_filters->>'date_to')::date+interval '1 day' THEN CONTINUE; END IF;
 IF p_resource='menu-options' AND coalesce(p_filters->>'navigation','false')='true' THEN
 SELECT coalesce(jsonb_agg(child ORDER BY (child->>'order')::integer,(child->>'id')::integer),'[]') INTO result_children FROM jsonb_array_elements(v->'children') child WHERE EXISTS(SELECT 1 FROM profile_menu_option pm JOIN menu_options m ON m.id=pm.menu_option_id JOIN states s ON s.id=m.state_id WHERE pm.profile_id=p_profile AND m.id=(child->>'id')::integer AND s.is_active);
 v:=v||jsonb_build_object('children',result_children);
 END IF;
 rows_json:=rows_json||jsonb_build_array(v);
 END LOOP;
 IF p_resource='alerts' THEN
 total:=jsonb_array_length(rows_json); pg:=greatest(1,coalesce(nullif(p_filters->>'page','')::integer,1)); sz:=least((j2f_param('max_page_size')#>>'{}')::integer,greatest(1,coalesce(nullif(p_filters->>'per_page','')::integer,(j2f_param('page_size')#>>'{}')::integer)));
 SELECT coalesce(jsonb_agg(value ORDER BY ord DESC),'[]') INTO rows_json FROM jsonb_array_elements(rows_json) WITH ORDINALITY t(value,ord) WHERE ord>greatest(0,total-pg*sz) AND ord<=total-(pg-1)*sz;
 RETURN jsonb_build_object('alerts',rows_json,'total',total,'page',pg,'per_page',sz,'pages',ceil(total::numeric/sz));
 END IF;
 RETURN jsonb_build_object(replace(p_resource,'-','_'),rows_json)||CASE WHEN p_resource='profiles' THEN jsonb_build_object('states',(SELECT jsonb_agg(to_jsonb(s)) FROM states s WHERE type='user')) WHEN p_resource='menu-options' THEN jsonb_build_object('configured',true) ELSE '{}'::jsonb END;
END $$;
-- Escritura tipada; la lista de columnas se valida contra information_schema y campos protegidos.
CREATE OR REPLACE FUNCTION j2f_save(p_resource text,p_id integer,p_data jsonb,p_user integer,p_profile integer) RETURNS integer LANGUAGE plpgsql AS $$
DECLARE r app_resources; data jsonb:=p_data; cols text; vals text; sets text; v_id integer; k text; item jsonb; BEGIN
 SELECT * INTO r FROM app_resources WHERE code=p_resource; IF r.code IS NULL THEN RAISE EXCEPTION 'Recurso desconocido'; END IF;
 PERFORM j2f_require(p_user,p_profile,r.write_permission);
 data:=data-'id'-'created_at'-'updated_at'-'session_version'-'last_login'-'result_json'-'resolved_at'-'opened_at'-'acknowledged_at'-'completed_at'-'response_time_minutes'-'generated_by'-'created_by';
 IF p_resource='clients' THEN
 IF data ? 'document_type' AND NOT EXISTS(SELECT 1 FROM document_types WHERE code=data->>'document_type') THEN RAISE EXCEPTION 'Tipo de documento inválido'; END IF;
 IF data ? 'document_number' AND NOT EXISTS(SELECT 1 FROM document_types WHERE code=coalesce(data->>'document_type',(SELECT document_type FROM clients WHERE id=p_id)) AND data->>'document_number' ~ pattern) THEN RAISE EXCEPTION 'Formato de documento inválido'; END IF;
 END IF;
 IF p_resource IN ('users','profiles') AND data ? 'state_id' AND NOT EXISTS(SELECT 1 FROM states WHERE id=(data->>'state_id')::integer AND type='user') THEN RAISE EXCEPTION 'Estado de cuenta inválido'; END IF;
 IF data ? 'priority' AND NOT EXISTS(SELECT 1 FROM priorities WHERE code=data->>'priority') THEN RAISE EXCEPTION 'Prioridad inválida'; END IF;
 IF data ? 'default_priority' AND NOT EXISTS(SELECT 1 FROM priorities WHERE code=data->>'default_priority') THEN RAISE EXCEPTION 'Prioridad inválida'; END IF;
 IF p_resource='reports' THEN
 IF NOT EXISTS(SELECT 1 FROM report_types WHERE code=data->>'type') THEN RAISE EXCEPTION 'Tipo de reporte inválido'; END IF;
 data:=data-'filters'; data:=data||jsonb_build_object('generated_by',p_user,'filters_json',coalesce(p_data->'filters','{}'::jsonb)::text);
 END IF;
 IF p_resource='alerts' AND p_id IS NOT NULL THEN data:=data-'state_id'; END IF;
 IF p_resource='alerts' AND p_id IS NULL THEN
 data:=data||jsonb_build_object('created_by',p_user,'state_id',j2f_state('initial_alert_state_code'));
 IF NOT data ? 'priority' THEN data:=data||jsonb_build_object('priority',j2f_param('default_priority')); END IF;
 END IF;
 IF p_resource IN ('clients','vehicles','gps-devices','event-types','users','profiles','menu-options') AND p_id IS NULL AND NOT data ? 'state_id' THEN data:=data||jsonb_build_object('state_id',j2f_state('default_state_code')); END IF;
 IF p_resource='event-types' AND p_id IS NULL AND NOT data ? 'default_priority' THEN data:=data||jsonb_build_object('default_priority',j2f_param('default_priority')); END IF;
 IF p_resource='menu-options' AND (data->>'parent_id')::integer=p_id THEN RAISE EXCEPTION 'Un menú no puede ser su propio padre'; END IF;
 IF p_resource='menu-options' AND data->>'parent_id' IS NOT NULL THEN
 IF EXISTS(WITH RECURSIVE tree AS (SELECT id,parent_id FROM menu_options WHERE id=(data->>'parent_id')::integer UNION SELECT m.id,m.parent_id FROM menu_options m JOIN tree t ON m.id=t.parent_id) SELECT 1 FROM tree WHERE id=p_id) THEN RAISE EXCEPTION 'El menú produciría un ciclo'; END IF;
 END IF;


 IF p_id IS NOT NULL AND p_resource IN ('clients','vehicles','gps-devices') AND (
 (data ? 'state_id' AND NOT EXISTS(SELECT 1 FROM states WHERE id=(data->>'state_id')::integer AND is_active)) OR
 (p_resource='vehicles' AND data ? 'client_id' AND (data->>'client_id')::integer<>(SELECT client_id FROM vehicles WHERE id=p_id)) OR
 (p_resource='gps-devices' AND data ? 'vehicle_id' AND (data->>'vehicle_id')::integer<>(SELECT vehicle_id FROM gps_devices WHERE id=p_id))) THEN
 IF EXISTS(SELECT 1 FROM alerts al JOIN states s ON s.id=al.state_id LEFT JOIN vehicles ve ON ve.id=al.vehicle_id WHERE NOT s.is_terminal AND CASE p_resource WHEN 'clients' THEN ve.client_id=p_id WHEN 'vehicles' THEN al.vehicle_id=p_id ELSE al.gps_device_id=p_id END) THEN RAISE EXCEPTION 'Resuelve o anula las alertas abiertas antes de desactivar o trasladar este registro'; END IF;
 END IF;
 -- Contenido mínimo y coherencia referencial verificados también en la BD.
 FOR k IN SELECT jsonb_object_keys(data) LOOP
 IF k IN ('full_name','business_name','name','title','plate','imei','code','document_number','email','dni') AND length(trim(coalesce(data->>k,'')))=0 THEN RAISE EXCEPTION 'El campo % es obligatorio',k; END IF;
 END LOOP;
 IF p_resource='users' AND data ? 'dni' AND data->>'dni' !~ '^[0-9]{8}$' THEN RAISE EXCEPTION 'DNI inválido'; END IF;
 IF data ? 'email' AND nullif(data->>'email','') IS NOT NULL AND data->>'email' !~ '^[^[:space:]@]+@[^[:space:]@]+[.][^[:space:]@]+$' THEN RAISE EXCEPTION 'Correo inválido'; END IF;
 IF p_resource='vehicles' AND data ? 'plate' THEN data:=jsonb_set(data,'{plate}',to_jsonb(upper(trim(data->>'plate')))); END IF;
 IF p_resource IN ('vehicles','gps-devices') THEN
 IF p_resource='vehicles' AND data ? 'client_id' AND NOT EXISTS(SELECT 1 FROM clients c JOIN states s ON s.id=c.state_id WHERE c.id=(data->>'client_id')::integer AND s.is_active) THEN RAISE EXCEPTION 'Cliente no activo'; END IF;
 IF p_resource='gps-devices' AND data ? 'vehicle_id' AND NOT EXISTS(SELECT 1 FROM vehicles v JOIN states s ON s.id=v.state_id WHERE v.id=(data->>'vehicle_id')::integer AND s.is_active) THEN RAISE EXCEPTION 'Vehículo no activo'; END IF;
 END IF;
 IF p_resource='alerts' THEN
 IF p_id IS NULL OR data ? 'title' THEN
   IF jsonb_typeof(data->'title') IS DISTINCT FROM 'string' OR length(regexp_replace(data->>'title','^\s+|\s+$','','g')) NOT BETWEEN 3 AND 200 THEN
     RAISE EXCEPTION USING ERRCODE='22023', MESSAGE='El título debe tener entre 3 y 200 caracteres';
   END IF;
 END IF;
 IF p_id IS NULL OR data ? 'description' THEN
   IF jsonb_typeof(data->'description') IS DISTINCT FROM 'string' OR length(regexp_replace(data->>'description','^\s+|\s+$','','g')) NOT BETWEEN 5 AND 2000 THEN
     RAISE EXCEPTION USING ERRCODE='22023', MESSAGE='La descripción debe tener entre 5 y 2000 caracteres';
   END IF;
 END IF;
 IF p_id IS NULL OR data ?| ARRAY['client_id','vehicle_id','event_type_id'] THEN
   IF num_nonnulls(data->>'client_id',data->>'vehicle_id') = 1 OR
      (data->>'vehicle_id' IS NOT NULL AND NOT EXISTS (
        SELECT 1 FROM vehicles WHERE id=(data->>'vehicle_id')::integer AND client_id=(data->>'client_id')::integer
      )) THEN
     RAISE EXCEPTION USING ERRCODE='22023', MESSAGE='Selecciona un cliente y un vehículo que le pertenezca';
   END IF;
   IF EXISTS (SELECT 1 FROM event_types WHERE id=coalesce((data->>'event_type_id')::integer,
       (SELECT event_type_id FROM alerts WHERE id=p_id)) AND code=j2f_param('fuel_event_code')#>>'{}')
       AND (CASE WHEN data ? 'vehicle_id' THEN (data->>'vehicle_id')::integer ELSE (SELECT vehicle_id FROM alerts WHERE id=p_id) END) IS NULL THEN
     RAISE EXCEPTION USING ERRCODE='22023', MESSAGE='Combustible bajo requiere un cliente y su vehículo';
   END IF;
 END IF;
 IF data->>'vehicle_id' IS NOT NULL AND NOT EXISTS(SELECT 1 FROM vehicles v JOIN states s ON s.id=v.state_id JOIN clients c ON c.id=v.client_id JOIN states cs ON cs.id=c.state_id WHERE v.id=(data->>'vehicle_id')::integer AND s.is_active AND cs.is_active) THEN RAISE EXCEPTION 'Vehículo o cliente no activo'; END IF;
 IF data->>'gps_device_id' IS NOT NULL AND NOT EXISTS(SELECT 1 FROM gps_devices g JOIN states s ON s.id=g.state_id WHERE g.id=(data->>'gps_device_id')::integer AND s.is_active AND g.vehicle_id=coalesce((data->>'vehicle_id')::integer,(SELECT vehicle_id FROM alerts WHERE id=p_id))) THEN RAISE EXCEPTION 'El GPS no corresponde al vehículo activo'; END IF;
 IF data->>'event_type_id' IS NOT NULL AND NOT EXISTS(SELECT 1 FROM event_types e JOIN states s ON s.id=e.state_id WHERE e.id=(data->>'event_type_id')::integer AND s.is_active AND e.generates_alert) THEN RAISE EXCEPTION 'Tipo de evento no activo'; END IF;
 END IF;
 IF p_resource='clients' AND p_data ? 'verification' THEN
 data:=data||jsonb_build_object('verification_json',(p_data->'verification'||jsonb_build_object('actor',jsonb_build_object('id',p_user,'full_name',(SELECT full_name FROM users WHERE id=p_user)),'timestamp',timezone('UTC',now()),'audit',coalesce((SELECT verification_json::jsonb->'audit' FROM clients WHERE id=p_id),'[]'::jsonb)||jsonb_build_array(p_data->'verification'||jsonb_build_object('actor',p_user,'timestamp',timezone('UTC',now())))))::text);
 END IF;
 SELECT string_agg(format('%I',c.column_name),','),string_agg(format('x.%I',c.column_name),','),string_agg(format('%I=x.%I',c.column_name,c.column_name),',') INTO cols,vals,sets FROM information_schema.columns c WHERE c.table_schema='public' AND c.table_name=r.table_name AND data ? c.column_name;
 IF cols IS NULL THEN RAISE EXCEPTION 'No hay campos editables'; END IF;
 IF p_id IS NULL THEN EXECUTE format('INSERT INTO %I(%s) SELECT %s FROM jsonb_populate_record(NULL::%I,$1) x RETURNING id',r.table_name,cols,vals,r.table_name) INTO v_id USING data;
 ELSE EXECUTE format('UPDATE %I t SET %s FROM jsonb_populate_record(NULL::%I,$1) x WHERE t.id=$2 RETURNING t.id',r.table_name,sets,r.table_name) INTO v_id USING data,p_id; END IF;
 IF v_id IS NULL THEN RAISE NO_DATA_FOUND USING MESSAGE='Registro no encontrado'; END IF;
 IF p_resource='users' THEN
 IF p_data ? 'profile_ids' THEN
 DELETE FROM user_profile WHERE user_id=v_id;
 INSERT INTO user_profile SELECT v_id,value::integer FROM jsonb_array_elements_text(p_data->'profile_ids');
 UPDATE users SET profile_id=(SELECT min(profile_id) FROM user_profile WHERE user_id=v_id) WHERE id=v_id;
 ELSIF p_data ? 'profile_id' THEN DELETE FROM user_profile WHERE user_id=v_id; INSERT INTO user_profile VALUES(v_id,(p_data->>'profile_id')::integer); END IF;
 UPDATE users SET session_version=session_version+1,updated_at=timezone('UTC',now()) WHERE id=v_id;
 END IF;
 IF p_resource='profiles' THEN
 -- El nombre visible no define los permisos. La administración asigna códigos explícitos.
 IF p_data ? 'permissions' THEN DELETE FROM profile_permissions WHERE profile_id=v_id; INSERT INTO profile_permissions SELECT v_id,value FROM jsonb_array_elements_text(p_data->'permissions'); END IF;
 IF p_data ? 'menu_option_ids' THEN DELETE FROM profile_menu_option WHERE profile_id=v_id; INSERT INTO profile_menu_option SELECT v_id,value::integer FROM jsonb_array_elements_text(p_data->'menu_option_ids'); END IF;
 UPDATE users SET session_version=session_version+1 WHERE id IN (SELECT user_id FROM user_profile WHERE profile_id=v_id);
 END IF;
 IF p_resource IN ('profiles','users') AND NOT EXISTS(SELECT 1 FROM users u JOIN user_profile up ON up.user_id=u.id JOIN profile_permissions pp ON pp.profile_id=up.profile_id WHERE pp.permission_code='admin' AND j2f_has(u.id,up.profile_id,'admin')) THEN RAISE EXCEPTION 'Debe existir al menos un administrador activo'; END IF;
 IF p_resource='menu-options' AND p_data ? 'profile_ids' THEN DELETE FROM profile_menu_option WHERE menu_option_id=v_id; INSERT INTO profile_menu_option SELECT value::integer,v_id FROM jsonb_array_elements_text(p_data->'profile_ids'); END IF;
 IF p_resource IN ('clients','vehicles') AND data ? 'state_id' AND NOT EXISTS(SELECT 1 FROM states WHERE id=(data->>'state_id')::integer AND is_active) THEN
 IF p_resource='clients' THEN UPDATE vehicles SET state_id=(data->>'state_id')::integer WHERE client_id=v_id; END IF;
 UPDATE gps_devices SET state_id=(data->>'state_id')::integer WHERE vehicle_id IN (SELECT id FROM vehicles WHERE CASE p_resource WHEN 'clients' THEN client_id=v_id ELSE id=v_id END);
 END IF;
 IF p_resource='alerts' THEN
   PERFORM j2f_log(v_id,p_user,p_profile,CASE WHEN p_id IS NULL THEN 'created' ELSE 'updated' END,
     CASE WHEN p_id IS NULL THEN 'Alerta creada' ELSE 'Alerta actualizada' END);
 END IF;
 RETURN v_id;
END $$;
-- Flujo de estados con bloqueo de fila y auditoría en la misma transacción.
CREATE OR REPLACE FUNCTION j2f_transition(p_alert integer,p_target integer,p_note text,p_user integer,p_profile integer,p_cancel boolean DEFAULT false) RETURNS void LANGUAGE plpgsql AS $$
DECLARE a alerts; old_state states; new_state states; BEGIN
 SELECT * INTO a FROM alerts WHERE id=p_alert FOR UPDATE; IF a.id IS NULL THEN RAISE NO_DATA_FOUND USING MESSAGE='Alerta no encontrada'; END IF;
 SELECT * INTO old_state FROM states WHERE id=a.state_id; SELECT * INTO new_state FROM states WHERE id=p_target AND type='alert';
 IF old_state.is_terminal THEN RAISE EXCEPTION 'La alerta está cerrada o anulada'; END IF;
 IF new_state.id IS NULL THEN RAISE EXCEPTION 'Estado inválido'; END IF;
 IF p_cancel THEN PERFORM j2f_require(p_user,p_profile,'cancel');
 ELSE IF NOT j2f_can_attend(p_alert,p_user,p_profile) THEN RAISE EXCEPTION USING ERRCODE='42501',MESSAGE='La atención corresponde al técnico asignado'; END IF;
 IF NOT EXISTS(SELECT 1 FROM alert_transitions WHERE from_state_id=a.state_id AND to_state_id=p_target) THEN RAISE EXCEPTION 'Transición no permitida'; END IF; END IF;
 IF new_state.is_terminal AND length(trim(coalesce(p_note,'')))<5 THEN RAISE EXCEPTION 'Registra una solución o motivo de al menos 5 caracteres'; END IF;
 IF new_state.is_resolution AND a.event_type_id IN (SELECT id FROM event_types WHERE code=j2f_param('fuel_event_code')#>>'{}') AND NOT EXISTS(SELECT 1 FROM history WHERE alert_id=a.id AND action='fuel_confirmed') THEN RAISE EXCEPTION 'Confirma el abastecimiento antes de cerrar'; END IF;
 UPDATE alerts SET state_id=p_target,updated_at=timezone('UTC',now()),acknowledged_at=coalesce(acknowledged_at,timezone('UTC',now())),resolved_at=CASE WHEN new_state.is_resolution THEN timezone('UTC',now()) ELSE NULL END WHERE id=p_alert;
 IF new_state.is_terminal THEN UPDATE assignments SET completed_at=timezone('UTC',now()),response_time_minutes=round(extract(epoch FROM (timezone('UTC',now())-assigned_at))/60,2) WHERE alert_id=p_alert AND completed_at IS NULL; END IF;
 PERFORM j2f_log(p_alert,p_user,p_profile,CASE WHEN p_cancel THEN 'cancelled' ELSE 'state_changed' END,p_note,old_state.name,new_state.name);
END $$;
CREATE OR REPLACE FUNCTION j2f_fuel(p_alert integer,p_data jsonb,p_user integer,p_profile integer) RETURNS jsonb LANGUAGE plpgsql AS $$
DECLARE a alerts; act text:=p_data->>'action'; history_action text; metadata jsonb; BEGIN
 SELECT * INTO a FROM alerts WHERE id=p_alert FOR UPDATE;
 IF a.id IS NULL THEN RAISE NO_DATA_FOUND USING MESSAGE='Alerta no encontrada'; END IF;
 IF NOT j2f_can_attend(p_alert,p_user,p_profile) THEN RAISE EXCEPTION USING ERRCODE='42501',MESSAGE='No puedes atender esta alerta'; END IF;
 IF EXISTS(SELECT 1 FROM states WHERE id=a.state_id AND is_terminal) THEN RAISE EXCEPTION 'La alerta es terminal'; END IF;
 IF NOT EXISTS(SELECT 1 FROM event_types WHERE id=a.event_type_id AND code=j2f_param('fuel_event_code')#>>'{}') THEN RAISE EXCEPTION 'La alerta no corresponde a combustible'; END IF;
 IF act NOT IN ('coordinate','confirm') OR act IS NULL THEN RAISE EXCEPTION 'Acción de combustible inválida'; END IF;
 IF length(trim(coalesce(p_data->>'observation','')))<5 THEN RAISE EXCEPTION 'Registra una observación de al menos 5 caracteres'; END IF;
 history_action:=CASE act WHEN 'coordinate' THEN 'fuel_coordinated' ELSE 'fuel_confirmed' END;
 IF EXISTS(SELECT 1 FROM history WHERE alert_id=p_alert AND action=history_action) THEN RAISE EXCEPTION 'La acción ya fue registrada'; END IF;
 IF act='confirm' AND NOT EXISTS(SELECT 1 FROM history WHERE alert_id=p_alert AND action='fuel_coordinated') THEN RAISE EXCEPTION 'Primero coordina el abastecimiento'; END IF;
 metadata:=jsonb_build_object('estacion',p_data->'station','observacion',p_data->>'observation','modalidad',CASE WHEN p_data->>'station' IS NULL THEN 'manual' ELSE 'mapa' END);
 PERFORM j2f_log(p_alert,p_user,p_profile,history_action,metadata::text);
 RETURN j2f_fuel_workflow(p_alert);
END $$;
CREATE OR REPLACE FUNCTION j2f_fuel_workflow(p_alert integer) RETURNS jsonb LANGUAGE sql STABLE AS $$
 SELECT jsonb_build_object('fuel_status',CASE WHEN EXISTS(SELECT 1 FROM history WHERE alert_id=p_alert AND action='fuel_confirmed') THEN 'confirmed' WHEN EXISTS(SELECT 1 FROM history WHERE alert_id=p_alert AND action='fuel_coordinated') THEN 'coordinated' ELSE 'pending' END,'fuel_workflow',jsonb_build_object('coordination',(SELECT jsonb_build_object('station',detail::jsonb->'estacion','observation',detail::jsonb->>'observacion','timestamp',timestamp) FROM history WHERE alert_id=p_alert AND action='fuel_coordinated' ORDER BY id DESC LIMIT 1),'confirmation',(SELECT jsonb_build_object('station',detail::jsonb->'estacion','observation',detail::jsonb->>'observacion','timestamp',timestamp) FROM history WHERE alert_id=p_alert AND action='fuel_confirmed' ORDER BY id DESC LIMIT 1)))
$$;
CREATE OR REPLACE FUNCTION j2f_assign(p_alert integer,p_target integer,p_auto boolean,p_note text,p_user integer,p_profile integer) RETURNS integer LANGUAGE plpgsql AS $$
DECLARE a alerts; target integer:=p_target; v_id integer; BEGIN
 PERFORM j2f_require(p_user,p_profile,'assign');
 -- Serializa la selección de carga para que dos autoasignaciones no elijan sobre datos viejos.
 IF p_auto THEN PERFORM pg_advisory_xact_lock(7823441); END IF;
 SELECT * INTO a FROM alerts WHERE id=p_alert FOR UPDATE;
 IF a.id IS NULL THEN RAISE NO_DATA_FOUND USING MESSAGE='Alerta no encontrada'; END IF;
 IF EXISTS(SELECT 1 FROM states WHERE id=a.state_id AND is_terminal) THEN RAISE EXCEPTION 'No se asignan alertas terminales'; END IF;
 IF p_auto THEN
 IF EXISTS(SELECT 1 FROM assignments WHERE alert_id=p_alert AND completed_at IS NULL) THEN RAISE EXCEPTION 'La alerta ya está asignada'; END IF;
 SELECT u.id INTO target FROM users u WHERE EXISTS(SELECT 1 FROM user_profile up WHERE up.user_id=u.id AND j2f_has(u.id,up.profile_id,'attend') AND NOT j2f_has(u.id,up.profile_id,'admin')) ORDER BY (SELECT count(*) FROM assignments WHERE user_id=u.id AND completed_at IS NULL),u.id LIMIT 1;
 END IF;
 IF target IS NULL OR NOT EXISTS(SELECT 1 FROM user_profile up WHERE up.user_id=target AND j2f_has(target,up.profile_id,'attend') AND NOT j2f_has(target,up.profile_id,'admin')) THEN RAISE EXCEPTION 'Selecciona un técnico activo'; END IF;
 UPDATE assignments SET completed_at=timezone('UTC',now()) WHERE alert_id=p_alert AND completed_at IS NULL;
 INSERT INTO assignments(alert_id,user_id,assignment_type) VALUES(p_alert,target,CASE WHEN p_auto THEN 'auto' ELSE 'manual' END) RETURNING id INTO v_id;
 UPDATE alerts SET state_id=j2f_state('working_alert_state_code'),acknowledged_at=coalesce(acknowledged_at,timezone('UTC',now())),updated_at=timezone('UTC',now()) WHERE id=p_alert;
 PERFORM j2f_log(p_alert,p_user,p_profile,'assigned','Asignada a '||(SELECT full_name FROM users WHERE id=target));
 IF nullif(trim(p_note),'') IS NOT NULL THEN PERFORM j2f_log(p_alert,p_user,p_profile,'note_added',jsonb_build_object('kind','assignment_note','assignment_id',v_id,'text',p_note)::text); END IF;
 RETURN v_id;
END $$;
CREATE OR REPLACE FUNCTION j2f_metrics(p_user integer,p_profile integer) RETURNS jsonb LANGUAGE sql STABLE AS $$
 WITH visible AS(SELECT a.* FROM alerts a WHERE j2f_can_view(a.id,p_user,p_profile))
 SELECT jsonb_build_object('total_alerts',(SELECT count(*) FROM visible),'by_state',(SELECT jsonb_object_agg(s.name,(SELECT count(*) FROM visible a WHERE a.state_id=s.id)) FROM states s WHERE type='alert'),'critical_open',coalesce((SELECT jsonb_agg(j2f_record('alerts',id)) FROM (SELECT a.id FROM visible a JOIN states s ON s.id=a.state_id JOIN priorities p ON p.code=a.priority WHERE NOT s.is_terminal AND p.rank=(SELECT min(rank) FROM priorities) ORDER BY a.opened_at DESC LIMIT (j2f_param('critical_list_limit')#>>'{}')::integer) x),'[]'::jsonb),'avg_response_time_minutes',coalesce((SELECT round(avg(extract(epoch FROM(a.resolved_at-a.opened_at))/60),2) FROM visible a JOIN states s ON s.id=a.state_id WHERE s.is_resolution AND a.resolved_at IS NOT NULL),0))
$$;
CREATE OR REPLACE FUNCTION j2f_map(p_filters jsonb,p_user integer,p_profile integer) RETURNS jsonb LANGUAGE plpgsql STABLE AS $$
DECLARE v vehicles; ev jsonb; result jsonb:='[]'; BEGIN
 FOR v IN SELECT veh.* FROM vehicles veh JOIN states s ON s.id=veh.state_id JOIN clients c ON c.id=veh.client_id JOIN states cs ON cs.id=c.state_id WHERE s.is_active AND cs.is_active AND (nullif(p_filters->>'client_id','') IS NULL OR veh.client_id=(p_filters->>'client_id')::integer) AND (j2f_has(p_user,p_profile,'view_all') OR EXISTS(SELECT 1 FROM alerts WHERE vehicle_id=veh.id AND j2f_can_view(id,p_user,p_profile))) ORDER BY veh.plate LOOP
 SELECT coalesce(jsonb_agg(jsonb_build_object('alert_id',a.id,'code',e.code,'name',coalesce(e.name,a.title),'priority',a.priority,'can_coordinate',j2f_can_attend(a.id,p_user,p_profile))||j2f_fuel_workflow(a.id) ORDER BY a.opened_at DESC),'[]'::jsonb) INTO ev FROM alerts a JOIN states s ON s.id=a.state_id LEFT JOIN event_types e ON e.id=a.event_type_id WHERE a.vehicle_id=v.id AND NOT s.is_terminal AND j2f_can_view(a.id,p_user,p_profile);
 result:=result||jsonb_build_array(to_jsonb(v)||jsonb_build_object('client',j2f_record('clients',v.client_id),'gps_device',(SELECT j2f_record('gps-devices',g.id,1) FROM gps_devices g JOIN states s ON s.id=g.state_id WHERE g.vehicle_id=v.id AND s.is_active ORDER BY g.id LIMIT 1),'open_events',ev,'fuel_confirmation',(SELECT jsonb_build_object('alert_id',h.alert_id,'timestamp',h.timestamp) FROM history h JOIN alerts a ON a.id=h.alert_id WHERE a.vehicle_id=v.id AND h.action='fuel_confirmed' AND j2f_can_view(a.id,p_user,p_profile) ORDER BY h.id DESC LIMIT 1)));
 END LOOP; RETURN jsonb_build_object('vehicles',result);
END $$;
-- Los cálculos de reportes también se ejecutan en PostgreSQL.
CREATE OR REPLACE FUNCTION j2f_generate(p_report integer,p_user integer,p_profile integer) RETURNS jsonb LANGUAGE plpgsql AS $$
DECLARE r reports; f jsonb; result jsonb; data jsonb; BEGIN
 PERFORM j2f_require(p_user,p_profile,'reports'); SELECT * INTO r FROM reports WHERE id=p_report FOR UPDATE;
 IF r.id IS NULL THEN RAISE NO_DATA_FOUND USING MESSAGE='Reporte no encontrado'; END IF;
 f:=coalesce(r.filters_json::jsonb,'{}');
 -- Una tabla temporal por llamada mantiene un único conjunto filtrado para los agregados.
 CREATE TEMP TABLE IF NOT EXISTS j2f_report_alerts (LIKE alerts) ON COMMIT DROP;
 TRUNCATE j2f_report_alerts;
 INSERT INTO j2f_report_alerts SELECT a.* FROM alerts a LEFT JOIN vehicles v ON v.id=a.vehicle_id JOIN states s ON s.id=a.state_id WHERE
 (r.type='operator_performance' OR ((r.date_range_start IS NULL OR (CASE WHEN r.type='response_times' THEN a.opened_at ELSE a.created_at END)>=r.date_range_start) AND (r.date_range_end IS NULL OR (CASE WHEN r.type='response_times' THEN a.opened_at ELSE a.created_at END)<r.date_range_end+interval '1 day'))) AND
 (nullif(f->>'client_id','') IS NULL OR v.client_id=(f->>'client_id')::integer) AND (nullif(f->>'vehicle_id','') IS NULL OR a.vehicle_id=(f->>'vehicle_id')::integer) AND (nullif(f->>'priority','') IS NULL OR a.priority=f->>'priority') AND (nullif(f->>'state','') IS NULL OR s.name=f->>'state') AND (nullif(f->>'user_id','') IS NULL OR EXISTS(SELECT 1 FROM assignments WHERE alert_id=a.id AND user_id=(f->>'user_id')::integer));
 CASE r.type
 WHEN 'alerts_summary' THEN
 SELECT jsonb_build_object('total_alerts',(SELECT count(*) FROM j2f_report_alerts),'by_priority',coalesce((SELECT jsonb_object_agg(priority,n) FROM(SELECT priority,count(*) n FROM j2f_report_alerts GROUP BY priority)x),'{}'::jsonb),'by_state',coalesce((SELECT jsonb_object_agg(name,n) FROM(SELECT s.name,count(*) n FROM j2f_report_alerts a JOIN states s ON s.id=a.state_id GROUP BY s.name)x),'{}'::jsonb)) INTO data;
 WHEN 'response_times' THEN
 SELECT jsonb_build_object('by_priority',coalesce(jsonb_object_agg(priority,stats),'{}'::jsonb)) INTO data FROM(SELECT a.priority,jsonb_build_object('count',count(*),'avg_minutes',round(avg(extract(epoch FROM(a.resolved_at-a.opened_at))/60),2),'min_minutes',min(extract(epoch FROM(a.resolved_at-a.opened_at))/60),'max_minutes',max(extract(epoch FROM(a.resolved_at-a.opened_at))/60)) stats FROM j2f_report_alerts a JOIN states s ON s.id=a.state_id WHERE s.is_resolution AND a.resolved_at IS NOT NULL GROUP BY a.priority)x;
 WHEN 'operator_performance' THEN
 SELECT jsonb_build_object('rows',coalesce(jsonb_agg(to_jsonb(x) ORDER BY technician),'[]'::jsonb)) INTO data FROM(SELECT u.id technician_id,u.full_name technician,count(*) assigned,count(*) FILTER(WHERE a.completed_at IS NULL) active,count(*) FILTER(WHERE a.completed_at IS NOT NULL AND s.is_resolution AND NOT EXISTS(SELECT 1 FROM assignments n WHERE n.alert_id=a.alert_id AND n.id>a.id)) resolved,count(*) FILTER(WHERE a.completed_at IS NOT NULL AND NOT s.is_resolution AND s.is_terminal AND NOT EXISTS(SELECT 1 FROM assignments n WHERE n.alert_id=a.alert_id AND n.id>a.id)) cancelled,count(*) FILTER(WHERE EXISTS(SELECT 1 FROM assignments n WHERE n.alert_id=a.alert_id AND n.id>a.id)) reassigned,round(avg(a.response_time_minutes) FILTER(WHERE s.is_resolution AND NOT EXISTS(SELECT 1 FROM assignments n WHERE n.alert_id=a.alert_id AND n.id>a.id))::numeric,2) avg_response_minutes FROM assignments a JOIN j2f_report_alerts ra ON ra.id=a.alert_id JOIN states s ON s.id=ra.state_id JOIN users u ON u.id=a.user_id WHERE (nullif(f->>'user_id','') IS NULL OR a.user_id=(f->>'user_id')::integer) AND (r.date_range_start IS NULL OR a.assigned_at>=r.date_range_start) AND (r.date_range_end IS NULL OR a.assigned_at<r.date_range_end+interval '1 day') GROUP BY u.id)x;
 ELSE RAISE EXCEPTION 'Este tipo de reporte requiere un generador instalado en PostgreSQL'; END CASE;
 result:=data||jsonb_build_object('type',r.type,'filters',f,'filter_labels',f,'date_range',jsonb_build_object('start',r.date_range_start,'end',r.date_range_end),'generated_at',timezone('UTC',now()),'generated_by',jsonb_build_object('id',p_user,'full_name',(SELECT full_name FROM users WHERE id=p_user)));
 UPDATE reports SET result_json=result::text WHERE id=p_report; RETURN result;
END $$;
-- Punto de entrada único: distribuye hacia subprogramas de negocio, no ejecuta SQL recibido.
CREATE OR REPLACE FUNCTION j2f_api(p_resource text,p_action text,p_id integer,p_data jsonb,p_filters jsonb,p_user integer,p_profile integer) RETURNS jsonb LANGUAGE plpgsql AS $$
DECLARE r app_resources; v jsonb; et event_types; n integer; target integer; result jsonb; note text; BEGIN
 IF p_resource='catalogs' THEN RETURN j2f_catalogs(); END IF;
 IF NOT EXISTS(SELECT 1 FROM user_profile up JOIN users u ON u.id=up.user_id JOIN profiles p ON p.id=up.profile_id JOIN states us ON us.id=u.state_id JOIN states ps ON ps.id=p.state_id WHERE u.id=p_user AND p.id=p_profile AND us.is_active AND ps.is_active) THEN RAISE EXCEPTION USING ERRCODE='42501',MESSAGE='Selecciona un perfil activo'; END IF;
 IF p_resource='history' THEN
 IF p_action='detail' THEN
   IF NOT j2f_can_view(p_id,p_user,p_profile) THEN RAISE insufficient_privilege; END IF;
   RETURN jsonb_build_object('history',j2f_history(p_id));
 END IF;
 DECLARE
   pg integer := coalesce((p_filters->>'page')::integer,1);
   size integer := coalesce((p_filters->>'per_page')::integer,30);
   first_day date := nullif(p_filters->>'date_from','')::date;
   last_day date := nullif(p_filters->>'date_to','')::date;
   action_filter text := nullif(p_filters->>'action','');
 BEGIN
   IF pg < 1 OR size NOT BETWEEN 1 AND 200 OR first_day > last_day THEN
     RAISE EXCEPTION USING ERRCODE='22023', MESSAGE='Revisa la paginación y el intervalo de fechas';
   END IF;
   WITH filtered AS (
     SELECT h.* FROM history h
     WHERE j2f_can_view(h.alert_id,p_user,p_profile)
       AND (p_filters->>'alert_id' IS NULL OR h.alert_id=(p_filters->>'alert_id')::integer)
       AND (action_filter IS NULL OR h.action=action_filter OR
         (action_filter='escalated' AND h.action='state_changed' AND
           h.new_state IN ('Escalado',(SELECT name FROM states WHERE code='escalated'))))
       AND (p_filters->>'user_id' IS NULL OR h.user_id=(p_filters->>'user_id')::integer)
       AND (first_day IS NULL OR h.timestamp>=first_day)
       AND (last_day IS NULL OR h.timestamp<last_day+1)
   ), page_rows AS (
     SELECT * FROM filtered ORDER BY timestamp DESC,id DESC LIMIT size OFFSET ((pg-1)::bigint*size)
   )
   SELECT jsonb_build_object('history',coalesce((SELECT jsonb_agg(j2f_history_entry(h) ORDER BY h.timestamp DESC,h.id DESC) FROM page_rows p JOIN history h ON h.id=p.id),'[]'),
     'total',count(*),'pages',ceil(count(*)::numeric/size),'current_page',pg) INTO result FROM filtered;
   RETURN result;
 END;
 END IF;
 IF p_resource='alerts' AND p_action='metrics' THEN RETURN j2f_metrics(p_user,p_profile); END IF;
 IF p_resource='alerts' AND p_action='map' THEN RETURN j2f_map(p_filters,p_user,p_profile); END IF;
 IF p_resource='alerts' AND p_action='event' THEN
 PERFORM j2f_require(p_user,p_profile,'assign');
 PERFORM 1 FROM vehicles v JOIN states s ON s.id=v.state_id JOIN clients c ON c.id=v.client_id JOIN states cs ON cs.id=c.state_id WHERE v.id=(p_data->>'vehicle_id')::integer AND s.is_active AND cs.is_active FOR UPDATE OF v;
 IF NOT FOUND THEN RAISE EXCEPTION 'Vehículo o cliente no activo'; END IF;
 SELECT e.* INTO et FROM event_types e JOIN simulated_events se ON se.event_type_id=e.id JOIN states s ON s.id=e.state_id WHERE e.code=p_data->>'event_code' AND s.is_active AND e.generates_alert;
 IF et.id IS NULL THEN RAISE EXCEPTION 'Evento no permitido'; END IF;
 IF et.code=j2f_param('fuel_event_code')#>>'{}' AND ((p_data->>'fuel_percent') IS NULL OR (p_data->>'fuel_percent')::numeric<0 OR (p_data->>'fuel_percent')::numeric>(j2f_param('low_fuel_threshold')#>>'{}')::numeric) THEN RAISE EXCEPTION 'El combustible supera el umbral o no es válido'; END IF;
 SELECT al.id INTO n FROM alerts al JOIN states s ON s.id=al.state_id WHERE al.vehicle_id=(p_data->>'vehicle_id')::integer AND al.event_type_id=et.id AND NOT s.is_terminal LIMIT 1;
 IF n IS NOT NULL THEN RETURN jsonb_build_object('created',false,'alert',j2f_record('alerts',n)); END IF;
 n:=j2f_save('alerts',NULL,jsonb_build_object('title',et.name||' - '||(SELECT plate FROM vehicles WHERE id=(p_data->>'vehicle_id')::integer),'description',coalesce(nullif(trim(et.description),''),et.name),'client_id',(SELECT client_id FROM vehicles WHERE id=(p_data->>'vehicle_id')::integer),'vehicle_id',p_data->'vehicle_id','gps_device_id',(SELECT g.id FROM gps_devices g JOIN states s ON s.id=g.state_id WHERE vehicle_id=(p_data->>'vehicle_id')::integer AND s.is_active ORDER BY g.id LIMIT 1),'event_type_id',et.id,'priority',et.default_priority,'source','Simulación','location',concat(p_data->>'latitude',', ',p_data->>'longitude')),p_user,p_profile);
 RETURN jsonb_build_object('created',true,'alert',j2f_record('alerts',n),'message','Evento registrado');
 END IF;
 IF p_resource='assignments' AND p_action='technicians' THEN
 PERFORM j2f_require(p_user,p_profile,'assign');
 RETURN jsonb_build_object('technicians',coalesce((SELECT jsonb_agg(j2f_user(u.id)||jsonb_build_object('active_assignments_count',(SELECT count(*) FROM assignments WHERE user_id=u.id AND completed_at IS NULL)) ORDER BY u.full_name) FROM users u WHERE EXISTS(SELECT 1 FROM user_profile up WHERE up.user_id=u.id AND j2f_has(u.id,up.profile_id,'attend') AND NOT j2f_has(u.id,up.profile_id,'admin'))),'[]'::jsonb));
 END IF;
 IF p_action='list' THEN RETURN j2f_list(p_resource,p_filters,p_user,p_profile); END IF;
 SELECT * INTO r FROM app_resources WHERE code=p_resource; IF r.code IS NULL THEN RAISE NO_DATA_FOUND USING MESSAGE='Recurso desconocido'; END IF;
 IF p_action='create' AND p_resource NOT IN ('assignments') THEN n:=j2f_save(p_resource,NULL,p_data,p_user,p_profile); RETURN jsonb_build_object(r.singular,j2f_record(p_resource,n),'message','Registro creado'); END IF;
 IF p_resource='assignments' AND p_action IN ('create','auto-assign') THEN
 n:=j2f_assign((p_data->>'alert_id')::integer,(p_data->>'user_id')::integer,p_action='auto-assign',p_data->>'notes',p_user,p_profile); RETURN jsonb_build_object('assignment',j2f_record('assignments',n),'message','Asignación registrada'); END IF;
 v:=j2f_record(p_resource,p_id); IF v IS NULL THEN RAISE NO_DATA_FOUND USING MESSAGE='Registro no encontrado'; END IF;
 IF p_resource='alerts' THEN
 IF NOT j2f_can_view(p_id,p_user,p_profile) THEN RAISE EXCEPTION USING ERRCODE='42501',MESSAGE='Alerta fuera de tu alcance'; END IF;
 ELSIF p_resource='assignments' THEN
 IF NOT j2f_can_view((v->>'alert_id')::integer,p_user,p_profile) THEN RAISE EXCEPTION USING ERRCODE='42501',MESSAGE='Asignación fuera de tu alcance'; END IF;
 ELSIF p_resource='reports' THEN PERFORM j2f_require(p_user,p_profile,'reports');
 ELSIF p_resource IN ('users','profiles','menu-options') THEN PERFORM j2f_require(p_user,p_profile,'admin');
 ELSE IF NOT j2f_has(p_user,p_profile,'admin') AND NOT j2f_has(p_user,p_profile,'view_all') AND NOT EXISTS(SELECT 1 FROM jsonb_array_elements(j2f_list(p_resource,'{}',p_user,p_profile)->replace(p_resource,'-','_')) x WHERE (x->>'id')::integer=p_id) THEN RAISE EXCEPTION USING ERRCODE='42501',MESSAGE='Registro fuera de tu alcance'; END IF;
 END IF;
 IF p_action IN ('get','access') THEN RETURN jsonb_build_object(r.singular,v); END IF;
 IF p_resource='reports' AND p_action='generate' THEN RETURN jsonb_build_object('result',j2f_generate(p_id,p_user,p_profile),'message','Reporte generado','report',j2f_record('reports',p_id)); END IF;
 IF p_resource='alerts' AND p_action='fuel' THEN RETURN j2f_fuel(p_id,p_data,p_user,p_profile)||jsonb_build_object('message','Acción documentada'); END IF;
 IF p_resource='alerts' AND (p_action='cancel' OR (p_action='update' AND p_data ? 'state_name')) THEN
 SELECT id INTO target FROM states WHERE name=p_data->>'state_name' AND type='alert'; IF p_action='cancel' THEN target:=j2f_state('cancelled_alert_state_code'); END IF;
 PERFORM j2f_transition(p_id,target,coalesce(p_data->>'reason',p_data->>'notes'),p_user,p_profile,p_action='cancel'); RETURN jsonb_build_object('alert',j2f_record('alerts',p_id),'message','Estado actualizado'); END IF;
 IF p_resource='assignments' AND p_action IN ('notes','add-note','update') THEN
 n:=(v->>'alert_id')::integer;
 IF p_action='notes' THEN RETURN jsonb_build_object('alert_id',n,'notes',(SELECT coalesce(jsonb_agg(value),'[]') FROM jsonb_array_elements(j2f_history(n)) WHERE value->>'action'='note_added'),'legacy_notes',(SELECT coalesce(jsonb_agg(jsonb_build_object('assignment_id',id,'detail',notes)),'[]') FROM assignments WHERE alert_id=n AND nullif(notes,'') IS NOT NULL),'legacy_audits','[]'::jsonb,'can_add',(j2f_can_attend(n,p_user,p_profile) OR j2f_has(p_user,p_profile,'supervise')) AND v->>'completed_at' IS NULL); END IF;
 IF NOT (j2f_can_attend(n,p_user,p_profile) OR j2f_has(p_user,p_profile,'supervise')) OR v->>'completed_at' IS NOT NULL THEN RAISE EXCEPTION USING ERRCODE='42501',MESSAGE='No puedes modificar esta asignación'; END IF;
 PERFORM 1 FROM alerts WHERE id=n FOR UPDATE;
 IF EXISTS(SELECT 1 FROM alerts a JOIN states s ON s.id=a.state_id WHERE a.id=n AND s.is_terminal) THEN RAISE EXCEPTION 'La alerta es terminal'; END IF;
 IF coalesce((p_data->>'complete')::boolean,false) AND NOT j2f_can_attend(n,p_user,p_profile) THEN RAISE EXCEPTION USING ERRCODE='42501',MESSAGE='El cierre corresponde al técnico asignado'; END IF;
 note:=coalesce(p_data->>'notes',p_data->>'solution');
 IF length(trim(coalesce(note,'')))<5 THEN RAISE EXCEPTION 'Registra una observación o solución de al menos 5 caracteres'; END IF;
 target:=j2f_log(n,p_user,p_profile,'note_added',jsonb_build_object('kind','assignment_note','assignment_id',p_id,'text',note)::text);
 IF coalesce((p_data->>'complete')::boolean,false) THEN PERFORM j2f_transition(n,j2f_state('resolved_alert_state_code'),note,p_user,p_profile); END IF;
 RETURN jsonb_build_object('assignment',j2f_record('assignments',p_id),'note',(SELECT value FROM jsonb_array_elements(j2f_history(n)) WHERE (value->>'id')::integer=target),'message','Observación registrada');
 END IF;
 IF p_action='update' THEN
 IF p_resource='alerts' THEN p_data:=p_data-'state_id'; END IF;
 n:=j2f_save(p_resource,p_id,p_data,p_user,p_profile); RETURN jsonb_build_object(r.singular,j2f_record(p_resource,n),'message','Registro actualizado'); END IF;
 IF p_action='delete' THEN
 PERFORM j2f_require(p_user,p_profile,'admin');
 IF p_resource='users' THEN PERFORM j2f_save('users',p_id,jsonb_build_object('state_id',(SELECT id FROM states WHERE code='inactive')),p_user,p_profile); RETURN jsonb_build_object('message','Usuario desactivado'); END IF;
 IF p_resource='alerts' THEN
 RAISE EXCEPTION USING ERRCODE='42501', MESSAGE='Las alertas se conservan para auditoría';
 END IF;
 IF p_resource='profiles' THEN
 IF EXISTS(SELECT 1 FROM user_profile WHERE profile_id=p_id) OR EXISTS(SELECT 1 FROM users WHERE profile_id=p_id) THEN RAISE EXCEPTION 'El perfil tiene usuarios asignados; desactívalo o reasigna primero'; END IF;
 DELETE FROM profile_menu_option WHERE profile_id=p_id;
 END IF;
 IF p_resource='menu-options' THEN DELETE FROM profile_menu_option WHERE menu_option_id=p_id; END IF;
 EXECUTE format('DELETE FROM %I WHERE id=$1',r.table_name) USING p_id;
 RETURN jsonb_build_object('message','Registro eliminado');
 END IF;
 RAISE EXCEPTION 'Operación no reconocida';
END $$;
-- Bootstrap local explícito: nunca existe una contraseña predeterminada.
CREATE OR REPLACE FUNCTION j2f_bootstrap(p_dni text,p_name text,p_email text,p_hash text) RETURNS integer LANGUAGE plpgsql AS $$
DECLARE n integer; pid integer; BEGIN
 PERFORM pg_advisory_xact_lock(7823442);
 IF EXISTS(SELECT 1 FROM users) THEN RAISE EXCEPTION 'El bootstrap solo se permite cuando no existen usuarios'; END IF;
 SELECT id INTO pid FROM profiles WHERE role_code='admin' ORDER BY id LIMIT 1;
 INSERT INTO users(dni,full_name,email,password_hash,profile_id,state_id) VALUES(p_dni,p_name,lower(p_email),p_hash,pid,j2f_state('default_state_code')) RETURNING id INTO n;
 INSERT INTO user_profile VALUES(n,pid); RETURN n;
END $$;
COMMIT;
