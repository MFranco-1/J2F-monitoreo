-- =====================================================================
-- J2F Soluciones de Información
-- Módulo de Gestión de Usuarios, Perfiles y Opciones de Menú
-- Dialecto: PostgreSQL
-- Esquema normalizado en 3FN (ver DER acordado con el equipo)
-- =====================================================================

-- Ejecutar en orden: primero las entidades independientes,
-- luego las tablas puente que dependen de ellas.

-- ---------------------------------------------------------------------
-- 1. PERFIL
-- ---------------------------------------------------------------------
CREATE TABLE perfil (
    id_perfil        INTEGER GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    nombre           VARCHAR(50)  NOT NULL,
    descripcion      VARCHAR(200),
    estado_registro  SMALLINT     NOT NULL DEFAULT 1
);

COMMENT ON TABLE perfil IS 'Roles del sistema (Administrador, Técnico, etc.)';

-- ---------------------------------------------------------------------
-- 2. USUARIO
--    (usuario_creacion / usuario_modificacion son auto-referencia
--     para trazabilidad de auditoría: quién creó/editó el registro)
-- ---------------------------------------------------------------------
CREATE TABLE usuario (
    id_usuario            INTEGER GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    dni                   VARCHAR(8)   NOT NULL,
    nombres               VARCHAR(80)  NOT NULL,
    apellido_paterno      VARCHAR(50)  NOT NULL,
    apellido_materno      VARCHAR(50),
    celular               VARCHAR(9),
    correo_electronico    VARCHAR(120) NOT NULL,
    clave_hash            VARCHAR(255) NOT NULL,
    usuario_creacion      INTEGER      REFERENCES usuario(id_usuario),
    fecha_creacion        TIMESTAMP    NOT NULL DEFAULT CURRENT_TIMESTAMP,
    usuario_modificacion  INTEGER      REFERENCES usuario(id_usuario),
    fecha_modificacion    TIMESTAMP,
    estado_registro       SMALLINT     NOT NULL DEFAULT 1,
    CONSTRAINT uq_usuario_dni    UNIQUE (dni),
    CONSTRAINT uq_usuario_correo UNIQUE (correo_electronico)
);

COMMENT ON TABLE usuario IS 'Usuarios del sistema (operadores, supervisores, administradores)';
COMMENT ON COLUMN usuario.clave_hash IS 'Hash de la contraseña (nunca texto plano)';

-- ---------------------------------------------------------------------
-- 3. USUARIO_PERFIL  (relación N:M entre usuario y perfil)
-- ---------------------------------------------------------------------
CREATE TABLE usuario_perfil (
    id_usuario       INTEGER  NOT NULL REFERENCES usuario(id_usuario),
    id_perfil        INTEGER  NOT NULL REFERENCES perfil(id_perfil),
    estado_registro  SMALLINT NOT NULL DEFAULT 1,
    PRIMARY KEY (id_usuario, id_perfil)
);

COMMENT ON TABLE usuario_perfil IS 'Perfiles asignados a cada usuario (un usuario puede tener más de uno)';

-- ---------------------------------------------------------------------
-- 4. OPCION_MENU  (jerarquía padre-hijo vía id_padre, auto-referencia)
-- ---------------------------------------------------------------------
CREATE TABLE opcion_menu (
    id_opcion_menu   INTEGER GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    nombre           VARCHAR(80)  NOT NULL,
    url_menu         VARCHAR(150) NOT NULL,
    descripcion      VARCHAR(200),
    id_padre         INTEGER      REFERENCES opcion_menu(id_opcion_menu),
    estado_registro  SMALLINT     NOT NULL DEFAULT 1
);

COMMENT ON TABLE opcion_menu IS 'Ítems del menú del sistema, con jerarquía padre-hijo';

