"""Contrato de facturación con PostgreSQL aislado y un emisor sustituible."""
from concurrent.futures import ThreadPoolExecutor
from decimal import Decimal
from threading import Lock

import pytest

from app.fact_api import BETA, FactAPI, ProviderError


def call(client, headers, method, path, **args):
    response = getattr(client, method)('/api/' + path, headers=headers, **args)
    assert response.status_code in (200, 201), (path, response.status_code, response.json)
    return response.json


def fleet(client, admin, suffix, plan='monthly', count=1, first='2027-01', paid=False):
    customer = call(client, admin, 'post', 'master-data/clients/', json={
        'document_type': 'RUC', 'document_number': f'20123456{suffix:03}',
        'business_name': f'Transportes {suffix}',
    })['record']['id']
    for i in range(count):
        vehicle = call(client, admin, 'post', 'master-data/vehicles/', json={
            'client_id': customer, 'plate': f'J{suffix:02}-{100+i:03}',
        })['record']['id']
        call(client, admin, 'put', f'billing/plans/{vehicle}', json={
            'plan': plan, 'service_start': '2027-01-20', 'first_period': first,
            'equipment_paid': paid,
        })
    return customer


def preview(client, admin, customer, period):
    return call(client, admin, 'get', f'billing/preview?client={customer}&period={period}')


class Emitter:
    def __init__(self):
        self.documents = {}
        self.lock = Lock()
        self.lose_create = False
        self.fail_send = False
        self.calls = 0
        self.production = False

    def request(self, path, data=None):
        if path.startswith('companies/'):
            return {'company': {'id': 1, 'branches': [{'id': 1}], 'modo_produccion': self.production},
                    'j2f_beta_endpoint': BETA, 'j2f_signing_ready': True}
        if path == 'invoices':
            with self.lock:
                self.calls += 1
                iid = len(self.documents) + 1
                doc = dict(data, id=iid, numero_completo=f'F001-{iid}', estado_sunat='PENDIENTE',
                           mto_imp_venta=str(sum(Decimal(l['j2f_precio_final']) for l in data['detalles'])))
                self.documents[iid] = doc
            if self.lose_create:
                raise ProviderError('Respuesta perdida')
            return doc
        if path.startswith('invoices?'):
            return {'total': len(self.documents), 'data': list(self.documents.values())}
        doc = self.documents[int(path.split('/')[1])]
        if path.endswith('/send-sunat'):
            if self.fail_send:
                raise ProviderError('Configuración incompleta', 400)
            doc.update(estado_sunat='ACEPTADO', respuesta_sunat={'code': '0'})
        return doc


@pytest.fixture
def emitter(app, monkeypatch):
    for name, value in dict(URL='http://localhost:8091', TOKEN='token-local',
                            COMPANY_ID='1', BRANCH_ID='1', SERIES='F001').items():
        monkeypatch.setitem(app.config, 'FACT_API_' + name, value)
    service = Emitter()
    monkeypatch.setattr(FactAPI, 'request', lambda _, path, data=None: service.request(path, data))
    return service


def test_cycles_and_concurrent_create(app, client, admin, emitter):
    customer = fleet(client, admin, 11, count=2)
    first = preview(client, admin, customer, '2027-01')
    assert first['total'] == 574 and len(first['lines']) == 4
    payload = dict(client=customer, period='2027-01', signature=first['signature'], total=1)
    def issue(_):
        with app.test_client() as worker:
            return worker.post('/api/billing/invoices', headers=admin, json=payload).status_code
    with ThreadPoolExecutor(max_workers=2) as pool:
        results = list(pool.map(issue, range(2)))
    assert min(results) in (200, 201) and set(results) <= {200, 201, 409}
    frozen = call(client, admin, 'post', 'billing/invoices', json=payload)
    assert emitter.calls == 1 and frozen['total'] == 574 and frozen['external_id'] == 1
    assert preview(client, admin, customer, '2027-02')['total'] == 74
    annual = fleet(client, admin, 12, plan='annual')
    assert preview(client, admin, annual, '2027-01')['total'] == 630
    assert preview(client, admin, annual, '2027-02')['total'] == 0
    assert preview(client, admin, annual, '2028-01')['total'] == 444
    existing = fleet(client, admin, 13, first='2027-03', paid=True)
    assert preview(client, admin, existing, '2027-02')['lines'] == []
    assert preview(client, admin, existing, '2027-03')['total'] == 37


