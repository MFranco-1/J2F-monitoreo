/** Reglas de entrada de los formularios. Flask vuelve a validar cada escritura. */
import { clientPhoneError } from './client-inputs';
export type FormKind = 'clients' | 'vehicles' | 'gps-devices' | 'event-types' |
  'users' | 'profiles' | 'menu-options' | 'alerts' | 'reports' | 'assignment' | 'fuel';
type Rule = { label: string; required?: boolean; min?: number; max: number; letters?: number; person?: boolean };
const rule = (label: string, min: number, max: number, required = false, letters = 2, person = false): Rule =>
  ({ label, min, max, required, letters, person });
const description = rule('Descripción', 5, 2000);
const rules: Record<FormKind, Record<string, Rule>> = {
  clients: {
    business_name: rule('Razón social', 3, 180, true),
    contact_name: rule('Contacto', 3, 150, false, 2, true),
    address: rule('Dirección', 5, 255),
  },
  vehicles: {
    brand: rule('Marca', 2, 100, false, 1), model: rule('Modelo', 2, 100, false, 0),
    color: rule('Color', 3, 50), vehicle_type: rule('Tipo de vehículo', 3, 80),
  },
  'gps-devices': { model: rule('Modelo', 2, 100, false, 0), provider: rule('Proveedor', 3, 100) },
  'event-types': { name: rule('Nombre', 3, 150, true), description,
    expected_action: rule('Acción esperada', 5, 2000) },
  users: { full_name: rule('Nombre completo', 3, 150, true, 2, true) },
  profiles: { name: rule('Nombre', 3, 100, true), description: rule('Descripción', 5, 255) },
  'menu-options': { name: rule('Nombre', 3, 100, true) },
  alerts: { title: rule('Título', 3, 200, true), description: rule('Descripción', 5, 2000, true),
    service_type: rule('Tipo de servicio', 3, 100), location: rule('Ubicación', 3, 200),
    source: rule('Origen', 3, 100), notes: rule('Observación / solución', 5, 2000) },
  reports: { name: rule('Nombre', 3, 200, true), description },
  assignment: { notes: rule('Observación', 5, 2000), solution: rule('Solución', 5, 2000) },
  fuel: { observation: rule('Observación de abastecimiento', 5, 500, true) },
};

