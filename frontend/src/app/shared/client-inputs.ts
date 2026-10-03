import { CountryCode, getCountries, getCountryCallingCode, parsePhoneNumberFromString } from 'libphonenumber-js/max';

/** Mismo formato que Flask; no modifica registros hasta que se guardan. */
export function normalizeClientName(value: string): string {
  return value.trim().normalize('NFC').replace(/\s+/gu, ' ').toLowerCase()
    .replace(/\p{L}/u, letter => letter.toUpperCase());
}

export function phoneCountries(): { code: CountryCode; label: string }[] {
  const names = new Intl.DisplayNames(['es'], { type: 'region' });
  return getCountries().map(code => ({ code, label: `${names.of(code) || code} (+${getCountryCallingCode(code)})` }))
    .sort((left, right) => left.code === 'PE' ? -1 : right.code === 'PE' ? 1 : left.label.localeCompare(right.label, 'es'));
}

export function clientPhoneError(value: unknown, country?: unknown): string {
  if (country !== undefined && (typeof country !== 'string' || !getCountries().includes(country as CountryCode)))
    return 'Teléfono: selecciona un país válido';
  if (value === undefined || value === null || (typeof value === 'string' && !value.trim())) return '';
  if (typeof value !== 'string' || !/^[0-9]{7,15}$/.test(value.trim()))
    return 'Teléfono: ingresa solo dígitos, sin espacios ni símbolos; el prefijo se elige por país';
  const region = (country || 'PE') as CountryCode;
  const parsed = parsePhoneNumberFromString(value.trim(), { defaultCountry: region, extract: false });
  if (parsed && parsed.number.length > 16) return 'Teléfono: máximo 15 dígitos incluyendo el prefijo internacional';
  return parsed?.isValid() && parsed.country === region ? '' :
    'Teléfono: el número no es válido para el país seleccionado; revisa la longitud y el código de área';
}

/** Abre números actuales y heredados, sin sumar dos veces el prefijo. */
export function splitClientPhone(value?: string | null, country?: CountryCode | null): { phone: string; phone_country: string } {
  if (!value) return { phone: '', phone_country: country || 'PE' };
  const candidates = value.startsWith('+') ? [value] : [value, '+' + value];
  for (const candidate of candidates) {
    const parsed = parsePhoneNumberFromString(candidate, { defaultCountry: country || 'PE', extract: false });
    if (parsed?.isValid() && parsed.country)
      return { phone: parsed.nationalNumber, phone_country: parsed.country };
  }
  // No adivinar el país ni corregir un teléfono antiguo inválido silenciosamente.
  return { phone: value, phone_country: country || '' };
}