def test_uncertain_create_and_send(client, admin, emitter):
    c = fleet(client, admin, 14)
    payload = dict(client=c, period='2027-01', signature=preview(client, admin, c, '2027-01')['signature'])
    emitter.production = True
    assert client.post('/api/billing/invoices', headers=admin, json=payload).status_code == 503
    emitter.production = False
    emitter.lose_create = True
    inv = call(client, admin, 'post', 'billing/invoices', json=payload)
    assert inv['status'] == 'uncertain'
    assert call(client, admin, 'post', 'billing/invoices', json=payload)['status'] == 'uncertain'
    route = f"billing/invoices/{inv['id']}/"
    found = call(client, admin, 'post', route+'consult')
    assert found['status'] == 'created' and found['external_id'] == 1
    emitter.fail_send = True
    assert call(client, admin, 'post', route+'send')['status'] == 'created'
    emitter.fail_send = False
    done = call(client, admin, 'post', route+'send')
    assert done['status'] == 'accepted' and done['external_id'] == found['external_id']
    assert emitter.calls == 1
    assert client.post('/api/'+route+'send', headers=admin).status_code == 409


def test_billing_permission(client, admin, emitter):
    profiles = call(client, admin, 'get', 'profiles/')['profiles']
    operator = next(p for p in profiles if p['role_code'] == 'operator')
    call(client, admin, 'post', 'users/', json={'dni':'56236789', 'full_name':'Usuario operativo',
         'email':'operador-fact@test.local', 'password':'PruebaClave123', 'profile_ids':[operator['id']]})
    auth = call(client, {}, 'post', 'auth/login', json={'identifier':'operador-fact@test.local',
                                                       'password':'PruebaClave123'})
    headers = {'Authorization':'Bearer '+auth['access_token']}
    assert client.get('/api/billing/catalog', headers=headers).status_code == 403
    for path in ('billing/invoices','billing/invoices/1/send','billing/invoices/1/consult'):
        assert client.post('/api/'+path, headers=headers, json={'client':1,'period':'2027-01'}).status_code == 403
    for path in ('invoices', 'invoices/1', 'invoices/1/pdf', 'invoices/1/xml'):
        assert client.get('/api/billing/' + path, headers=headers).status_code == 403
    assert emitter.calls == 0


def test_separate_services_same_vehicle_and_month(client, admin, emitter):
    customer = fleet(client, admin, 76)
    catalog = call(client, admin, 'get', 'billing/catalog')
    vehicle = next(v['id'] for v in catalog['vehicles'] if v['client_id'] == customer)
    invoices = []
    for concept, total in [('equipment', 250), ('month', 37)]:
        selection = dict(client=customer, vehicle=vehicle, period='2027-01')
        draft = call(client, admin, 'get', 'billing/preview',
                     query_string={**selection, 'concept': concept})
        assert draft['total'] == total
        payload = dict(**selection, concepts=[concept], signature=draft['signature'])
        invoice = call(client, admin, 'post', 'billing/invoices', json=payload)
        invoices.append(invoice['id'])
        assert invoice['total'] == total
        assert client.post('/api/billing/invoices', headers=admin, json=payload).status_code == 409
    assert invoices[0] != invoices[1] and emitter.calls == 2
    rows = call(client, admin, 'get', 'billing/invoices')['items']
    assert [r['id'] for r in rows[:2]] == invoices[::-1]
    assert all(r['created_at'] for r in rows[:2])



