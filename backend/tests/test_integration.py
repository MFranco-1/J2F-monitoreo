"""Contrato REST y reglas reales de PL/pgSQL, incluyendo rechazos y rollback."""
import json


def request(client,headers,method,path,**kwargs):
    response=getattr(client,method)('/api/'+path,headers=headers,**kwargs)
    assert response.status_code in (200,201), (path,response.status_code,response.json)
    return response.json


def test_catalogs_and_permissions_are_data(client,admin):
    catalogs=client.get('/api/catalogs').json
    assert len(catalogs['priorities'])==4
    assert catalogs['parameters']['low_fuel_threshold']==10
    profiles=request(client,admin,'get','profiles/')['profiles']
    technician=next(p for p in profiles if p['role_code']=='technician')
    assert technician['permissions']==['attend']
    renamed=request(client,admin,'post','profiles/',json={'name':'Consulta Especial','permissions':['reports'],'state_id':technician['state_id']})['profile']
    assert renamed['permissions']==['reports']
    request(client,admin,'put',f'profiles/{renamed["id"]}',json={'name':'Perfil Renombrado'})
    assert request(client,admin,'get',f'profiles/{renamed["id"]}')['profile']['permissions']==['reports']
    request(client,admin,'delete',f'profiles/{renamed["id"]}')


def test_end_to_end_alert_fuel_reports_and_scope(client,admin):
    profiles=request(client,admin,'get','profiles/')['profiles']
    tech_profile=next(p for p in profiles if p['role_code']=='technician')
    tech=request(client,admin,'post','users/',json={'dni':'87654321','full_name':'Técnico de pruebas','email':'tech@test.local','password':'PruebaClave123','profile_ids':[tech_profile['id']]})['user']
    assert 'password_hash' not in tech
    c=request(client,admin,'post','master-data/clients/',json={'document_type':'RUC','document_number':'20123456789','business_name':'Empresa de pruebas'})['record']
    v=request(client,admin,'post','master-data/vehicles/',json={'client_id':c['id'],'plate':'abc-123'})['record']
    assert v['plate']=='ABC-123'
    gps=request(client,admin,'post','master-data/gps-devices/',json={'vehicle_id':v['id'],'imei':'123456789012345','model':'Modelo real'})['record']
    assert gps['model']=='Modelo real'
    event={'vehicle_id':v['id'],'event_code':'LOW_FUEL','fuel_percent':8,'latitude':-12,'longitude':-77}
    a=request(client,admin,'post','alerts/map/events',json=event)['alert']
    duplicate=request(client,admin,'post','alerts/map/events',json=event)
    assert duplicate['created'] is False and duplicate['alert']['id']==a['id']
    assert client.post('/api/alerts/map/events',headers=admin,json=event|{'fuel_percent':11}).status_code==409
    # Una validación fallida no desactiva el cliente ni altera datos relacionados.
    assert client.put(f'/api/master-data/clients/{c["id"]}',headers=admin,json={'state_id':2}).status_code==409
    assert request(client,admin,'get',f'master-data/clients/{c["id"]}')['record']['state']['is_active']
    login=request(client,{},'post','auth/login',json={'identifier':'tech@test.local','password':'PruebaClave123'})
    tech_headers={'Authorization':'Bearer '+login['access_token']}
    assert client.get('/api/users/',headers=tech_headers).status_code==403
    assert client.get(f'/api/alerts/{a["id"]}',headers=tech_headers).status_code==403
    assignment=request(client,admin,'post','assignments/auto-assign',json={'alert_id':a['id']})['assignment']
    assert assignment['user_id']==tech['id']
    assert request(client,tech_headers,'get',f'alerts/{a["id"]}')['alert']['id']==a['id']
    assert client.post(f'/api/alerts/{a["id"]}/cancel',headers=tech_headers,json={'reason':'No corresponde'}).status_code==403
    assert client.put(f'/api/alerts/{a["id"]}',headers=tech_headers,json={'state_name':'Cerrado','notes':'Intento de cierre sin abastecer'}).status_code==409
    request(client,tech_headers,'post',f'assignments/{assignment["id"]}/notes',json={'notes':'Diagnóstico registrado por el técnico'})
    notes=request(client,tech_headers,'get',f'assignments/{assignment["id"]}/notes')['notes']
    assert notes[0]['detail']=='Diagnóstico registrado por el técnico'
    request(client,tech_headers,'post',f'alerts/{a["id"]}/fuel-actions',json={'action':'coordinate','observation':'Coordinado con la estación'})
    request(client,tech_headers,'post',f'alerts/{a["id"]}/fuel-actions',json={'action':'confirm','observation':'Abastecimiento realizado'})
    closed=request(client,tech_headers,'put',f'alerts/{a["id"]}',json={'state_name':'Cerrado','notes':'Solución y cierre documentados'})['alert']
    assert closed['state']['is_resolution'] and closed['resolved_at']
    assert request(client,admin,'get','assignments/')['assignments'][0]['status']=='Completada'
    metrics=request(client,admin,'get','alerts/metrics')
    assert metrics['total_alerts']==1 and metrics['by_state']['Cerrado']==1
    for typ in ('alerts_summary','operator_performance','response_times'):
        report=request(client,admin,'post','reports/',json={'name':'Prueba '+typ,'type':typ,'filters':{}})['report']
        result=request(client,admin,'post',f'reports/{report["id"]}/generate')['result']
        assert result['type']==typ
        exported=client.get(f'/api/reports/{report["id"]}/export?format=json',headers=admin)
        assert exported.status_code==200 and json.loads(exported.data)['type']==typ
    request(client,tech_headers,'post','auth/logout',json={})
    assert client.get('/api/auth/me',headers=tech_headers).status_code==401


