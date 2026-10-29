# J2F — Centro de Monitoreo

Aplicación Angular 22 + Flask + SQLAlchemy + JWT para monitoreo, preparada para
usuarios multiperfil, menú dinámico y maestros de clientes, vehículos, dispositivos
GPS y tipos de evento.

Requiere Node compatible con Angular 22: `^22.22.3`, `^24.15.0` o `>=26`;
se verificó con Node 24.19.0. Mantener `package-lock.json` y usar `npm ci`.
La interfaz y los flujos se conservan; no se introduce otro framework.

Consultar [trazabilidad de historias](docs/HISTORIAS_Y_VERIFICACION.md) y
[calidad y explicación del hardcodeo](docs/CALIDAD_Y_HARDCODE.md).

## Migración segura de PostgreSQL / Neon

El código no ejecuta migraciones al arrancar. Antes de desplegarlo, crea un respaldo
de Neon y revisa `j2f_modulo_usuarios.sql` y las migraciones incrementales de
`backend/migrations`. Los scripts no usan `DROP` ni `TRUNCATE` y conservan
`users.profile_id`, las alertas y los demás datos actuales.

Para aplicar todo desde un único archivo del proyecto:

```powershell
$env:DATABASE_URL = '<URL_PRIVADA_DE_NEON>'
psql "$env:DATABASE_URL" -v ON_ERROR_STOP=1 -f j2f_modulo_usuarios.sql
```

El mismo archivo incorpora tres clientes, cuatro vehículos por cliente y dieciocho
alertas iniciales identificables mediante la fuente `Carga inicial J2F`. Ejecutarlo
nuevamente no duplica esos registros.

Después, `backend/init_db.py` valida en modo de solo lectura las 14 tablas y sus
columnas. No crea, altera ni borra datos.

## Backend

```powershell
cd backend
python -m venv venv
.\venv\Scripts\Activate.ps1
python -m pip install -r requirements.txt
$env:DATABASE_URL = '<URL_PRIVADA_DE_NEON>'
python init_db.py
python run.py
```

La API queda en `http://localhost:5000/api`. Un usuario con un perfil activo entra
directamente. Con varios perfiles recibe un token temporal restringido, permanece en
`/dashboard` y elige su perfil allí. El JWT definitivo lleva el único perfil activo.

## Frontend

```powershell
cd frontend
npm ci
npm start
```

Abrir `http://localhost:4200`. Las rutas de usuarios, perfiles y menús requieren el
perfil activo Administrador. En Datos maestros, Administrador conserva el CRUD;
Operador y Supervisor consultan el catálogo operativo, y Técnico solo los registros
vinculados a sus alertas autorizadas y los catálogos necesarios.

En desarrollo las claves de sesión no configuradas se generan aleatoriamente;
será necesario volver a iniciar sesión al reiniciar. Para sesiones estables entre
reinicios, exportar claves privadas `SECRET_KEY` y `JWT_SECRET_KEY` de al menos
32 caracteres. Producción exige ambas y rechaza las claves de la plantilla.
`HOST` y `PORT` configuran `python run.py`; el host predeterminado es 127.0.0.1.

La pantalla de Datos maestros utiliza `/master-data`: los perfiles con esa opción
asignada pueden consultarla, mientras que solo Administrador puede modificarla.

La pantalla de alertas muestra todo por defecto. El filtro de cliente carga sus
vehículos y limita las alertas; el filtro de vehículo limita el resultado a esa unidad.
Seleccionar `Todos los clientes` restaura la consulta general.

El Supervisor y el Operador revisan las alertas y las asignan o reasignan a los
Técnicos, de forma manual o automática. El Técnico atiende únicamente sus alertas
asignadas, registra notas y cambia su estado. El Administrador conserva esas
capacidades para casos excepcionales.

## Pruebas

```powershell
cd backend
python -m unittest discover -s tests -v

cd ..\frontend
npm test
npm run build
```

Las pruebas de backend usan SQLite aislada y no acceden a Neon.

## Validación de formularios

