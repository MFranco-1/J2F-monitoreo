const HISTORY_ACTION_LABELS: Readonly<Record<string, string>> = {
  created: ' Creada',
  state_changed: ' Estado cambiado',
  assigned: ' Asignada',
  escalated: ' Escalada',
  closed: ' Cerrada',
  cancelled: ' Anulada',
  updated: ' Actualizada',
  reassigned: ' Reasignada',
  fuel_coordinated: ' Coordinación de abastecimiento',
  fuel_confirmed: ' Abastecimiento confirmado',
};

/**
 * Comparte las etiquetas sin unificar el texto de las notas de cada pantalla.
 * Conserva los espacios iniciales y devuelve el código original si no tiene etiqueta.
 */
export function getHistoryActionLabel(action: string, noteLabel = ' Nota'): string {
  if (action === 'note_added') return noteLabel;
  return HISTORY_ACTION_LABELS[action] ?? action;
}
