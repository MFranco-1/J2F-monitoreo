-- 006: menú actual con sus agrupaciones y permisos, sin duplicar rutas.
BEGIN;
DO $$
BEGIN
 IF NOT EXISTS (SELECT 1 FROM states WHERE LOWER(BTRIM(name))='activo' AND type='user') THEN
  RAISE EXCEPTION 'No existe el estado Activo de tipo user';
 END IF;
END $$;
WITH active_state AS (
 SELECT id FROM states WHERE LOWER(BTRIM(name))='activo' AND type='user' ORDER BY id LIMIT 1
), sections(name,icon,menu_order) AS (VALUES
 ('MONITOREO','folder',0),('SEGUIMIENTO','folder',40),('ADMINISTRACIÓN','folder',60)
)
INSERT INTO menu_options(name,url,icon,parent_id,"order",state_id,created_at,updated_at)
SELECT s.name,NULL,s.icon,NULL,s.menu_order,a.id,CURRENT_TIMESTAMP,CURRENT_TIMESTAMP
FROM sections s CROSS JOIN active_state a
WHERE NOT EXISTS (SELECT 1 FROM menu_options m WHERE m.url IS NULL AND LOWER(m.name)=LOWER(s.name));

WITH active_state AS (
 SELECT id FROM states WHERE LOWER(BTRIM(name))='activo' AND type='user' ORDER BY id LIMIT 1
), seed(name,url,icon,menu_order,parent_name) AS (VALUES
 ('Panel de control','/dashboard','dashboard',10,'MONITOREO'),
 ('Alertas','/alerts','alerts',20,'MONITOREO'),
 ('Asignaciones','/assignments','assignments',30,'MONITOREO'),
 ('Historial','/history','history',40,'SEGUIMIENTO'),
 ('Reportes','/reports','reports',50,'SEGUIMIENTO'),
 ('Usuarios','/admin/users','users',60,'ADMINISTRACIÓN'),
 ('Perfiles','/admin/profiles','profiles',70,'ADMINISTRACIÓN'),
 ('Opciones de menú','/admin/menu-options','menu',80,'ADMINISTRACIÓN'),
 ('Datos maestros','/admin/master-data','database',90,'ADMINISTRACIÓN')
)
INSERT INTO menu_options(name,url,icon,parent_id,"order",state_id,created_at,updated_at)
SELECT s.name,s.url,s.icon,(SELECT MIN(id) FROM menu_options WHERE url IS NULL AND LOWER(name)=LOWER(s.parent_name)),s.menu_order,a.id,CURRENT_TIMESTAMP,CURRENT_TIMESTAMP
FROM seed s CROSS JOIN active_state a WHERE NOT EXISTS (SELECT 1 FROM menu_options m WHERE m.url=s.url);

WITH mapping(url,parent_name) AS (VALUES
 ('/dashboard','MONITOREO'),('/alerts','MONITOREO'),('/assignments','MONITOREO'),
 ('/history','SEGUIMIENTO'),('/reports','SEGUIMIENTO'),('/admin/users','ADMINISTRACIÓN'),
 ('/admin/profiles','ADMINISTRACIÓN'),('/admin/menu-options','ADMINISTRACIÓN'),
 ('/admin/master-data','ADMINISTRACIÓN')
)
UPDATE menu_options child SET parent_id=parent.id,updated_at=CURRENT_TIMESTAMP
FROM mapping x JOIN menu_options parent ON parent.url IS NULL AND LOWER(parent.name)=LOWER(x.parent_name)
WHERE child.url=x.url AND child.parent_id IS DISTINCT FROM parent.id;

WITH access(url,role) AS (VALUES
 ('/dashboard','administrador'),('/alerts','administrador'),('/assignments','administrador'),('/history','administrador'),('/reports','administrador'),
 ('/admin/users','administrador'),('/admin/profiles','administrador'),('/admin/menu-options','administrador'),('/admin/master-data','administrador'),
 ('/dashboard','tecnico'),('/alerts','tecnico'),('/assignments','tecnico'),('/history','tecnico')
)
INSERT INTO profile_menu_option(profile_id,menu_option_id)
SELECT p.id,m.id FROM access a JOIN profiles p ON
 ((a.role='administrador' AND LOWER(BTRIM(p.name))='administrador') OR
  (a.role='tecnico' AND LOWER(BTRIM(p.name)) IN ('tecnico','técnico')))
JOIN menu_options m ON m.url=a.url
ON CONFLICT (profile_id,menu_option_id) DO NOTHING;

INSERT INTO profile_menu_option(profile_id,menu_option_id)
SELECT DISTINCT child_access.profile_id,parent.id FROM profile_menu_option child_access
JOIN menu_options child ON child.id=child_access.menu_option_id
JOIN menu_options parent ON parent.id=child.parent_id
ON CONFLICT (profile_id,menu_option_id) DO NOTHING;
COMMIT;
-- Reversión: desactivar las opciones nuevas desde el CRUD; no borrar permisos usados.
