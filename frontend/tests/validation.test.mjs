import test from 'node:test';
import assert from 'node:assert/strict';
import fs from 'node:fs';
import vm from 'node:vm';
import ts from 'typescript';

const source = fs.readFileSync(new URL('../src/app/shared/validation.ts', import.meta.url), 'utf8');
const compiled = ts.transpileModule(source, { compilerOptions: {
  module: ts.ModuleKind.CommonJS, target: ts.ScriptTarget.ES2022,
} }).outputText;
const exports = {};
vm.runInThisContext('(function(exports){' + compiled + '\n})')(exports);
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
  assert.equal(firstError(validateForm('alerts', { title: 'GPS', priority: 'high' })), '');
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