@pytest.mark.parametrize(('plan', 'suffix', 'total'), [('monthly', 77, 287), ('annual', 78, 630)])
def test_sell_new_plan(client, admin, emitter, plan, suffix, total):
    customer = fleet(client, admin, suffix, count=0)
    vehicle = call(client, admin, 'post', 'master-data/vehicles/', json={
        'client_id': customer, 'plate': f'J{suffix}-100',
    })['record']['id']
    sale = dict(client=customer, vehicle=vehicle, start='2027-02-23', plan=plan)

    def contract():
        catalog = call(client, admin, 'get', 'billing/catalog')
        return next(v['contract'] for v in catalog['vehicles'] if v['id'] == vehicle)

    quote = call(client, admin, 'post', 'billing/sales/preview', json=sale)
    assert quote['total'] == total and contract() is None
    assert client.post('/api/billing/sales', headers=admin,
                       json={**sale, 'signature': 'obsoleta'}).status_code == 409
    assert contract() is None
    sale['signature'] = quote['signature']
    invoice = call(client, admin, 'post', 'billing/sales', json=sale)
    assert invoice['total'] == total and invoice['status'] == 'created'
    assert contract()['service_start'] == sale['start']
    catalog = call(client, admin, 'get', 'billing/catalog')
    coverage = catalog['coverage'][str(vehicle)]
    assert coverage['start'] == sale['start']
    assert coverage['end'] == ('2027-03-22' if plan == 'monthly' else '2028-02-22')
    sold = catalog['sold_plans']
    assert sold[str(vehicle)] == ['Mensual' if plan == 'monthly' else 'Anual']
    assert client.post('/api/billing/sales', headers=admin, json=sale).status_code == 409
    assert emitter.calls == 1



def test_selected_plates_grouped_sale(client, admin, emitter):
    customer = fleet(client, admin, 86, count=0)
    def add(i):
        return call(client, admin, 'post', 'master-data/vehicles/', json={
            'client_id': customer, 'plate': f'J86-{i:03}',
        })['record']['id']
    first, second, other = [add(i) for i in range(100, 103)]
    payload = dict(client=customer, vehicles=[first, second], plan='monthly', start='2027-03-23')
    def sell(data):
        quote = call(client, admin, 'post', 'billing/sales/preview', json=data)
        return call(client, admin, 'post', 'billing/sales', json={**data, 'signature': quote['signature']})
    invoice = sell(payload)
    assert invoice['total'] == 574 and invoice['sale_start'] == payload['start']
    periods = call(client, admin, 'get', 'billing/catalog')['billed_periods']
    for vehicle in [first, second]:
        entry, = periods[str(vehicle)]
        assert (entry['period'], entry['number'], entry['amount']) == ('2027-03-01', invoice['number'], 37)
    assert str(other) not in periods
    assert {l['vehicle_id'] for l in invoice['lines']} == {first, second}
    assert client.post('/api/billing/sales/preview', headers=admin, json=payload).status_code == 409
    assert sell({**payload, 'vehicles': [other]})['total'] == 287
    assert sell({**payload, 'start': '2027-04-23'})['total'] == 74
    wrong = fleet(client, admin, 87, count=0)
    assert client.post('/api/billing/sales/preview', headers=admin,
                       json={**payload, 'client': wrong}).status_code == 400

def test_invoice_history_filters_before_pagination(app, client, admin):
    customer = fleet(client, admin, 93, count=0)
    other = fleet(client, admin, 94, count=0)
    for cid, count in [(customer, 32), (other, 35)]:
        app.config['TEST_SQL'](f"""
            INSERT INTO billing_invoices(client_id,period,recipient,issuer,total,created_by,issue_date)
            SELECT {cid}, date '2031-01-01' + n, '{{}}','{{}}',1,(SELECT min(id) FROM users),
                CASE WHEN n=1 THEN date '2031-03-01' ELSE date '2031-03-02' END
            FROM generate_series(1,{count}) n;
        """)
    path = 'billing/invoices'
    filters = {'client': customer, 'from': '2031-03-02', 'to': '2031-03-02'}
    page = call(client, admin, 'get', path, query_string=filters)
    assert page['has_more'] and len(page['items']) == 30
    assert all(row['issue_date'] == filters['from'] for row in page['items'])
    last = page['items'][-1]['id']
    rest = call(client, admin, 'get', path, query_string={**filters, 'before': last})
    assert len(rest['items']) == 1 and rest['items'][0]['id'] < last and not rest['has_more']
    assert not call(client, admin, 'get', path, query_string={'client': customer, 'to': '2031-02-28'})['items']
    assert client.get('/api/'+path, headers=admin, query_string={**filters, 'to':'2031-01-01'}).status_code == 400
