# Alcance y verificación de J2F

Base funcional: HU-01 a HU-12 del tablero `PA_III_EQUIPO 5 / SECCION : B`,
exportado por el equipo el 28/10/2026. HU-13 corresponde a la ampliación de notas
solicitada y acordada con Mauricio. Este archivo no modifica el tablero de Trello.

## Trazabilidad

| Historia | Alcance que se conserva | Evidencia automatizada principal |
| --- | --- | --- |
| HU-01 | Inicio por DNI/correo, perfil único/múltiple, cambio y salida | `test_regressions.py`, `auth.test.mjs` |
| HU-02 | Perfil activo del JWT, rutas protegidas, menú configurado y respaldo | `test_regressions.py`, `auth.test.mjs` |
| HU-03 | Usuarios, validación, duplicados, perfiles y bajas protegidas | `test_validation.py`, `test_regressions.py`, `validation.test.mjs` |
| HU-04 | CRUD de perfiles/menús, grupos sin ruta, jerarquía y protección del último administrador | `test_regressions.py`, `auth.test.mjs` |
| HU-05 | Clientes, teléfonos internacionales, vehículos, GPS, relaciones y estados | `test_client_formats.py`, `test_client_registration.py`, `test_operational_observations.py`, `test_fleet_gps.py`, `test_fleet_reconciliation.py` |
| HU-06 | Tipos de evento y prioridades; cuatro códigos operativos protegidos | `test_validation.py`, `test_regressions.py`, `async-behavior.test.mjs` |
| HU-07 | Título/descripción válidos, relaciones coherentes y combustible con vehículo | `test_operational_observations.py`, `test_regressions.py`, `validation.test.mjs` |
| HU-08 | Técnico habilitado, carga consultada, asignación automática/manual y reasignación | `test_regressions.py`, `test_operational_observations.py`, `async-behavior.test.mjs` |
| HU-09 | Consulta por alcance, historial y anulación sin borrado | `test_alert_cancellation.py`, `test_regressions.py`, `async-behavior.test.mjs` |
| HU-10 | Atención vigente, solución obligatoria, coordinación/confirmación y cierre conjunto | `test_regressions.py`, `test_validation.py`, `fuel-flow.test.mjs` |
| HU-11 | Métricas reales y mapa Leaflet con telemetría local simulada | `test_regressions.py`, `fuel-flow.test.mjs`, `async-behavior.test.mjs` |
| HU-12 | Reportes filtrados, autor/fecha de generación y descarga CSV/JSON | `test_report_exports.py`, `test_regressions.py`, `async-behavior.test.mjs` |
| HU-13 | Varias notas inmutables, autor/perfil/fecha, separación y continuidad al reasignar | `test_assignment_notes.py`, `async-behavior.test.mjs` |

Las pruebas no equivalen a una aceptación formal del profesor ni cubren todas
las combinaciones posibles. Las pruebas que escriben registros usan SQLite
aislada, nunca Neon. Los scripts de mantenimiento de Neon son operaciones
explícitas, no pruebas ni tareas automáticas de arranque.

## HU-13: registro y consulta de notas del caso

**Actores:** Técnico asignado, Supervisor y Administrador.

**Como** integrante autorizado del equipo, **deseo** añadir observaciones propias
y consultar las anteriores, **para** mantener la continuidad de la atención sin
alterar lo escrito por otros.

- **Dado** un caso pendiente con asignación vigente, **cuando** su Técnico añade
  una nota válida, **entonces** se registra una entrada técnica independiente.
- **Dado** un Supervisor o Administrador, **cuando** añade una observación a ese
  caso, **entonces** se registra como una nota propia de Supervisión/Administración.
- **Dado** una nota nueva, **cuando** se consulta, **entonces** muestra autor,
  perfil y fecha/hora registrados por el servidor; la pantalla utiliza hora de Perú.
- **Dado** notas anteriores, **cuando** se añade una corrección, **entonces** se
  conserva todo lo anterior y la corrección se añade como otra nota. No hay edición ni borrado.
- **Dado** una reasignación, **cuando** entra el nuevo Técnico, **entonces** puede
  leer las notas del anterior y las de Supervisión/Administración.
- **Dado** un Técnico anterior o ajeno, **cuando** intenta escribir, **entonces**
  se rechaza; el anterior conserva únicamente su consulta autorizada.
- **Dado** texto vacío, solo espacios/signos, menor de 5 o mayor de 2000
  caracteres, **cuando** intenta guardar, **entonces** se rechaza con explicación.
- **Dado** un caso cerrado o anulado, **cuando** consulta sus notas, **entonces**
  solo puede leerlas y no añadir otras.
- **Dado** un Supervisor que puede añadir notas, **cuando** intenta cambiar
  estados, coordinar/confirmar formalmente combustible o cerrar, **entonces**
  sigue sin tener esos permisos.
- **Dado** un texto heredado sin autor/fecha acreditados, **cuando** se consulta,
  **entonces** se conserva como registro anterior sin inventar esos datos.

HU-13 amplía HU-10 y sustituye únicamente su restricción anterior sobre las
notas del Supervisor. No modifica las reglas de atención, combustible o cierre.

## Recorrido de aceptación manual

1. Entrar con perfil único y con cuenta multiperfil. Antes de seleccionar perfil,
   comprobar que no se cargan métricas ni menú operativo. Probar cambio y salida.
2. Administrador: crear/editar usuarios, perfiles y grupos/opciones de menú;
   comprobar validaciones, duplicados y restricciones de bajas.
