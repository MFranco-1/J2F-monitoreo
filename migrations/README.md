# Aplicación de migraciones

Ejecutar en este orden después de hacer una copia de seguridad y revisar el destino:

```powershell
psql "$env:DATABASE_URL" -v ON_ERROR_STOP=1 -f migrations/001_user_profile.sql
psql "$env:DATABASE_URL" -v ON_ERROR_STOP=1 -f migrations/002_master_data.sql
psql "$env:DATABASE_URL" -v ON_ERROR_STOP=1 -f migrations/003_alert_relationships.sql
psql "$env:DATABASE_URL" -v ON_ERROR_STOP=1 -f migrations/004_history_active_profile.sql
psql "$env:DATABASE_URL" -v ON_ERROR_STOP=1 -f migrations/005_seed_event_types.sql
psql "$env:DATABASE_URL" -v ON_ERROR_STOP=1 -f migrations/006_seed_menu_options.sql
```

Los scripts son incrementales e idempotentes. No contienen `DROP` ni `TRUNCATE`.
La reversión recomendada es volver a la versión anterior del código y conservar las
tablas/columnas. Eliminarlas podría perder asignaciones multiperfil y trazabilidad.
