# J2F — Centro de Monitoreo

**Revisión del 8 de septiembre de 2026 para la base existente `j2f_monitoreo`.**

Este paquete sustituye la entrega anterior. Está adaptado a las nueve tablas en
`public` y a las columnas/relaciones que se consultaron en tu PostgreSQL:

`users`, `profiles`, `menu_options`, `profile_menu_option`, `states`, `alerts`,
`assignments`, `history` y `reports`.

Conserva Angular 17.3, Flask 3.0.3, PostgreSQL y la presentación profesional de
J2F en azul marino y blanco, sin emojis. No se añadieron módulos de negocio.

## Trabajar con la base compartida de Neon

Cada integrante puede usar la misma base remota sin instalar PostgreSQL. La URL
debe recibirse por un canal privado y configurarse solo en su terminal; nunca se
debe pegar en el código, el README, un commit o un archivo `.env` versionado.

Después de clonar el repositorio, en PowerShell:

```powershell
git clone <URL_DEL_REPOSITORIO>
cd J2F\backend
python -m venv venv
.\venv\Scripts\Activate.ps1
python -m pip install -r requirements.txt
$env:DATABASE_URL = '<URL_DE_NEON_RECIBIDA_PRIVADAMENTE>'
python init_db.py
python run.py
```

`DATABASE_URL` tiene prioridad y puede ser la URL directa o la URL con pooler
entregada por Neon. Se conservan sus parámetros, incluidos `sslmode` y
`channel_binding`. Si comienza con `postgres://`, el backend normaliza solamente
ese prefijo para SQLAlchemy. No imprimas la variable ni la guardes en GitHub.

Para usar PostgreSQL local como alternativa, deja `DATABASE_URL` sin definir y
configura `PGHOST`, `PGPORT`, `PGDATABASE`, `PGUSER` y `PGPASSWORD`. El archivo
`.env.example` de la raíz contiene marcadores seguros; el proyecto no carga
archivos `.env` automáticamente, por lo que no requiere `python-dotenv`.

## Sustituir la versión que ya tienes

1. Detén el backend y el frontend con **Ctrl + C** en sus respectivas terminales.
2. Extrae el ZIP actualizado dentro de `C:\Users\Mauricio\Desktop\J2F` y acepta
   reemplazar los archivos existentes. `backend`, `frontend` y este `README.md`
   deben quedar directamente dentro de `J2F`.
3. Conserva el entorno `backend\venv` y las dependencias `frontend\node_modules`
   ya instaladas. Las versiones de las dependencias no cambiaron.
4. Abre esa carpeta en Antigravity o Visual Studio Code. El paquete contiene
   el proyecto integrado; no requiere fusionar una carpeta de correcciones.

Si prefieres otra carpeta nueva, también funciona. En ese caso crea allí el
entorno virtual e instala las dependencias según la sección de instalación.

## Iniciar el backend en PowerShell

En tu terminal actual, si `(venv)` sigue activo y `PGPASSWORD` conserva la
contraseña que ya configuraste:

```powershell
cd C:\Users\Mauricio\Desktop\J2F\backend
$env:PGDATABASE = 'j2f_monitoreo'
python init_db.py
if ($LASTEXITCODE -eq 0) { python run.py }
```

El resultado esperado de la verificación es:

```text
Base conectada: j2f_monitoreo
Conexión correcta. Las 9 tablas y sus columnas requeridas existen. No se modificaron datos.
```

Para registrar las tres secciones, las ocho opciones existentes y sus accesos,
ejecuta el script idempotente desde la raíz del proyecto:

```powershell
psql -v ON_ERROR_STOP=1 -f .\j2f_modulo_usuarios.sql
```

Las cinco rutas operativas se asignan a todos los perfiles existentes y las
tres rutas administrativas solo al perfil `Administrador`. Si las rutas ya
están registradas, el script no las duplica; únicamente asegura sus secciones
padre y permisos.

Si abriste una terminal nueva, antes de esos comandos activa el entorno y
configura tu contraseña real de PostgreSQL:

```powershell
cd C:\Users\Mauricio\Desktop\J2F\backend
.\venv\Scripts\Activate.ps1
$env:PGPASSWORD = 'TU_CONTRASENA_ACTUAL_DE_POSTGRES'
```

`TU_CONTRASENA_ACTUAL_DE_POSTGRES` es un marcador que debes sustituir en tu
terminal. No se incluyó tu contraseña en este paquete.

**`PGDATABASE` es el nombre de la base, `j2f_monitoreo`. No es el nombre de un
archivo `.sql`.** Los valores predeterminados son `localhost`, puerto `5432`
y usuario `postgres`. `PGHOST`, `PGPORT` y `PGUSER` permiten conservar otra
configuración si la necesitas. `DATABASE_URL`, si está definida, tiene prioridad.

Las variables deben estar configuradas en la misma terminal donde ejecutas Python.
No se cargan archivos `.env` automáticamente.

`init_db.py` verifica conexión y nombres de tablas/columnas mediante una
transacción de solo lectura. `run.py` también verifica antes de iniciar y se
detiene si hay un problema. Ninguno crea, renombra, elimina ni modifica tablas.
El arranque normal tampoco inserta estados, perfiles o usuarios de demostración.

## Iniciar el frontend en otra terminal