Los formularios comprueban los datos antes de enviarlos y Flask vuelve a validarlos
al crear o editar. No basta con completar un campo con una letra o símbolos.

- Clientes: RUC de 11 dígitos con prefijo y dígito verificador válidos, DNI de 8, CE de 9 a 12 y pasaporte alfanumérico de
  6 a 12; razón social de al menos 3 caracteres y con letras. No se obliga a usar
  el sufijo S.A.C. Teléfono nacional validado según el país seleccionado y guardado
  en formato internacional; no se admiten letras ni símbolos en el número nacional;
  correo con formato válido, contacto con letras y dirección de al menos 5 caracteres.
- Vehículos y GPS: placa alfanumérica de 4 a 8 caracteres con guion opcional,
  IMEI de 15 dígitos, SIM numérica de 7 a 22 y relaciones existentes.
- Usuarios: DNI, correo, nombre, perfiles y estado válidos; nuevas contraseñas de
  8 a 128 caracteres. La contraseña vacía al editar conserva la anterior.
- Perfiles, menús, eventos, alertas y reportes: nombres/títulos de al menos 3
  caracteres, límites de longitud, códigos, rutas internas, prioridades y fechas
  válidos. Las observaciones, soluciones y descripciones ingresadas requieren
  al menos 5 caracteres con contenido, no una letra aislada.

Los campos opcionales pueden quedar vacíos. Se conservan los registros antiguos;
las actualizaciones parciales validan los campos enviados (el tipo y número de
documento se validan juntos). El formulario de edición solicita corregir sus
campos inválidos antes de guardar. No hay borrados ni correcciones automáticas de datos antiguos.

Las reglas de formato no acreditan la existencia del titular, correo, teléfono,
placa o dispositivo. No hay consultas a SUNAT/RENIEC ni conexión automática a
equipos GPS: la razón social y demás datos se ingresan manualmente.

## Registro de clientes sin servicios externos

Antes de iniciar esta versión sobre una base existente, aplica únicamente
`backend/migrations/20261003_client_verification.sql`. Añade una columna nullable
en `clients`; conserva los datos. `j2f_modulo_usuarios.sql` también la incorpora
para instalaciones nuevas. No ejecutar pruebas ni reinicializaciones en Neon.

```powershell
psql "$env:DATABASE_URL" -v ON_ERROR_STOP=1 -f backend/migrations/20261003_client_verification.sql
```

El Administrador registra y edita clientes manualmente. Se retiraron el botón de
consulta RUC, su endpoint, comprobantes y configuración del proveedor. No se necesita
token, consulta previa ni observación adicional para guardar. Angular y Flask
mantienen validación de documento, razón social, contacto, teléfono, correo y dirección.
Los demás perfiles conservan sus permisos de consulta.

La columna de verificación de la versión anterior se conserva únicamente por
compatibilidad y para no borrar información existente. No se ejecutan cambios de
esquema ni de datos al retirar la API. Si un registro ya tenía historial y cambia
su RUC/razón social, se conserva el historial y se invalida la verificación anterior;
una edición manual nunca queda marcada como consulta externa exitosa. La validación
local de RUC comprueba formato/control, no acredita inscripción ni razón social.

## Formato de clientes y teléfonos internacionales

Al crear o editar, Angular y Flask guardan razón social y persona de contacto con
primera letra mayúscula y el resto en minúscula, normalizando espacios (por ejemplo,
`Transportes andinos s.a.c.`). No se permite usar solo `S.A.C.` como razón social.
No se cambia en bloque ningún nombre ni registro histórico.

La dirección admite letras (incluidas tildes y ñ), números ASCII, espacios y
`. , - / #`. Otros símbolos, controles y saltos de línea se rechazan, no se borran
silenciosamente. Esta regla es de calidad de datos, no sustituye autorización,
consultas parametrizadas ni escape de salida.

