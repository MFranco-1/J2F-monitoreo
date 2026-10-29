# J2F Monitoreo

Aplicación web para gestionar incidentes de una flota vehicular. Permite registrar
alertas, asignar técnicos, documentar la atención y consultar su historial y
reportes desde un panel de monitoreo.

El sistema utiliza una base PostgreSQL compartida. Las posiciones, velocidades y
niveles de combustible del mapa son simulados en cada navegador; las alertas,
asignaciones, notas y confirmaciones se guardan en la base de datos.

## Funcionalidades

- Autenticación por DNI o correo y selección del perfil activo en cuentas multiperfil.
- Usuarios, perfiles y menú lateral configurable.
- Catálogos de clientes, vehículos, dispositivos GPS y tipos de evento.
- Alertas con prioridades, estados, filtros e historial.
- Asignación manual o automática según la carga de los técnicos.
- Notas independientes con autor, perfil y fecha, conservadas al reasignar el caso.
- Mapa Leaflet integrado en el dashboard, filtrado por cliente y permisos.
- Abastecimiento documentado: alerta de combustible, asignación, coordinación,
  confirmación y cierre.
- Reportes de alertas, rendimiento y tiempos de atención, con exportación CSV/JSON.

## Tecnologías

| Capa | Herramientas |
| --- | --- |
| Frontend | Angular 22, TypeScript 6, SCSS, RxJS |
| Backend | Python 3.12, Flask 3, SQLAlchemy |
| Base de datos | PostgreSQL; conexión local o alojada en Neon |
| Autenticación | JWT con autorización por perfil activo |
| Mapa | Leaflet, teselas OpenStreetMap, rutas OSRM y estaciones Overpass |
| Pruebas | unittest con SQLite aislada y pruebas de frontend con Node.js |
| Calidad | Ruff, Prettier y comprobación estricta de TypeScript |

## Estructura

```text
backend/
  app/
    controllers/         Reglas de negocio
    models/              Entidades y relaciones de SQLAlchemy
    views/               Rutas HTTP y permisos
    config.py            Configuración por entorno
    security.py          Autorización y alcance de consultas
    testing_fixtures.py  Datos exclusivos de las pruebas SQLite
    validation.py        Validaciones del backend
  migrations/            Cambios incrementales de PostgreSQL
  tests/                 Pruebas de comportamiento y regresión
  init_db.py             Verificación de la estructura existente, de solo lectura
  run.py                 Arranque del servidor de desarrollo
frontend/
  src/app/
    core/                Servicios, guards e interceptor de autenticación
    features/            Pantallas organizadas por funcionalidad
    layout/              Estructura y navegación
    shared/              Modelos y validaciones compartidas
  tests/                 Pruebas de frontend
.env.example             Plantilla de configuración sin credenciales
j2f_modulo_usuarios.sql   Migración consolidada para la base existente de J2F
```

## Requisitos

- Python 3.12 y pip.
- Node.js compatible con Angular 22: `^22.22.3`, `^24.15.0` o `>=26`.
- npm 10 o superior.
- Acceso a una base PostgreSQL de J2F con su esquema base y usuarios configurados.
- Conexión a Internet para teselas, rutas y consulta de estaciones.

Las versiones de las dependencias se fijan en los archivos de requisitos y en
`frontend/package-lock.json`.

## Instalación local

### 1. Obtener el código

```powershell
git clone https://github.com/MFranco-1/J2F-monitoreo.git
cd J2F-monitoreo
```

### 2. Configurar PostgreSQL

Usar una base local o las credenciales de la base compartida de Neon. Cada equipo
debe configurar su conexión de forma privada. Git comparte código, no sincroniza
una base local con Neon.

`j2f_modulo_usuarios.sql` es una migración incremental: requiere las tablas del
esquema original, como `states`, `users` y `profiles`. No es un volcado completo
para iniciar una base vacía. Una instalación independiente necesita provisionar
ese esquema y una cuenta administradora antes de utilizar la aplicación.

En una base existente, revisar los cambios y disponer de un respaldo antes de
aplicar una migración pendiente:

```powershell
$env:DATABASE_URL = '<URL_PRIVADA_POSTGRESQL>'
psql "$env:DATABASE_URL" -v ON_ERROR_STOP=1 -f j2f_modulo_usuarios.sql
```

