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
    assert emitter.calls == 0