```powershell
cd C:\Users\Mauricio\Desktop\J2F\frontend
npm start
```

Abre **http://localhost:4200**. La API local utiliza
**http://localhost:5000/api**.

Inicia sesión con el correo o DNI y la contraseña de una cuenta que ya exista
en tu base. La cuenta y su perfil deben estar activos. La contraseña del usuario
de la aplicación puede ser distinta de la contraseña de PostgreSQL.
Las sesiones guardadas por la entrega anterior requieren iniciar sesión de nuevo.

## Instalación si elegiste una carpeta nueva

Desde `backend`, usa una instalación de Python compatible con las dependencias
fijadas (la revisión se ejecutó con Python 3.12):

```powershell
python -m venv venv
.\venv\Scripts\Activate.ps1
python -m pip install -r requirements.txt
```

Después configura la conexión y sigue los pasos de inicio del backend.
Desde `frontend`, instala las dependencias antes de iniciarlo:

```powershell
npm ci
npm start
```

Mantén una versión de Node compatible con Angular 17.3. Las dependencias se
conservan en el `package-lock.json` original; este paquete no actualiza Angular.

## Compatibilidad corregida

- Los modelos usan las tablas y columnas en inglés de tu instalación.
- Las referencias de alertas, asignaciones, historial y reportes apuntan a
  `users.id`.
- El formulario de usuarios guarda el nombre completo en `users.full_name`
  y un perfil en `users.profile_id`. La base actual permite **un perfil por
  usuario**; no contiene una tabla de relación usuario-perfil para varios roles.
- No se muestran campos de apellidos separados o celular, porque esas columnas
  no existen en esta base. No se dividieron ni cambiaron nombres guardados.
- Los estados de usuarios, perfiles y menús se obtienen de `states`. Sus
  identificadores no se tratan como banderas fijas `0/1`.
- Los perfiles con acceso a una opción se guardan en `profile_menu_option`.
  El orden se guarda en `menu_options.order`.
- La columna `menu_options.icon` se conserva. Los iconos existentes no se
  reemplazan al editar; la interfaz utiliza SVG y no imprime emojis del campo.
- Se mantienen las correcciones de autenticación, renovación y revocación de
  sesiones, permisos, validaciones, asignación, fechas UTC y trazabilidad.
- La baja de un usuario utiliza el estado Inactivo y conserva sus referencias.
- Se conserva la corrección de recarga de rutas de Angular y el diseño de
  las pantallas actuales para escritorio y móvil.

**No se añadieron tablas, columnas ni migraciones, ni se cambiaron las contraseñas
existentes.** Las operaciones que realices en la aplicación seguirán guardándose
en tu base habitual.

`j2f_modulo_usuarios.sql` es el único SQL operativo del proyecto. Trabaja sobre
las tablas existentes en Neon y no crea otra base de datos ni un esquema alterno.

## Comprobaciones realizadas

- **36 pruebas de backend aprobadas**. Incluyen autenticación y revocación,
  permisos, CRUD, perfil único, estados con identificadores distintos de 1/2,
  asignaciones, historial, fechas y los tres tipos de reportes existentes.
- Comparación de los modelos con la estructura proporcionada: nombres de las
  nueve tablas, columnas, tipos, nulabilidad, claves primarias y claves foráneas.
- **14 pruebas del frontend aprobadas** para autenticación, actualización del
  menú dinámico, selección excluyente del respaldo y notificaciones del CRUD,
  perfil único y sesiones de la versión anterior.
- **Compilación Angular de producción correcta**.
- Recorrido en Chromium con la compilación de producción y la API sobre una
  base temporal: login, creación/edición de usuario, perfiles y menús, asignación
  de alerta, cierre por el técnico responsable, restricciones de administración,
  historial, reportes, recarga de rutas, pantalla móvil y cierre de sesión.
  Sin errores JavaScript ni respuestas HTTP fallidas durante ese recorrido.

Comandos para repetir las pruebas incluidas:

```powershell
# Desde backend, con el entorno virtual activo
python -m unittest discover -s tests -v

# Desde frontend
npm test
npm run build
```

Las pruebas automatizadas se ejecutan con SQLite aislada, nunca contra los datos
de PostgreSQL. `init_db.py` realiza por separado una validación de solo lectura
de la conexión PostgreSQL configurada.

## Si algo impide iniciar

- Si todavía aparece `Tabla faltante: usuario` o `perfil`, se está ejecutando
  la entrega anterior. Comprueba que reemplazaste los archivos y que la terminal
  apunta a la carpeta actualizada.
- Si falla la conexión, comprueba el servicio PostgreSQL, la contraseña y las
  variables de conexión. El verificador muestra qué base está utilizando.
- Si se indica que faltan tablas o columnas, conserva ese mensaje; el
  verificador no cambia tu base para intentar corregirlo.
- Si el puerto está ocupado, detén el servidor anterior.
- Si se rechaza el login, usa una cuenta de tu aplicación con usuario y perfil
  activos. No se crea automáticamente un administrador ni se restablecen claves.
- Si no hay operadores disponibles, comprueba que exista una cuenta activa con
  un perfil activo llamado Técnico u Operador.

Se conserva la configuración de producción: `environment.production.ts` utiliza
`/api`. Un servidor de producción debe servir esa API y devolver `index.html`
para las rutas de Angular. No se realizó ningún despliegue en esta entrega.