3. Datos maestros: cliente válido, teléfono internacional, vehículo y GPS
   relacionado. Probar errores de documento, teléfono y relaciones.
4. Crear una alerta con descripción; intentar guardar otra con solo título.
5. Asignar un Técnico, comprobar su carga y registrar notas de Técnico y Supervisor.
6. Reasignar a otro Técnico; comprobar las notas anteriores, recargar y consultar
   nuevamente. Intentar escribir desde la asignación anterior.
7. Cerrar un caso general con solución. Comprobar historial y notas de solo lectura.
8. Combustible: generar <=10 %, asignar, consultar estaciones/ruta o registrar
   coordinación manual ante fallo, confirmar con observación y comprobar cierre.
9. Anular otro caso con Administrador/Supervisor. Verificar motivo, historial y
   rechazo para Operador/Técnico. No contar la anulación como solución.
10. Generar cada reporte, consultar autor/fecha/filtros y descargar CSV/JSON.
    Verificar que reasignaciones y anulaciones no se cuenten como resueltas.

## Límites que deben explicarse

- El mapa y el combustible son simulación local; no existe recepción de GPS físicos.
- Un documento/teléfono con formato válido no acredita titularidad ni existencia.
- La disponibilidad de OpenStreetMap, OSRM y Overpass es externa; el fallo debe
  mostrarse sin inventar estaciones o rutas.
- La cuenta de conexión actual de Neon es propietaria de tablas. Para publicar
  debe configurarse una cuenta de aplicación de privilegios mínimos, claves
  privadas estables, HTTPS y un servidor de producción.
- Las imágenes enlazadas de REQ 1–3 del tablero no forman parte de la comparación
  textual de las historias consolidada en este documento.

## Resultado de la revisión del 28/10/2026

- Backend: 138 pruebas aprobadas con `unittest discover`; todas las escrituras
  de pruebas se ejecutaron en SQLite aislada.
- Frontend: 83 pruebas aprobadas con `npm test`. Instalación limpia `npm ci`
  y compilación de producción `npm run build` completadas.
- Dependencias: `pip check` sin conflictos; `pip-audit -r requirements.txt`
  y `npm audit` sin vulnerabilidades conocidas en la consulta realizada.
- Chrome: inicio correcto/incorrecto, selección Leaflet, navegación a detalle,
  notas de varios autores, Supervisor sin cierre, reasignación, recarga,
  notas de solo lectura después del cierre, alcance del Técnico/Operador,
  coordinación manual persistida, confirmación y rechazo de duplicados,
  anulación y descargas reales de CSV/JSON. Sin excepciones JavaScript
  durante ese recorrido. Se inspeccionaron capturas de mapa, notas y reportes.
- Ese recorrido de navegador utilizó un backend SQLite aislado. Sus rutas
  visuales fueron respuestas de prueba controladas; no acredita disponibilidad
  externa ni recepción de GPS físicos. La consulta fallida de estaciones se
  provocó para verificar el mensaje y la alternativa manual.
- Una comprobación pública separada obtuvo una ruta real de OSRM (HTTP 200);
  Overpass agotó el tiempo de espera. Su disponibilidad futura no está garantizada.
- Neon: inspección en transacción de solo lectura; 14 tablas y columnas
  requeridas presentes, conexión TLS 1.3. Cero LOW_FUEL pendientes sin vehículo,
  casos con asignaciones vigentes duplicadas, asignaciones vigentes en casos
  terminados y alertas con GPS de otro vehículo en las consultas realizadas.

### Datos heredados y pendientes de despliegue

La inspección encontró el vehículo **48** y los GPS **1 y 12** activos con
padres inactivos. Inicialmente la revisión automática de permisos rechazó
modificarlos sin autorización específica. Tras la autorización de Mauricio,
se aplicó `reconcile_fleet_states.py --apply`: los tres quedaron Inactivos,
sin borrar registros ni modificar alertas o historial. Se comprobó previamente
que no había LOW_FUEL pendiente que bloqueara la operación.

El respaldo de sus estados anteriores quedó en
`backend/backups/fleet-states-20261029T022558131316Z.json`, excluido de Git.
Una consulta posterior de solo lectura confirmó los tres estados y **cero
vehículos/GPS activos con padres inactivos** según el plan de reconciliación.
Las dos pruebas específicas del mantenimiento se ejecutaron nuevamente en
SQLite y aprobaron. Los servidores continuaron accesibles: frontend HTTP 200
y API HTTP 401 sin sesión, como corresponde a una ruta protegida.

El cliente **1 (Transportes Andinos)** tenía solamente **Lima** en dirección.
Mauricio confirmó que se trata de datos de prueba y autorizó una dirección
ficticia: **Av. Los Transportistas 456, Ate, Lima**. Se guardó y verificó con
la validación vigente, sin cambiar los demás campos del cliente. El valor
anterior quedó respaldado en
`backend/backups/client-address-20261029T022829774672Z.json`, excluido de Git.
Esta dirección es un dato de prueba y no una ubicación verificada de la empresa.
Los tres documentos antiguos de tipo `Código interno`
se conservan como tales, no como RUC; no se les asignaron documentos inventados.

La cuenta propietaria de Neon y la configuración para exposición pública siguen
siendo decisiones de despliegue. La revisión y los auditores no son una garantía
de seguridad absoluta ni una comprobación manual de cada combinación posible.