const controlCharacters = /[\p{Cc}\p{Cf}]/u;
const emailPattern = /^[A-Za-z0-9!#$%&'*+/=?^_`{|}~.-]+@(?:[A-Za-z0-9](?:[A-Za-z0-9-]{0,61}[A-Za-z0-9])?\.)+[A-Za-z]{2,63}$/;
export function textError(value: unknown, spec: Rule): string {
  if (value === null || value === undefined || value === '') return spec.required ? `${spec.label}: campo obligatorio` : '';
  if (typeof value !== 'string') return `${spec.label}: debe ser texto`;
  const text = value.trim().normalize('NFC');
  if (!text) return spec.required ? `${spec.label}: campo obligatorio` : '';
  if (controlCharacters.test(text.replace(/[\n\r\t]/g, ''))) return `${spec.label}: contiene caracteres no permitidos`;
  if (text.length > spec.max) return `${spec.label}: máximo ${spec.max} caracteres`;
  const significant = [...text.toLowerCase()].filter(char => /[\p{L}\p{N}]/u.test(char));
  if (text.length < (spec.min ?? 0) || significant.length < 2 || new Set(significant).size < 2 ||
      [...text].filter(char => /\p{L}/u.test(char)).length < (spec.letters ?? 0)) {
    return `${spec.label}: ingresa un dato válido de al menos ${spec.min} caracteres, no una letra o símbolos aislados`;
  }
  if (spec.person && !/^[\p{L} .'-]+$/u.test(text)) return `${spec.label}: solo letras, espacios, puntos, apóstrofes y guiones`;
  if (spec.label === 'Dirección' && !/^[\p{L}0-9 .,/\-#]+$/u.test(text))
    return 'Dirección: solo admite letras (incluidas tildes y ñ), números, espacios y . , - / #';
  if (spec.label === 'Razón social' && ['sa', 'sac', 'saa', 'sacs', 'srl', 'eirl'].includes(text.toLowerCase().replace(/[^a-z]/g, '')))
    return 'Razón social: ingresa el nombre de la empresa, no solo su forma legal (S.A.C., S.A., etc.)';
  return '';
}

/** Solo estructura y dígito de control: no demuestra inscripción en SUNAT. */
export function rucError(value: string): string {
  if (!/^[0-9]{11}$/.test(value)) return 'El RUC debe contener exactamente 11 dígitos';
  if (!['10','15','16','17','20'].includes(value.slice(0,2))) return 'El prefijo del RUC no es válido';
  const weights = [5,4,3,2,7,6,5,4,3,2];
  const sum = weights.reduce((total, weight, index) => total + weight * Number(value[index]), 0);
  return Number(value[10]) === ((11 - sum % 11) % 10) ? '' : 'El dígito verificador del RUC no es válido; comprueba el número';
}

export function validateForm(kind: FormKind, data: Record<string, any>, editing = false): Record<string, string> {
  const errors: Record<string, string> = {};
  const value = (field: string): string => typeof data[field] === 'string' ? data[field].trim().normalize('NFC') : '';
  const check = (field: string, valid: boolean, message: string): void => { if (!valid) errors[field] = message; };
  for (const [field, spec] of Object.entries(rules[kind])) {
    const error = textError(data[field], spec);
    if (error) errors[field] = error;
  }
  if (['clients', 'vehicles', 'gps-devices', 'event-types', 'users', 'profiles', 'menu-options'].includes(kind)) {
    check('state_id', Number.isInteger(data['state_id']) && data['state_id'] > 0, 'Selecciona un estado válido');
  }
  if (kind === 'clients') {
    const type = value('document_type').toUpperCase();
    const documents: Record<string, [RegExp, string]> = {
      RUC: [/^[0-9]{11}$/, 'El RUC debe contener exactamente 11 dígitos'],
      DNI: [/^[0-9]{8}$/, 'El DNI debe contener exactamente 8 dígitos'],
      CE: [/^[0-9]{9,12}$/, 'El carné de extranjería debe contener de 9 a 12 dígitos'],
      PASAPORTE: [/^[A-Z0-9]{6,12}$/, 'El pasaporte debe contener de 6 a 12 letras o dígitos'],
    };
    check('document_type', !!documents[type], 'Selecciona un tipo de documento válido');
    if (documents[type]) check('document_number', documents[type][0].test(value('document_number').toUpperCase()), documents[type][1]);
    if (type === 'RUC' && !errors['document_number']) {
      const error = rucError(value('document_number'));
      if (error) errors['document_number'] = error;
    }
    const phoneError = clientPhoneError(data['phone'], data['phone_country']);
    if (phoneError) errors['phone'] = phoneError;
  }
  if (kind === 'clients' || kind === 'users') {
    const email = value('email');
    if (email || kind === 'users') check('email', email.length <= 150 && emailPattern.test(email) &&
      !email.startsWith('.') && !email.includes('..') && !email.includes('.@') && email.split('@')[0].length <= 64,
      'Correo electrónico inválido (ej. contacto@empresa.com)');
  }
  if (kind === 'users') {
    check('dni', /^[0-9]{8}$/.test(value('dni')), 'El DNI debe contener exactamente 8 dígitos');
    check('profile_ids', Array.isArray(data['profile_ids']) && data['profile_ids'].length > 0 &&
      data['profile_ids'].every((id: number) => Number.isInteger(id) && id > 0), 'Selecciona al menos un perfil válido');
    const password = data['password'];
    if (!editing || password !== '') check('password', typeof password === 'string' && !!password.trim() &&
      password.length >= 8 && password.length <= 128, 'La contraseña debe contener entre 8 y 128 caracteres y no solo espacios');
  }
  if (kind === 'vehicles') {
    check('client_id', Number.isInteger(data['client_id']) && data['client_id'] > 0, 'Selecciona un cliente válido');
    const plate = value('plate').toUpperCase();
    check('plate', /^[A-Z0-9]{2,4}-?[A-Z0-9]{2,4}$/.test(plate) && /[A-Z]/.test(plate) && /[0-9]/.test(plate),
      'Placa inválida: de 4 a 8 letras y dígitos, con un guion opcional (ej. ABC-123)');
  }
  if (kind === 'gps-devices') {
    check('vehicle_id', Number.isInteger(data['vehicle_id']) && data['vehicle_id'] > 0, 'Selecciona un vehículo válido');
    check('imei', /^[0-9]{15}$/.test(value('imei')), 'El IMEI debe contener exactamente 15 dígitos');
    if (value('serial_number')) check('serial_number', /^[A-Za-z0-9][A-Za-z0-9._/-]{2,79}$/.test(value('serial_number')), 'Número de serie: de 3 a 80 caracteres; admite letras, dígitos, . _ / -');
    if (value('sim_number')) check('sim_number', /^[0-9]{7,22}$/.test(value('sim_number')), 'SIM: de 7 a 22 dígitos, sin letras ni símbolos');
  }
  if (kind === 'event-types') {
    check('code', /^[A-Z][A-Z0-9]*(?:_[A-Z0-9]+)*$/.test(value('code').toUpperCase()) && value('code').length >= 2 && value('code').length <= 50,
      'Código: de 2 a 50 caracteres, comenzando por una letra; usa letras, dígitos y guiones bajos');
    check('generates_alert', typeof data['generates_alert'] === 'boolean', 'Indica si el evento genera alerta');
  }
  if (kind === 'event-types' || kind === 'alerts') {
    const priority = kind === 'event-types' ? 'default_priority' : 'priority';
    if (data[priority] !== undefined) check(priority, ['critical', 'high', 'medium', 'low'].includes(data[priority]), 'Selecciona una prioridad válida');
  }
  if (kind === 'menu-options') {
    check('url', !value('url') || (value('url').length <= 255 && /^\/(?:[A-Za-z0-9_-]+(?:\/[A-Za-z0-9_-]+)*)?$/.test(value('url'))), 'La ruta debe ser interna, por ejemplo /alerts; no admite espacios ni URLs externas');
    check('order', Number.isInteger(data['order']) && data['order'] >= 0, 'El orden debe ser un entero mayor o igual a cero');
    if (value('icon')) check('icon', /^[A-Za-z][A-Za-z0-9_-]{1,99}$/.test(value('icon')), 'Ícono: usa un identificador válido de al menos 2 caracteres');
  }
  if (kind === 'reports') {
    check('type', ['alerts_summary', 'operator_performance', 'response_times'].includes(data['type']), 'Selecciona un tipo de reporte válido');
    for (const field of ['date_range_start', 'date_range_end']) {
      if (data[field]) check(field, /^\d{4}-\d{2}-\d{2}$/.test(data[field]) &&
        Number.isFinite(Date.parse(data[field])) && new Date(data[field]).toISOString().slice(0, 10) === data[field], 'Selecciona una fecha válida');
    }
    if (!errors['date_range_start'] && !errors['date_range_end'] && data['date_range_start'] && data['date_range_end'])
      check('date_range_end', data['date_range_start'] <= data['date_range_end'], 'La fecha inicial no puede ser posterior a la fecha final');
  }
  return errors;
}

export function firstError(errors: Record<string, string>): string { return Object.values(errors)[0] || ''; }