-- ---------------------------------------------------------------------
-- 5. OPCION_MENU_PERFIL  (relación N:M entre opcion_menu y perfil)
-- ---------------------------------------------------------------------
CREATE TABLE opcion_menu_perfil (
    id_opcion_menu   INTEGER  NOT NULL REFERENCES opcion_menu(id_opcion_menu),
    id_perfil        INTEGER  NOT NULL REFERENCES perfil(id_perfil),
    orden            INTEGER  NOT NULL DEFAULT 1,
    estado_registro  SMALLINT NOT NULL DEFAULT 1,
    PRIMARY KEY (id_opcion_menu, id_perfil)
);

COMMENT ON TABLE opcion_menu_perfil IS 'Qué perfiles ven cada opción de menú, y en qué orden';

-- ---------------------------------------------------------------------
-- Índices para las llaves foráneas más consultadas
-- (Postgres no las indexa automáticamente, solo la PK)
-- ---------------------------------------------------------------------
CREATE INDEX idx_usuario_perfil_perfil       ON usuario_perfil(id_perfil);
CREATE INDEX idx_opcion_menu_padre           ON opcion_menu(id_padre);
CREATE INDEX idx_opcion_menu_perfil_perfil   ON opcion_menu_perfil(id_perfil);

-- =====================================================================
-- DATOS DE PRUEBA (los mismos del modelo original / mockup)
-- Comenta o borra este bloque si no lo necesitas
-- =====================================================================

INSERT INTO perfil (nombre, descripcion) VALUES
    ('Administrador', 'Acceso completo al sistema'),
    ('Técnico',        'Gestión operativa de trabajos y atención');

-- Nota: clave_hash de ejemplo, en la app real va un hash real (bcrypt/argon2)
INSERT INTO usuario (dni, nombres, apellido_paterno, apellido_materno, celular, correo_electronico, clave_hash) VALUES
    ('90999999', 'Carlos',  'Rodriguez', NULL,        NULL,          'crodriguez@gmail.com', '$2b$12$reemplazar_por_hash_real'),
    ('56879826', 'Jose',    'Rios',      'Martinez',  '923876122',   'jrios@gmail.com',       '$2b$12$reemplazar_por_hash_real'),
    ('90157845', 'Roberto', 'Diaz',      'Guerrero',  '987456100',   'rdiaz@gmail.com',       '$2b$12$reemplazar_por_hash_real');

-- Carlos tiene ambos perfiles; Jose y Roberto son solo Técnico
INSERT INTO usuario_perfil (id_usuario, id_perfil) VALUES
    (1, 1), (1, 2),
    (2, 2),
    (3, 2);

INSERT INTO opcion_menu (id_opcion_menu, nombre, url_menu, descripcion, id_padre) OVERRIDING SYSTEM VALUE VALUES
    (1,  'Mantenimiento',           '/',                              NULL, NULL),
    (6,  'Trabajos',                '/',                              NULL, NULL),
    (8,  'Registrar Trabajo',       'home/RegistrarTrabajo',          NULL, NULL),
    (2,  'Tipo Servicio',           'home/TipoServicio',              NULL, 1),
    (3,  'Fallas',                  'home/Fallas',                    NULL, 1),
    (4,  'Tipo Asistencia',         'home/TipoAsistencia',            NULL, 1),
    (5,  'Detalle Trabajo',         'home/DetalleTrabajo',            NULL, 1),
    (9,  'Usuarios',                'home/Usuarios',                  NULL, 1),
    (10, 'Lugares de atención',     'home/LugaresAtencion',           NULL, 1),
    (7,  'Ordenes de Trabajo',      'home/OrdenesTrabajo',            NULL, 6),
    (11, 'Sub Ordenes de trabajo',  'home/SubOrdenesTrabajo',         NULL, 7);

-- Reajusta la secuencia de identidad tras insertar IDs explícitos arriba
SELECT setval(pg_get_serial_sequence('opcion_menu', 'id_opcion_menu'), 11, true);

INSERT INTO opcion_menu_perfil (id_opcion_menu, id_perfil, orden) VALUES
    (1, 1, 1), (2, 1, 2), (3, 1, 3), (4, 1, 4), (5, 1, 5),
    (6, 1, 1), (7, 1, 2), (9, 1, 6), (10, 1, 7),
    (8, 2, 1);
