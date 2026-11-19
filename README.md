# J2F Monitoreo

J2F Monitoreo permite a un equipo registrar alertas de flota, asignarlas a técnicos y seguir cada atención hasta su cierre. El tablero muestra vehículos con telemetría simulada y conserva en PostgreSQL las asignaciones, las notas y el historial de cada caso.

![Tablero de monitoreo de J2F con datos de prueba](frontend/docs/dashboard.png)

Angular y Leaflet presentan el mapa. Flask autentica las solicitudes y las funciones de PostgreSQL comprueban los permisos, las transiciones de estado y las reglas de abastecimiento.

## Ejecutar en Windows con Neon

Se requiere Python 3.11 o posterior. Desde la raíz del repositorio, ejecuta:

```powershell
.\scripts\preparar-local.ps1
```

El script instala las dependencias de Python y Angular, descarga Node para el proyecto y prepara `.env.local` con claves de sesión privadas. En ese archivo, reemplaza el valor de `DATABASE_URL` por la cadena de conexión PostgreSQL de tu proyecto en Neon. Conserva los parámetros TLS de la URL.

```powershell
.\scripts\iniciar-local.ps1 -OpenBrowser
# Al terminar
.\scripts\detener-local.ps1
```

El frontend escucha en <http://127.0.0.1:4200> y envía las peticiones de `/api` a Flask a través del proxy de desarrollo. Puedes comprobar la conexión del backend en <http://127.0.0.1:5000/api/catalogs>. Inicia sesión con un usuario registrado en esa base. Al usar una base compartida con el esquema instalado, el arranque conserva los registros existentes.

## Base de datos

Los archivos de `database/` se aplican en orden: `01_esquema.sql` crea las tablas de una base vacía, `02_catalogos.sql` configura permisos, estados, menús y parámetros, y `03_funciones.sql` instala las funciones que usa la API. La telemetría del mapa se simula en cada navegador. La consulta de estaciones y de rutas usa Overpass y OSRM.

Para instalar desde una terminal con `DATABASE_URL` definida, usa `python init_db.py` desde `backend/` **solo en una base vacía**. Para actualizar una instalación compatible con las tablas existentes, usa `python init_db.py --existing`. Para crear el primer administrador en una instalación sin usuarios, usa `python create_admin.py`.

## Pruebas

En `backend/`, instala `requirements-dev.txt` y define `J2F_TEST_DATABASE_URL` con una **base PostgreSQL exclusiva para pruebas** cuyo nombre termine en `_test`. La suite recrea el esquema público de esa base.

```powershell
python -m pytest tests -q
```

En `frontend/`, con las dependencias instaladas:

```powershell
npm test
npm run typecheck
npm run build
```

Para desplegar el frontend compilado, configura el servidor web para servir Angular y redirigir `/api` a Flask. En producción, el backend requiere `DATABASE_URL` y dos claves privadas distintas de al menos 32 caracteres, `SECRET_KEY` y `JWT_SECRET_KEY`.