Teléfono mantiene su carácter opcional. El formulario separa país/prefijo y número
nacional con código de área, y valida el plan telefónico de cada país usando
`libphonenumber-js/max`; Flask vuelve a comprobarlo con `phonenumbers`.
Se guarda en la columna existente `phone` en formato internacional (`+51987654321`);
`phone_country` es un campo de API derivado del número, no una columna nueva.
Los números antiguos siguen consultables y se separan al editar si son interpretables.
Los datos heredados inválidos deben corregirse si se envían en una edición; cambiar
solo el estado no reescribe ni valida de nuevo los campos no enviados.

No hay API externa, SMS ni verificación de titularidad: un formato válido no prueba
que el número exista o pertenezca al cliente. Instalar las dependencias actualizadas
con `pip install -r backend/requirements.txt` en el entorno virtual y `npm ci`
desde `frontend`. No se necesita una migración de base de datos para estos cambios.

## Identificación de GPS

GPS vacío significa que no existen equipos registrados dentro del alcance del
perfil. Los vehículos y las posiciones simuladas del mapa no crean un equipo físico.
En Vehículos se muestran IMEI y estado de los equipos vinculados, o Sin GPS registrado;
Registrar GPS abre el formulario existente con el vehículo preseleccionado. El
Administrador registra IMEI de 15 dígitos único y los datos disponibles del equipo,
su SIM/proveedor y estado. El mapa muestra el IMEI activo elegido para esa unidad.

Para los vehículos sin hardware, se autorizó poblar registros GPS con identificadores
generados. `backend/register_fleet_gps.py` muestra el plan y `--apply` lo aplica en
una transacción. Solo añade un GPS a cada vehículo activo sin equipo registrado;
no sustituye GPS existentes, ni crea SIM/proveedor, ni modifica alertas o vehículos.
Es idempotente. Usa serie `GPS-<placa>` y números de 15 dígitos con prefijo `00` y
control Luhn: son identificadores sintéticos, no IMEI asignados por un fabricante.
Los nombres visibles son neutros; no se etiquetan como demo en la pantalla.

Registrar un IMEI solo identifica el dispositivo: para telemetría real se necesita
el equipo instalado, configuración de transmisión y un receptor/proveedor compatible,
que esta aplicación aún no incorpora. El mapa sigue identificando posiciones como
simuladas locales del navegador. El Técnico solo consulta unidades/equipos asociados
a sus casos autorizados y no puede registrar ni editar GPS.

## Anulación de alertas

Aplicar `backend/migrations/20261003_cancel_alerts.sql` en bases existentes.
Solo añade el estado `Anulado` si falta; no altera alertas ni crea tablas.

Administrador y Supervisor, según el perfil activo del JWT, pueden anular un caso
pendiente desde su detalle con un motivo obligatorio de 5 a 1000 caracteres.
Operador, Técnico y perfiles nuevos distintos no tienen ese permiso, aunque se
les dé acceso al menú. Un usuario nuevo con perfil Supervisor sí conserva las
facultades de ese rol. No se permite anular alertas cerradas ni repetir la anulación.

El historial conserva autor, perfil, fecha, motivo y estado anterior. Se finalizan
las asignaciones pendientes sin tiempo de resolución, y el caso deja de aparecer
como abierto en el mapa. El historial y los reportes distinguen anulación de cierre;
el rendimiento cuenta las atenciones anuladas por separado. No se borran alertas.

Anular combustible no confirma un abastecimiento ni aumenta el nivel simulado.
Si termina un caso con combustible todavía bajo, esa simulación local no lo recrea
automáticamente hasta recuperar un nivel superior a 10 %; generar otro evento de
combustible de forma explícita sigue disponible. Los recorridos de abastecimiento
interrumpidos quedan detenidos en su última posición local con retorno recuperable.
La telemetría local no es compartida entre navegadores.

## Desactivación de flota y mínimos de alertas

Guardar un cliente como Inactivo desactiva también sus vehículos y GPS en la
misma transacción. Si una unidad tiene un caso LOW_FUEL pendiente, se bloquea
toda la operación hasta completar el abastecimiento o anular el caso con motivo;
no se dejan estados parciales. Desactivar un vehículo desactiva sus GPS.
Reactivar el cliente o vehículo no reactiva automáticamente sus descendientes.
No se puede activar una unidad con su cliente inactivo, ni un GPS con su vehículo
o cliente inactivo. Los catálogos activos y el mapa omiten también las unidades
heredadas cuyo cliente está inactivo, sin borrar datos ni historial.