El script consolidado incorpora las ampliaciones de `backend/migrations` y datos
iniciales de flota identificados con la fuente `Carga inicial J2F`. No se ejecuta
automáticamente al arrancar. Las pruebas no deben ejecutarse contra Neon.

### 3. Iniciar el backend

Desde la raíz del repositorio:

```powershell
cd backend
python -m venv venv
.\venv\Scripts\Activate.ps1
python -m pip install -r requirements.txt

$env:DATABASE_URL = '<URL_PRIVADA_POSTGRESQL>'
$env:SECRET_KEY = python -c "import secrets; print(secrets.token_urlsafe(48))"
$env:JWT_SECRET_KEY = python -c "import secrets; print(secrets.token_urlsafe(48))"
$env:CORS_ORIGINS = 'http://localhost:4200,http://127.0.0.1:4200'

python init_db.py
python run.py
```

La API escucha en `http://localhost:5000/api`. `init_db.py` comprueba las 14 tablas
y sus columnas requeridas sin alterar datos. `run.py` repite esa verificación
antes de iniciar Flask. La raíz `/` no contiene una página de inicio.

### 4. Iniciar el frontend

En otra terminal, desde la raíz del repositorio:

```powershell
cd frontend
npm ci
npm start
```

Abrir `http://localhost:4200` e ingresar con una cuenta existente. No se publican
credenciales de acceso a la base compartida ni contraseñas de usuarios.

### Variables de entorno

`.env.example` describe las variables disponibles. El backend lee el entorno del
proceso; no carga automáticamente un archivo `.env`.

| Variable | Uso |
| --- | --- |
| `DATABASE_URL` | URL PostgreSQL, con TLS cuando corresponda |
| `SECRET_KEY` | Clave privada de Flask |
| `JWT_SECRET_KEY` | Clave privada para firmar tokens |
| `FLASK_ENV` | `development`, `testing` o `production` |
| `HOST` / `PORT` | Dirección y puerto de Flask; por defecto `127.0.0.1:5000` |
| `CORS_ORIGINS` | Orígenes HTTP/HTTPS permitidos, separados por comas |
| `OVERPASS_API_URL` | Servicio para consultar estaciones |
| `ROUTING_API_URL` | Servicio de rutas viales compatible con OSRM |
| `MAP_SERVICE_TIMEOUT` | Tiempo de espera de los servicios del mapa, en segundos |

Como alternativa a `DATABASE_URL`, se admiten `PGHOST`, `PGPORT`, `PGDATABASE`,
`PGUSER` y `PGPASSWORD`.

En desarrollo se generan claves aleatorias si no se configuraron; al reiniciar,
esas sesiones dejan de ser válidas. Para conservar sesiones entre reinicios,
mantener las claves en una configuración privada estable. Producción exige claves
diferentes de al menos 32 caracteres y una `DATABASE_URL` explícita.

## Roles y permisos

La autorización se aplica en Flask y se refleja en Angular. El acceso al menú
no concede permisos sobre los endpoints.

| Acción | Administrador | Supervisor | Operador | Técnico |
| --- | --- | --- | --- | --- |
| Administrar usuarios, perfiles, menú y catálogos | Sí | No | No | No |
| Consultar datos operativos | Sí | Sí | Sí | Casos autorizados |
| Crear alertas y generar eventos del mapa | Sí | Sí | Sí | No |
| Asignar y reasignar | Sí | Sí | Sí | No |
| Añadir notas de atención | Sí | Sí | No | Asignación vigente |
| Atender, coordinar combustible y cerrar | Sí | No | No | Asignación vigente |
| Anular alertas con motivo | Sí | Sí | No | No |
| Consultar, generar y exportar reportes | Sí | Sí | No | No |
| Eliminar reportes | Sí | No | No | No |

El Operador puede registrar indicaciones al asignar. Las notas de atención se
separan entre Técnico y Supervisión/Administración. Ninguna nota se edita ni se
elimina: una corrección se añade como otra entrada.

## Reglas de operación

- Las alertas manuales requieren título y descripción con contenido válido.
  LOW_FUEL exige cliente y vehículo relacionados.
- Cada alerta tiene como máximo una asignación vigente. Una reasignación conserva
  el historial y no se cuenta como atención resuelta.
