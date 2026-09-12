# Datos maestros y eventos de J2F Monitoreo

## Clasificación de la información

Los datos maestros reutilizables son clientes, vehículos, dispositivos GPS, tipos de evento,
estados, perfiles, opciones de menú y sus permisos. Las prioridades (`critical`, `high`,
`medium`, `low`), tipos de servicio, fuentes y ubicaciones o geocercas se mantienen como
catálogos conceptuales compatibles con los campos actuales; no se añadió una integración
externa ni una tabla innecesaria para ellos.

Los datos transaccionales son los eventos recibidos, alertas, asignaciones, historial y
reportes. En esta fase no se persiste todavía una bandeja independiente de eventos GPS:
se define el catálogo y se relaciona el tipo de evento con la alerta.

## Relación principal

Un cliente posee varios vehículos. Cada vehículo pertenece a un cliente y puede tener uno
o varios registros históricos de dispositivos; cada dispositivo pertenece al vehículo
correspondiente. Un evento originado por un dispositivo puede generar una alerta. La alerta
guarda opcionalmente `vehicle_id`, `gps_device_id` y `event_type_id`; el cliente se obtiene
por `alerts.vehicle_id → vehicles.client_id → clients.id`.

Las relaciones de alertas son opcionales para conservar todos los registros anteriores.
Cuando no existen, la interfaz presenta “No especificado”. No existe borrado en cascada de
alertas o historial desde los maestros. Si un maestro ya está relacionado, se debe cambiar a
Inactivo.

## Evento y alerta

Un evento es un suceso recibido desde un dispositivo, registrado manualmente o producido
por un simulador. Una alerta es el evento que requiere atención, asignación, seguimiento y
cierre. Por esto `generates_alert` puede ser falso.

## Catálogo inicial

| Código | Tipo | Prioridad | Genera alerta | Acción esperada |
|---|---|---:|:---:|---|
| SOS | Botón de pánico o SOS | critical | Sí | Contactar al conductor y escalar según protocolo |
| SPEEDING | Exceso de velocidad | high | Sí | Verificar velocidad y contactar al responsable |
| GEOFENCE_EXIT | Salida de geocerca | high | Sí | Validar ruta y autorización |
| GEOFENCE_ENTRY | Ingreso a geocerca | low | No | Registrar ingreso |
| GPS_SIGNAL_LOSS | Pérdida de señal GPS | high | Sí | Comprobar cobertura y dispositivo |
| POWER_CUT | Corte de alimentación | critical | Sí | Revisar posible manipulación |
| LOW_BATTERY | Batería baja | medium | Sí | Programar revisión |
| DEVICE_TAMPER | Manipulación o desconexión | critical | Sí | Escalar y validar físicamente |
| UNAUTHORIZED_MOVEMENT | Movimiento no autorizado | critical | Sí | Activar protocolo de seguridad |
| OUT_OF_HOURS_IGNITION | Encendido fuera de horario | high | Sí | Confirmar autorización |
| PROLONGED_STOP | Inactividad prolongada | medium | No | Revisar operación |
| COMMUNICATION_FAILURE | Falla de comunicación | high | Sí | Revisar red, SIM y proveedor |

El script [005_seed_event_types.sql](../migrations/005_seed_event_types.sql) registra el
catálogo sin duplicar códigos.

## Flujo de una alerta

El operador elige un cliente activo, luego un vehículo activo de ese cliente, un dispositivo
activo del vehículo y un tipo de evento activo. La prioridad sugerida se completa desde el
tipo de evento y puede continuar utilizando los valores vigentes. El servidor vuelve a
validar toda la cadena y admite solicitudes antiguas que no envían ninguna relación.