Crear una alerta manual requiere título y descripción con contenido válido
(descripción de 5 a 2000 caracteres). No basta un título. Tampoco se permite
vaciar la descripción mediante una edición. Los casos antiguos sin descripción
siguen consultables y pueden atenderse o anularse sin una reescritura masiva.
Los eventos automáticos del mapa conservan sus descripciones generadas.

La carga del selector de técnicos se consulta al abrir la asignación, después
de asignar o reasignar y cada cinco segundos mientras la ventana permanezca abierta.
El polling termina al salir de la pantalla; cambiar de perfil descarta consultas
anteriores. No se calculan cargas sumando contadores locales.

Tras actualizar archivos, reiniciar un backend sin recarga automática: una
versión anterior en memoria puede devolver 404 para la ruta de anulación aunque
el código y la migración actuales estén instalados. Esto no se soluciona ampliando
los permisos; la anulación sigue reservada al perfil activo Administrador o Supervisor.

## Notas del caso y reasignaciones

En Asignaciones, **Notas del caso** consulta las notas de toda la alerta, incluidas
las de asignaciones anteriores. Se muestran por separado las notas técnicas,
las de Supervisión/Administración y las indicaciones iniciales de asignación.
Cada nota nueva conserva el usuario, perfil activo y fecha/hora registrados por
Flask; la pantalla muestra la hora de Perú (UTC−5).

El Técnico vigente añade notas técnicas. Supervisor y Administrador añaden sus
propias observaciones, sin obtener por ello permisos de cierre adicionales.
Operador conserva consulta e indicaciones al asignar, pero no añade notas de
atención. El nuevo Técnico puede leer las notas anteriores del caso; una
asignación anterior, cerrada o anulada queda en consulta de solo lectura.
Se mantienen los alcances operativos existentes de cada perfil.

Las notas son entradas independientes e inmutables: no hay edición ni borrado;
una corrección se registra con otra nota. Se pueden añadir varias sin reemplazar
las anteriores y usar **Actualizar notas** para consultar aportes de otros usuarios.
El cierre guarda su solución en el historial sin reemplazar las notas.

No se añaden tablas, columnas ni migraciones: se utiliza `history` con acción
`note_added` y detalle estructurado. `GET /api/assignments/<id>/notes` devuelve
las notas autorizadas del caso y los textos heredados; `POST` en esa ruta añade
una nota a la asignación vigente. El `PUT` anterior con `notes` sigue aceptándose,
pero ahora añade una entrada, no reemplaza un campo. Autor, perfil y fecha no se
aceptan del cliente. El texto requiere entre 5 y 2000 caracteres con contenido.

Los valores antiguos de `assignments.notes` y sus auditorías se conservan sin
reescribirlos. Se muestran como registros anteriores: no se atribuye un texto
heredado al Técnico ni se usa la fecha de asignación como fecha de su creación.

## Reportes y exportaciones (HU-12)

Los resultados conservan filtros, período, fecha de generación y autor real de
esa generación. El usuario que crea el reporte puede ser diferente de quien
lo genera. Los resultados antiguos no reciben una atribución inventada.

Administrador y Supervisor pueden consultar/generar y descargar CSV o JSON
desde el resultado existente. `GET /api/reports/<id>/export?format=csv|json`
descarga el resultado almacenado sin regenerarlo ni modificar registros.
Las etiquetas de prioridad se muestran en español; reasignaciones y anulaciones
se distinguen de resoluciones. La exportación CSV protege los textos que una
hoja de cálculo podría interpretar como fórmulas.

## Reversión

La reversión no debe borrar las tablas nuevas: vuelve a la versión anterior del código
y conserva columnas y registros compatibles. Antes de una eliminación posterior se
deben auditar dependencias y respaldar asignaciones multiperfil e historial. Nunca se
versionan `.env`, contraseñas, URLs privadas ni tokens.
