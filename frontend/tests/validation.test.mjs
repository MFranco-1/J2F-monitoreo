import test from 'node:test';
import assert from 'node:assert/strict';
import fs from 'node:fs';
import vm from 'node:vm';
import ts from 'typescript';
import { createRequire } from 'node:module';

const source = fs.readFileSync(new URL('../src/app/shared/validation.ts', import.meta.url), 'utf8');
const compiled = ts.transpileModule(source, { compilerOptions: {
  module: ts.ModuleKind.CommonJS, target: ts.ScriptTarget.ES2022,
} }).outputText;
const exports = {};
const nodeRequire = createRequire(import.meta.url);
const clientSource = fs.readFileSync(new URL('../src/app/shared/client-inputs.ts', import.meta.url), 'utf8');
const clientExports = {};
vm.runInThisContext('(function(exports,require){' + ts.transpileModule(clientSource, { compilerOptions: {
  module: ts.ModuleKind.CommonJS, target: ts.ScriptTarget.ES2022,
} }).outputText + '\n})')(clientExports, nodeRequire);
vm.runInThisContext('(function(exports,require){' + compiled + '\n})')(exports, id => {
  assert.equal(id, './client-inputs'); return clientExports;
});
const { validateForm, firstError } = exports;
const validClient = {
  document_type: 'RUC', document_number: '20123456786', business_name: 'Logística Muñoz S.A.C.',
  contact_name: "José D'Ávila", phone: '987654321', email: 'contacto@empresa.com', address: 'Av. Perú 123', state_id: 1,
};
const validUser = { dni: '01234567', full_name: 'María Pérez', email: 'maria@empresa.com',
  password: 'Password-123!', profile_ids: [1], state_id: 1 };

test('clientes rechazan cada dato inválido de la presentación antes de enviar', () => {
  for (const [field, value] of [
    ['document_number', '3000000028254561'], ['document_number', '2012345678h'],
    ['business_name', 'A'], ['contact_name', 'A'], ['phone', '987654321h'], ['address', 'A'],
    ['business_name', '123456'], ['business_name', 'AAAAAA'], ['email', 'hola@gmail'],
    ['email', 'hola..nombre@gmail.com'], ['phone', '+51987654321'], ['phone', '987 654 321'],
    ['document_type', 'A'], ['business_name', 'Empresa\u200b falsa'], ['contact_name', 'Juan123'],
  ]) {
    assert.ok(validateForm('clients', { ...validClient, [field]: value })[field], `${field}: ${value}`);
  }
  assert.equal(firstError(validateForm('clients', validClient)), '');
  assert.equal(firstError(validateForm('clients', { ...validClient, contact_name: '', phone: '', email: '', address: '' })), '');
});

test('nombres se normalizan sin perder tildes y no basta la forma legal de la empresa', () => {
  assert.equal(clientExports.normalizeClientName('  tRANSPORTES   ÑANDÚ S.A.C.  '), 'Transportes ñandú s.a.c.');
  assert.equal(clientExports.normalizeClientName("aNA   PÉREZ D'ÁVILA"), "Ana pérez d'ávila");
  assert.equal(clientExports.normalizeClientName(' Jose\u0301 MUÑOZ '), 'José muñoz');
  for (const name of ['S.A.C.', 'sac', 'E.I.R.L.', 'S.A.', '  S. R. L.  '])
    assert.ok(validateForm('clients', {...validClient, business_name:name}).business_name);
});

test('direcciones solo admiten letras, dígitos, espacios y puntuación de direcciones', () => {
  for (const address of ['Av. Perú 123, Dpto. 301', 'Mz. A - Lote 15', 'Calle 50 # 12-45 / A', 'São João 25', 'Jr. Pe\u0301rez 123'])
    assert.equal(firstError(validateForm('clients', {...validClient, address})), '');
  for (const symbol of ['"', "'", '!', '¡', '?', '¿', '+', '=', '<', '>', '*', '%', '(', ')', '[', ']', '{', '}', '@', '\\', '$', '&', ';', '\n', '\t', '\u200b', '\x00'])
    assert.ok(validateForm('clients', {...validClient, address:`Av. Perú ${symbol} 123`}).address, symbol);
});

test('teléfonos nacionales se validan según el país, no solo por cantidad de dígitos', () => {
  for (const [phone_country, phone] of [['PE','987654321'], ['US','2025550123'], ['CA','4165550123'],
    ['ES','612345678'], ['CO','3001234567'], ['CL','961234567'], ['GB','2079460018'],
    ['IT','0212345678'], ['BR','11987654321']])
    assert.equal(firstError(validateForm('clients', {...validClient, phone_country, phone})), '', `${phone_country}: ${phone}`);
  for (const [phone_country, phone] of [['PE','9876543211111'], ['PE','123456789'], ['PE','000000000'],
    ['PE','98765432'], ['US','4165550123'], ['PE','3001234567'], ['XX','987654321'], ['','987654321'],
    ['PE','987 654 321'], ['PE','987-654-321'], ['PE','９８７６５４３２１'], ['PE',987654321],
    [false,'987654321'], ['PE','+51987654321']])
    assert.ok(validateForm('clients', {...validClient, phone_country, phone}).phone, `${phone_country}: ${phone}`);
  assert.equal(firstError(validateForm('clients', {...validClient, phone_country:'PE', phone:''})), '');
  assert.equal(firstError(validateForm('clients', {...validClient, phone_country:'PE', phone:'   '})), '');
});

