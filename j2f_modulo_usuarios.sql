-- =====================================================================
-- J2F Soluciones de Información
-- Datos del menú para la base existente de Neon (esquema public)
-- Tablas utilizadas: states, profiles, menu_options, profile_menu_option
-- No crea otra base de datos, tablas, columnas, rutas ni módulos.
-- Puede ejecutarse más de una vez sin duplicar los datos.
-- =====================================================================

BEGIN;

DO $$
BEGIN
    IF NOT EXISTS (
        SELECT 1
        FROM states
        WHERE LOWER(BTRIM(name)) = 'activo'
          AND type = 'user'
    ) THEN
        RAISE EXCEPTION 'No existe el estado Activo de tipo user';
    END IF;
END $$;

-- Secciones que ya mostraba el menú fijo.
WITH section_seed(name, menu_order) AS (
    VALUES
        ('MONITOREO',       0),
        ('SEGUIMIENTO',    40),
        ('ADMINISTRACIÓN', 60)
), active_state AS (
    SELECT id
    FROM states
    WHERE LOWER(BTRIM(name)) = 'activo'
      AND type = 'user'
    ORDER BY id
    LIMIT 1
)
INSERT INTO menu_options (name, url, icon, parent_id, "order", state_id, created_at, updated_at)
SELECT seed.name, NULL, 'folder', NULL, seed.menu_order, state.id,
       CURRENT_TIMESTAMP, CURRENT_TIMESTAMP
FROM section_seed AS seed
CROSS JOIN active_state AS state
WHERE NOT EXISTS (
    SELECT 1
    FROM menu_options AS existing
    WHERE existing.url IS NULL
      AND existing.parent_id IS NULL
      AND existing.name = seed.name
);

-- Las ocho rutas existentes. Solo se insertan si todavía no existen.
WITH menu_seed(name, url, icon, menu_order) AS (
    VALUES
        ('Panel de control', '/dashboard',          'dashboard',   10),
        ('Alertas',          '/alerts',             'alerts',      20),
        ('Asignaciones',     '/assignments',        'assignments', 30),
        ('Historial',        '/history',            'history',     40),
        ('Reportes',         '/reports',            'reports',     50),
        ('Usuarios',         '/admin/users',        'users',       60),
        ('Perfiles',         '/admin/profiles',     'profiles',    70),
        ('Opciones de menú', '/admin/menu-options', 'menu',        80)
), active_state AS (
    SELECT id
    FROM states
    WHERE LOWER(BTRIM(name)) = 'activo'
      AND type = 'user'
    ORDER BY id
    LIMIT 1
)
INSERT INTO menu_options (name, url, icon, parent_id, "order", state_id, created_at, updated_at)
SELECT seed.name, seed.url, seed.icon, NULL, seed.menu_order, state.id,
       CURRENT_TIMESTAMP, CURRENT_TIMESTAMP
FROM menu_seed AS seed
CROSS JOIN active_state AS state
WHERE NOT EXISTS (
    SELECT 1
    FROM menu_options AS existing
    WHERE existing.url = seed.url
);

-- Relaciona cada opción con su sección sin cambiar sus rutas ni iconos.
WITH menu_parent(url, parent_name) AS (
    VALUES
        ('/dashboard',          'MONITOREO'),
        ('/alerts',             'MONITOREO'),
        ('/assignments',        'MONITOREO'),
        ('/history',            'SEGUIMIENTO'),
        ('/reports',            'SEGUIMIENTO'),
        ('/admin/users',        'ADMINISTRACIÓN'),
        ('/admin/profiles',     'ADMINISTRACIÓN'),
        ('/admin/menu-options', 'ADMINISTRACIÓN')
)
UPDATE menu_options AS child
SET parent_id = parent.id,
    updated_at = CURRENT_TIMESTAMP
FROM menu_parent AS relation
JOIN menu_options AS parent
  ON parent.name = relation.parent_name
 AND parent.url IS NULL
 AND parent.parent_id IS NULL
WHERE child.url = relation.url
  AND child.parent_id IS DISTINCT FROM parent.id;

-- Las secciones operativas y sus opciones son visibles para todos los
-- perfiles existentes. Administración se restringe al Administrador.
WITH route_access(url, admin_only) AS (
    VALUES
        ('/dashboard',          FALSE),
        ('/alerts',             FALSE),
        ('/assignments',        FALSE),
        ('/history',            FALSE),
        ('/reports',            FALSE),
        ('/admin/users',        TRUE),
        ('/admin/profiles',     TRUE),
        ('/admin/menu-options', TRUE)
), section_access(name, admin_only) AS (
    VALUES
        ('MONITOREO',       FALSE),
        ('SEGUIMIENTO',     FALSE),
        ('ADMINISTRACIÓN',  TRUE)
), target_menu AS (
    SELECT option.id, access.admin_only
    FROM route_access AS access
    JOIN menu_options AS option ON option.url = access.url
    UNION
    SELECT option.id, access.admin_only
    FROM section_access AS access
    JOIN menu_options AS option
      ON option.name = access.name
     AND option.url IS NULL
     AND option.parent_id IS NULL
)
INSERT INTO profile_menu_option (profile_id, menu_option_id)
SELECT profile.id, target.id
FROM target_menu AS target
CROSS JOIN profiles AS profile
WHERE (NOT target.admin_only OR LOWER(BTRIM(profile.name)) = 'administrador')
  AND NOT EXISTS (
      SELECT 1
      FROM profile_menu_option AS assigned
      WHERE assigned.profile_id = profile.id
        AND assigned.menu_option_id = target.id
  );

COMMIT;
