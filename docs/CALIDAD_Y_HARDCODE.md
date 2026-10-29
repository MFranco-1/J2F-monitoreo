# Calidad y explicación del hardcodeo

Hardcodear significa escribir directamente un valor en el código. No es un error
por sí solo: importa qué representa, por qué está allí y qué ocurre si cambia.

## Tres categorías en J2F

| Categoría | Ejemplo | Tratamiento |
| --- | --- | --- |
| Configuración de un entorno | URL de PostgreSQL, claves, puerto, orígenes CORS, proveedores de rutas | Variables de entorno, fuera del repositorio; validación al iniciar |
| Regla funcional | Combustible <=10 %, recarga simulada a 70 %, permisos de cada perfil | Constantes/políticas con nombre, documentación y pruebas; no números dispersos |
| Datos del negocio | Clientes, vehículos, IMEI registrados, alertas, notas, métricas | PostgreSQL; no arreglos estáticos usados como si fueran registros reales |

Una condición como `usuario.id == 1` para conceder administración sería incorrecta.
J2F consulta el perfil activo y valida su autorización en Flask. El ID usado para
desempatar técnicos con igual carga es un orden estable, no un privilegio.

## Simulación y reglas de HU-11

`frontend/src/app/features/dashboard/fleet-simulation.ts` reúne la configuración
del simulador y funciones puras de geometría. El componente del mapa conserva
la coordinación de Leaflet, selección y servicios. Las coordenadas y fórmulas de
velocidad/consumo son parámetros de simulación, no medidas recibidas de equipos.

HU-11 exige 30 s para las métricas, 10 s para vehículos/eventos, hasta siete
alertas críticas abiertas, umbral de 10 % y recarga simulada a 70 % después de
confirmar. Esos valores no deben eliminarse para aparentar ausencia de hardcodeo.

HU-02 exige un menú de respaldo si no puede consultarse el configurado. Ese
respaldo no sustituye la autorización del backend ni crea pantallas nuevas.

## Decisiones de mantenimiento

- Angular/TypeScript y dependencias Flask actualizados a versiones verificadas.
- Retirados Chart.js y herramientas Karma/Jasmine: no existían usos en las
  pantallas ni un objetivo de pruebas Karma. Se conserva la suite real de Node.
- Animaciones CSS conservadas; no había disparadores Angular que requirieran
  el proveedor de animaciones retirado. Se mantiene detección de cambios con Zone.
- Tipos explícitos para formularios, catálogos y reportes en lugar de datos `any`.
- Consultas por ID con `db.get_or_404`, sin la API de búsqueda obsoleta.
- Notas nuevas en entradas independientes de `history`; el texto legado se
  conserva. El cierre guarda su solución sin sobrescribir notas.
- Reportes descargan el resultado persistido, no recalculan datos al consultar.
  El creador y quien genera un resultado son datos diferentes.
- CSV neutraliza posibles fórmulas del texto de usuario al abrirlo en Excel.
- `.gitignore` protege secretos, logs, respaldos y dependencias, sin ocultar
  indiscriminadamente nuevos archivos útiles de la raíz.

No se han añadido pantallas, roles Cliente ni módulos funcionales nuevos.
Los archivos de pruebas, configuración y mantenimiento no son nuevas funciones
operativas para usuarios.

## Configuración segura

`HOST` y `PORT` controlan `python run.py`; por defecto solo se escucha en
127.0.0.1. No se activa el depurador de forma predeterminada.

En desarrollo, si no se proporcionan claves privadas, se generan claves
aleatorias para ese proceso. Por eso las sesiones requieren volver a entrar
tras un reinicio. Para conservarlas entre reinicios, configurar `SECRET_KEY`
y `JWT_SECRET_KEY` privadas y estables. En producción ambas son obligatorias,
distintas y de al menos 32 caracteres; se rechazan valores de la plantilla.

Ejemplo de generación local, sin copiar el resultado al repositorio:

```powershell
python -c "import secrets; print(secrets.token_urlsafe(48))"
```

`.env.example` documenta variables; no contiene credenciales reales. `python run.py`
no carga automáticamente un archivo `.env`: deben exportarse las variables al
proceso, como muestran los comandos del README.

## Datos heredados y reconciliación

Los códigos internos anteriores pueden conservarse sin cambios al editar un
cliente; no se aceptan nuevos códigos internos ni se finge que son RUC válidos.
Las direcciones reales requieren información correcta. Para registros de prueba,
Mauricio autorizó completar una dirección ficticia; se documenta como tal y se
conserva un respaldo, sin relajar las validaciones ni cambiar otros campos.

`backend/reconcile_fleet_states.py` muestra un plan sin escribir. `--apply`
requiere una decisión explícita, respalda los estados previos en `backend/backups`
y actualiza solo vehículos/GPS incoherentes. Bloquea la desactivación de vehículos
con LOW_FUEL pendiente. No modifica clientes, alertas ni historial y no cambia
el esquema. La revisión del plan y la aplicación son operaciones distintas.

## Comprobaciones reproducibles

```powershell
# Desde backend; las pruebas escriben únicamente en SQLite aislada.
.\venv\Scripts\python.exe -m unittest discover -s tests -v
.\venv\Scripts\python.exe -m pip check
.\venv\Scripts\python.exe -m pip_audit -r requirements.txt --progress-spinner off

# Desde frontend.
npm.cmd ci
npm.cmd test
npm.cmd run build
npm.cmd audit
```

Un auditor sin avisos conocidos no demuestra ausencia total de vulnerabilidades.
No sustituye pruebas de autorización, revisión de configuración ni evaluación de
un despliegue público. No ejecutar `npm audit fix --force` como solución automática.