def test_no_sql_from_http_and_pagination(client,admin):
    assert client.get('/api/not-a-resource/',headers=admin).status_code in (404,409)
    assert client.post('/api/users/',headers=admin,json={'dni':'12345678','full_name':'Duplicado','email':'x@test.local','password':'PruebaClave123','profile_id':1}).status_code==409
    data=request(client,admin,'get','alerts/?per_page=1&page=1')
    assert len(data['alerts'])<=1
    # Eliminar el único administrador se revierte en PostgreSQL.
    assert client.delete('/api/users/1',headers=admin).status_code==409
    assert request(client,admin,'get','auth/me')['user']['state']['is_active']


def test_runtime_catalog_changes_and_existing_database_migration(app,client,admin):
    # Cambiar un catálogo SQL modifica las respuestas y la validación sin editar Python.
    execute=app.config['TEST_SQL']
    execute("INSERT INTO priorities(code,label,rank) VALUES('urgent','Urgente',0);")
    catalogs=client.get('/api/catalogs').json
    assert any(p['code']=='urgent' for p in catalogs['priorities'])
    alert=request(client,admin,'post','alerts/',json={'title':'Prioridad agregada desde SQL','priority':'urgent','description':'Verificación de prioridad desde catálogo'})['alert']
    assert alert['priority']=='urgent'
    execute("UPDATE app_parameters SET value='15'::jsonb WHERE key='low_fuel_threshold';")
    assert client.get('/api/catalogs').json['parameters']['low_fuel_threshold']==15
    # Reaplicar catálogos y funciones no recrea las tablas ni elimina los registros.
    from pathlib import Path
    directory=Path(__file__).resolve().parents[2]/'database'
    for name in ('02_catalogos.sql','03_funciones.sql'):
        execute((directory/name).read_text(encoding='utf-8'))
    assert request(client,admin,'get',f'alerts/{alert["id"]}')['alert']['priority']=='urgent'
    assert client.get('/api/catalogs').json['parameters']['low_fuel_threshold']==15
    assert request(client,admin,'get','auth/me')['user']['email']=='admin@test.local'


def test_alert_requires_description_and_consistent_fuel_vehicle(client, admin):
    create = lambda data: client.post('/api/alerts/', headers=admin, json=data)
    assert create({'title': 'Reporte en carretera'}).status_code == 400
    payload = {'title': 'Reserva de combustible', 'description': 'Requiere abastecimiento'}
    event_types = request(client, admin, 'get', 'master-data/event-types/')['event_types']
    fuel = next(event for event in event_types if event['code'] == 'LOW_FUEL')
    payload['event_type_id'] = fuel['id']
    assert create(payload).status_code == 400

    def company(number):
        return request(client, admin, 'post', 'master-data/clients/', json={
            'document_type': 'RUC', 'document_number': number, 'business_name': 'Transportes del Sur'
        })['record']['id']

    owner, other = company('20712345678'), company('20712345679')
    vehicle = request(client, admin, 'post', 'master-data/vehicles/', json={
        'client_id': owner, 'plate': 'TST-987'
    })['record']['id']
    assert create(payload | {'vehicle_id': vehicle}).status_code == 400
    assert create(payload | {'vehicle_id': vehicle, 'client_id': other}).status_code == 400
    assert create(payload | {'vehicle_id': vehicle, 'client_id': owner}).status_code == 201


def test_escalations_scope_pagination_and_terminal_audit(app, client, admin):
    alert = request(client, admin, 'post', 'alerts/', json={
        'title': 'Aviso de seguimiento', 'description': 'Monitorear la unidad'
    })['alert']
    aid = alert['id']
    base = f'alerts/{aid}'
    request(client, admin, 'put', base, json={'state_name': 'Escalado', 'notes': 'Validar con supervisión'})
    request(client, admin, 'put', base, json={'state_name': 'En Progreso'})
    app.config['TEST_SQL'](f"INSERT INTO history(alert_id,action,detail) VALUES({aid},'escalated','Registro histórico')")
    path = f'reports/history?alert_id={aid}&action=escalated&per_page=1'
    first = request(client, admin, 'get', path)
    second = request(client, admin, 'get', path + '&page=2')
    assert first['total'] == first['pages'] == 2
    assert second['current_page'] == 2
    assert [r['action'] for r in first['history'] + second['history']] == ['escalated', 'state_changed']
    assert second['history'][0]['new_state'] == 'Escalado'
    tech_profile = next(p for p in request(client, admin, 'get', 'profiles/')['profiles']
                        if p['role_code'] == 'technician')
    request(client, admin, 'post', 'users/', json={
        'dni': '65987654', 'full_name': 'Técnico sin asignación', 'email': 'otro@test.local',
        'password': 'ClaveLocal123', 'profile_ids': [tech_profile['id']]
    })
    login = request(client, {}, 'post', 'auth/login', json={
        'identifier': 'otro@test.local', 'password': 'ClaveLocal123'
    })
    tech = {'Authorization': 'Bearer ' + login['access_token']}
    assert request(client, tech, 'get', path)['total'] == 0
    assert client.get(f'/api/reports/history/alerts/{aid}', headers=tech).status_code == 403
    request(client, admin, 'post', base + '/cancel', json={'reason': 'Reporte duplicado por el operador'})
    assert client.delete('/api/' + base, headers=admin).status_code == 403
    entries = request(client, admin, 'get', f'reports/history/alerts/{aid}')['history']
    assert entries[0]['action'] == 'created' and entries[-1]['action'] == 'cancelled'
