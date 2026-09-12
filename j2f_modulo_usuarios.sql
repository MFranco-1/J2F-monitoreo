-- Punto único de aplicación para psql. No crea otra base de datos.
-- Los archivos separados permiten revisar y revertir cada cambio con seguridad.
\set ON_ERROR_STOP on
\ir migrations/001_user_profile.sql
\ir migrations/002_master_data.sql
\ir migrations/003_alert_relationships.sql
\ir migrations/004_history_active_profile.sql
\ir migrations/005_seed_event_types.sql
\ir migrations/006_seed_menu_options.sql