- El cierre exige solución y completa también la asignación. La anulación requiere
  motivo, conserva los antecedentes y se distingue del cierre en los reportes.
- Desactivar un cliente desactiva sus vehículos y GPS en la misma transacción.
  Un caso LOW_FUEL pendiente bloquea esa baja. La reactivación de los padres
  no reactiva automáticamente sus descendientes.
- El backend valida documentos, relaciones, duplicados, textos, fechas y teléfonos.
  El RUC se comprueba por estructura y dígito de control, sin consulta a SUNAT.
- Los teléfonos se validan según el país y se guardan en formato internacional.
  La validación de formato no acredita existencia ni titularidad.

### Mapa y combustible

El mapa consulta vehículos y eventos autorizados cada 10 segundos; el dashboard
actualiza métricas cada 30 segundos. Las posiciones son simulaciones locales y
no representan una ubicación GPS compartida entre navegadores.

Una alerta LOW_FUEL se genera con combustible simulado de 10 % o menos. El
Técnico asignado o Administrador registra la coordinación y confirma el
abastecimiento con una observación obligatoria. Esa confirmación se conserva en
el historial y actualiza el nivel simulado al 70 %. No depende de terminar una
animación. Anular o cerrar un caso por otra vía no demuestra una recarga.

Las estaciones proceden de Overpass y las rutas por calles de OSRM. Ante un fallo,
se informa el problema y se permite una coordinación manual documentada. No se
inventan estaciones ni se sustituyen rutas viales por líneas rectas.

Registrar un GPS identifica el equipo, pero no configura su transmisión. La
recepción de telemetría de dispositivos físicos está fuera del alcance actual.

## Pruebas y calidad

Las pruebas de backend crean su estructura y fixtures únicamente en SQLite
aislada. No utilizan cuentas ni registros de Neon.

```powershell
cd backend
.\venv\Scripts\python.exe -m pip install -r requirements-dev.txt
.\venv\Scripts\python.exe -m unittest discover -s tests -v
.\venv\Scripts\python.exe -m ruff check .
.\venv\Scripts\python.exe -m ruff format --check .
.\venv\Scripts\python.exe -m pip check
.\venv\Scripts\python.exe -m pip_audit -r requirements.txt --progress-spinner off
```

```powershell
cd frontend
npm ci
npm run typecheck
npm run format:check
npm test
npm run build
npm audit
```

Para aplicar el formato antes de enviar cambios: `ruff format .` desde
`backend` y `npm run format` desde `frontend`.

## API

| Prefijo | Responsabilidad |
| --- | --- |
| `/api/auth` | Inicio de sesión, perfil activo, renovación y salida |
| `/api/users` | Usuarios y estados |
| `/api/profiles` | Perfiles y accesos |
| `/api/menu-options` | Navegación configurable |
| `/api/master-data` | Clientes, vehículos, GPS y eventos |
| `/api/alerts` | Alertas, métricas, mapa y abastecimiento |
| `/api/assignments` | Asignaciones, carga de técnicos y notas del caso |
| `/api/reports` | Reportes, exportaciones e historial |

Las rutas protegidas requieren `Authorization: Bearer <token>`. Una petición sin
sesión devuelve HTTP 401; una sesión sin permiso devuelve HTTP 403.

## Mantenimiento y despliegue

`backend/register_fleet_gps.py` y `backend/reconcile_fleet_states.py` muestran un
plan de mantenimiento sin escribir por defecto. `--apply` debe usarse solo tras
revisar el plan. La reconciliación respalda los estados anteriores en
`backend/backups`, ruta excluida de Git.

Para publicar, servir `frontend/dist/j2f-monitoreo-frontend/browser` con un
servidor que redirija las rutas de Angular a `index.html` y `/api` al backend.
La compilación de producción usa una URL de API relativa. Flask debe ejecutarse
con un servidor WSGI de producción, detrás de HTTPS, con orígenes explícitos y
una cuenta PostgreSQL con los permisos mínimos necesarios.

Mantener las migraciones separadas del arranque. Conservar respaldos y verificar
compatibilidad antes de un despliegue o una reversión. Las credenciales,
archivos de ejecución, respaldos y dependencias instaladas no se versionan.