test('selector incluye países con mismo prefijo y edición separa números actuales y antiguos', () => {
  const countries = clientExports.phoneCountries();
  assert.ok(countries.length > 200);
  assert.equal(countries[0].code, 'PE'); assert.equal(countries[0].label, 'Perú (+51)');
  assert.match(countries.find(item => item.code === 'US').label, /\(\+1\)/);
  assert.match(countries.find(item => item.code === 'CA').label, /\(\+1\)/);
  for (const [value, phone_country, phone] of [['+51987654321','PE','987654321'],
    ['51987654321','PE','987654321'], ['987654321','PE','987654321'],
    ['+14165550123','CA','4165550123'], ['+34612345678','ES','612345678'],
    ['+390212345678','IT','0212345678']])
    assert.deepEqual(clientExports.splitClientPhone(value), {phone_country, phone});
  assert.deepEqual(clientExports.splitClientPhone('987654321h'), {phone_country:'', phone:'987654321h'});
  assert.deepEqual(clientExports.splitClientPhone(null), {phone_country:'PE', phone:''});
});

test('documentos se validan como par; no exigen que toda empresa sea S.A.C.', () => {
  for (const [document_type, document_number] of [
    ['DNI', '01234567'], ['CE', '001234567'], ['PASAPORTE', 'ab123456'],
  ]) assert.equal(firstError(validateForm('clients', { ...validClient, document_type, document_number,
    business_name: 'Logística Muñoz E.I.R.L.' })), '');
  assert.ok(validateForm('clients', { ...validClient, document_type: 'DNI' })['document_number']);
  assert.ok(validateForm('clients', { ...validClient, document_number:'20123456789' })['document_number']);
  assert.ok(validateForm('clients', { ...validClient, document_number:'84545454445' })['document_number']);
  // Valores de control extremos: resultado 11 -> 1 y 10 -> 0.
  assert.equal(exports.rucError('20000000061'), '');
  assert.equal(exports.rucError('20000000010'), '');
  assert.equal(exports.rucError('20131312955'), '');
});

test('vehículos y GPS validan identificadores, relaciones y datos opcionales', () => {
  const vehicle = { plate: 'ABC-123', client_id: 1, state_id: 1, brand: 'MG', model: 'X5' };
  const gps = { imei: '860000000000001', vehicle_id: 1, state_id: 1, serial_number: '', sim_number: '51987654321' };
  assert.equal(firstError(validateForm('vehicles', vehicle)), '');
  assert.equal(firstError(validateForm('gps-devices', gps)), '');
  for (const plate of ['A', 'ABC!123', '123456', 'ABCDEF']) assert.ok(validateForm('vehicles', { ...vehicle, plate })['plate']);
  for (const [field, value] of [['imei', '123'], ['imei', '86000000000000h'], ['serial_number', 'A'],
    ['sim_number', '987654321h'], ['provider', 'A'], ['vehicle_id', null]]) {
    assert.ok(validateForm('gps-devices', { ...gps, [field]: value })[field]);
  }
});

test('usuarios validan nombres, DNI, correo, perfiles y nuevas contraseñas', () => {
  assert.equal(firstError(validateForm('users', validUser)), '');
  for (const [field, value] of [['full_name', 'A'], ['full_name', 'María123'], ['dni', '1234567h'],
    ['password', 'a'], ['password', '        '], ['password', 'a'.repeat(129)], ['profile_ids', []], ['email', 'a@b.c']]) {
    assert.ok(validateForm('users', { ...validUser, [field]: value })[field]);
  }
  assert.equal(firstError(validateForm('users', { ...validUser, password: '' }, true)), '');
  assert.ok(validateForm('users', { ...validUser, password: '' })['password']);
});

test('perfiles, menús y tipos de evento no aceptan letras aisladas ni formatos arbitrarios', () => {
  const event = { code: 'TEST_EVENT', name: 'Evento de prueba', state_id: 1, generates_alert: true, default_priority: 'high' };
  assert.equal(firstError(validateForm('event-types', event)), '');
  for (const [field, value] of [['code', 'A'], ['code', '1EVENT'], ['code', 'TEST EVENT'], ['name', 'A'],
    ['description', 'A'], ['expected_action', 'A'], ['default_priority', 'alta'], ['generates_alert', 'true']])
    assert.ok(validateForm('event-types', { ...event, [field]: value })[field]);
  assert.ok(validateForm('profiles', { name: 'A', state_id: 1 })['name']);
  const menu = { name: 'Consulta de alertas', url: '/alerts', order: 0, state_id: 1 };
  assert.equal(firstError(validateForm('menu-options', menu)), '');
  for (const url of ['https://example.com', '/bad path', 'javascript:alert(1)'])
    assert.ok(validateForm('menu-options', { ...menu, url })['url']);
  assert.ok(validateForm('menu-options', { ...menu, order: 1.5 })['order']);
});

test('alertas, reportes, soluciones y abastecimiento exigen contenido y fechas válidas', () => {
  assert.ok(validateForm('alerts', { title: 'A' })['title']);
  assert.equal(firstError(validateForm('alerts', { title: 'GPS', description: 'Incidencia que requiere revisión', priority: 'high' })), '');
  for (const observation of ['A', '...', '12345', 'AAAAAA', 'a'.repeat(501)])
    assert.ok(validateForm('fuel', { observation })['observation']);
  assert.equal(firstError(validateForm('fuel', { observation: 'Se cargaron 30 litros según comprobante 001' })), '');
  assert.ok(validateForm('assignment', { solution: 'A' })['solution']);
  assert.equal(firstError(validateForm('assignment', { notes: '' })), '');
  const report = { name: 'Informe mensual', type: 'alerts_summary' };
  for (const date_range_start of ['2026-02-30', 'ayer'])
    assert.ok(validateForm('reports', { ...report, date_range_start })['date_range_start']);
  assert.ok(validateForm('reports', { ...report, date_range_start: '2026-10-03', date_range_end: '2026-10-02' })['date_range_end']);
});
