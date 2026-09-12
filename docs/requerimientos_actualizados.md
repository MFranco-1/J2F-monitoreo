# Requerimientos actualizados

## Seguridad y compatibilidad

`user_profile` es la fuente de asignaciones multiperfil. `users.profile_id` se conserva como
respaldo y guarda el primer perfil seleccionado. El JWT definitivo identifica un único perfil
activo; nunca combina permisos. En cada solicitud se comprueba cuenta activa, perfil activo y
asignación vigente. El token temporal dura cinco minutos y solo puede llamar a
`POST /api/auth/select-profile`. El historial nuevo conserva opcionalmente el perfil activo.

Un usuario con un perfil entra directamente. Con varios perfiles permanece en `/dashboard`,
sin métricas ni menú, y selecciona desde su cabecera. El cambio emite tokens nuevos, invalida
los anteriores y reconstruye permisos y navegación. El menú usa la API cuando está
configurado y el conjunto fijo solamente ante una base vacía o error de solicitud.

## Historias de usuario y aceptación

### 1. Asignar varios perfiles

Como administrador, deseo asignar uno o varios perfiles activos a un usuario, para controlar
sus distintas responsabilidades.

Dado un usuario editable, cuando marco varios perfiles y guardo, entonces todos quedan en
`user_profile`, sin duplicados, y el primero queda también en `users.profile_id`.

### 2. Ingreso automático

Como usuario con un solo perfil, deseo entrar directamente, para evitar una selección innecesaria.

Dado que poseo exactamente un perfil activo, cuando mis credenciales son válidas, entonces
recibo tokens definitivos y veo el dashboard sin selector ni espacio reservado.

### 3. Seleccionar perfil

Como usuario multiperfil, deseo seleccionar mi perfil desde el dashboard, para iniciar una
sesión con los permisos correctos.

Dado que todavía no elegí perfil, cuando ingreso, entonces permanezco en `/dashboard`, no se
cargan métricas ni menú y veo una indicación discreta junto al selector de cabecera.

### 4. Cambiar perfil activo

Como usuario multiperfil, deseo cambiar mi perfil activo, para alternar de función sin cambiar de cuenta.

Dado un perfil activo, cuando elijo otro perfil asignado, entonces los tokens anteriores se
invalidan, el menú y el dashboard se recargan y sigo en `/dashboard`.

### 5. Restringir permisos

Como responsable de seguridad, deseo autorizar solo el perfil firmado, para evitar la unión de permisos.

Dado un usuario Administrador y Técnico, cuando trabaja como Técnico, entonces los endpoints,
guards, menús y controles administrativos quedan bloqueados.

### 6. Registrar clientes

Como administrador, deseo mantener clientes, para identificar al titular de los vehículos.

Dado un número de documento no registrado, cuando guardo datos válidos, entonces el cliente
queda disponible; un documento repetido se rechaza.

### 7. Registrar vehículos

Como administrador, deseo asociar vehículos a clientes, para contextualizar las alertas.

Dado un cliente existente, cuando registro una placa única, entonces el vehículo queda
relacionado; una placa repetida o cliente inexistente se rechaza.

### 8. Asociar dispositivos GPS

Como administrador, deseo asociar un dispositivo al vehículo correcto, para reconocer el origen.

Dado un vehículo existente, cuando registro IMEI y serie únicos, entonces el dispositivo queda
relacionado; las duplicaciones se rechazan.

### 9. Registrar tipos de evento

Como administrador, deseo mantener tipos de evento, para estandarizar prioridades y atención.

Dado un código único y prioridad válida, cuando guardo el tipo, entonces se registra su
descripción, indicador de alerta, acción esperada y estado.

### 10. Crear una alerta identificada

Como operador, deseo crear una alerta para un cliente y vehículo, para atenderla con contexto.

Dado un cliente activo, cuando selecciono uno de sus vehículos, su dispositivo y un evento
activo, entonces se registra la alerta con relaciones consistentes y prioridad sugerida.

### 11. Consultar alertas

Como operador, deseo ver cliente y vehículo en las alertas, para identificar rápidamente el caso.

Dada una alerta nueva, cuando consulto lista o detalle, entonces veo cliente, placa, equipo,
evento, prioridad, ubicación, estado y fecha; para alertas antiguas veo “No especificado”.

## Alcance y exclusiones

No se integran proveedores GPS reales. No se eliminan tablas, columnas ni datos actuales. No
se añaden perfiles distintos de Administrador y Técnico. Se conservan alertas, asignaciones,
historial, reportes, rutas y diseño existentes, excepto la eliminación solicitada de Acciones rápidas.
