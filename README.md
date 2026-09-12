# J2F — Centro de Monitoreo

Aplicación Angular 17.3 + Flask + SQLAlchemy + JWT para monitoreo, preparada para
usuarios multiperfil, menú dinámico y maestros de clientes, vehículos, dispositivos
GPS y tipos de evento.

## Migración segura de PostgreSQL / Neon

El código no ejecuta migraciones al arrancar. Antes de desplegarlo, crea un respaldo
de Neon y revisa `j2f_modulo_usuarios.sql`. Es el único script SQL del proyecto:
contiene cambios incrementales e idempotentes, no usa `DROP` ni `TRUNCATE` y conserva
`users.profile_id`, las alertas y los demás datos actuales.

Para aplicar todo desde un único archivo del proyecto:

```powershell
$env:DATABASE_URL = '<URL_PRIVADA_DE_NEON>'
psql "$env:DATABASE_URL" -v ON_ERROR_STOP=1 -f j2f_modulo_usuarios.sql
```

El mismo archivo incorpora tres clientes de demostración, tres vehículos para cada
cliente y dieciocho alertas identificables mediante la fuente `Datos de prueba J2F`.
Ejecutarlo nuevamente no duplica esos registros.

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

Abrir `http://localhost:4200`. Las rutas administrativas, incluidos los maestros,
requieren el perfil activo Administrador. El Técnico puede consultar maestros desde
una alerta, pero no modificarlos.

La pantalla de Datos maestros utiliza `/master-data`: los perfiles con esa opción
asignada pueden consultarla, mientras que solo Administrador puede modificarla.

La pantalla de alertas muestra todo por defecto. El filtro de cliente carga sus
vehículos y limita las alertas; el filtro de vehículo limita el resultado a esa unidad.
Seleccionar `Todos los clientes` restaura la consulta general.

## Pruebas

```powershell
cd backend
python -m unittest discover -s tests -v

cd ..\frontend
npm test
npm run build
```

Las pruebas de backend usan SQLite aislada y no acceden a Neon.

## Reversión

La reversión no debe borrar las tablas nuevas: vuelve a la versión anterior del código
y conserva columnas y registros compatibles. Antes de una eliminación posterior se
deben auditar dependencias y respaldar asignaciones multiperfil e historial. Nunca se
versionan `.env`, contraseñas, URLs privadas ni tokens.
