"""Datos exclusivos del entorno de pruebas; no se cargan en desarrollo ni producción."""

from app import db


def seed_testing_data() -> None:
    """Carga las cuentas y catálogos usados por las pruebas SQLite."""
    from app.models.master_data import EventType
    from app.models.menu_option import MenuOption
    from app.models.profile import Profile
    from app.models.state import State
    from app.models.user import User

    # Solo insertar si no existen datos
    if State.query.first():
        return

    # Estados base
    states = [
        State(name="Activo", type="user", description="Usuario activo en el sistema"),
        State(name="Inactivo", type="user", description="Usuario inactivo en el sistema"),
        State(name="Abierto", type="alert", description="Alerta nueva sin atender"),
        State(name="En Progreso", type="alert", description="Alerta siendo atendida"),
        State(name="Cerrado", type="alert", description="Alerta resuelta y cerrada"),
        State(name="Escalado", type="alert", description="Alerta escalada a nivel superior"),
        State(
            name="Anulado",
            type="alert",
            description="Caso anulado con motivo; no es una resolución",
        ),
    ]
    db.session.add_all(states)
    db.session.flush()

    # Perfil administrador
    admin_profile = Profile(
        name="Administrador",
        description="Acceso completo al sistema",
        state_id=states[0].id,
    )
    db.session.add(admin_profile)
    db.session.flush()

    technician_profile = Profile(
        name="Técnico", description="Atención operativa de alertas", state_id=states[0].id
    )
    db.session.add(technician_profile)
    db.session.flush()

    operator_profile = Profile(
        name="Operador", description="Revisión y asignación de alertas", state_id=states[0].id
    )
    db.session.add(operator_profile)
    db.session.flush()

    supervisor_profile = Profile(
        name="Supervisor", description="Supervisión y asignación de alertas", state_id=states[0].id
    )
    db.session.add(supervisor_profile)
    db.session.flush()

    # Usuario administrador por defecto
    admin_user = User(
        dni="00000000",
        full_name="Administrador J2F",
        email="admin@j2f.com",
        profile_id=admin_profile.id,
        state_id=states[0].id,
    )
    admin_user.set_password("Admin@J2F2024")
    admin_user.profiles = [admin_profile]
    db.session.add(admin_user)

    # El entorno de pruebas refleja las secciones y opciones registradas en Neon
    # mediante j2f_modulo_usuarios.sql.
    sections = {
        "MONITOREO": MenuOption(name="MONITOREO", icon="folder", order=0, state_id=states[0].id),
        "SEGUIMIENTO": MenuOption(
            name="SEGUIMIENTO", icon="folder", order=40, state_id=states[0].id
        ),
        "ADMINISTRACIÓN": MenuOption(
            name="ADMINISTRACIÓN", icon="folder", order=60, state_id=states[0].id
        ),
    }
    menu_options = [
        MenuOption(
            name="Panel de control",
            url="/dashboard",
            icon="dashboard",
            order=10,
            state_id=states[0].id,
            parent=sections["MONITOREO"],
        ),
        MenuOption(
            name="Alertas",
            url="/alerts",
            icon="alerts",
            order=20,
            state_id=states[0].id,
            parent=sections["MONITOREO"],
        ),
        MenuOption(
            name="Asignaciones",
            url="/assignments",
            icon="assignments",
            order=30,
            state_id=states[0].id,
            parent=sections["MONITOREO"],
        ),
        MenuOption(
            name="Historial",
            url="/history",
            icon="history",
            order=40,
            state_id=states[0].id,
            parent=sections["SEGUIMIENTO"],
        ),
        MenuOption(
            name="Reportes",
            url="/reports",
            icon="reports",
            order=50,
            state_id=states[0].id,
            parent=sections["SEGUIMIENTO"],
        ),
        MenuOption(
            name="Usuarios",
            url="/admin/users",
            icon="users",
            order=60,
            state_id=states[0].id,
            parent=sections["ADMINISTRACIÓN"],
        ),
        MenuOption(
            name="Perfiles",
            url="/admin/profiles",
            icon="profiles",
            order=70,
            state_id=states[0].id,
            parent=sections["ADMINISTRACIÓN"],
        ),
        MenuOption(
            name="Opciones de menú",
            url="/admin/menu-options",
            icon="menu",
            order=80,
            state_id=states[0].id,
            parent=sections["ADMINISTRACIÓN"],
        ),
        MenuOption(
            name="Datos maestros",
            url="/master-data",
            icon="database",
            order=90,
            state_id=states[0].id,
            parent=sections["ADMINISTRACIÓN"],
        ),
    ]
    for option in [*sections.values(), *menu_options]:
        option.profiles = [admin_profile]
    db.session.add_all([*sections.values(), *menu_options])
    for option in menu_options:
        if option.url in {"/dashboard", "/alerts", "/assignments", "/history"}:
            option.profiles.append(technician_profile)
            option.parent.profiles.append(
                technician_profile
            ) if technician_profile not in option.parent.profiles else None
            option.profiles.append(operator_profile)
            option.parent.profiles.append(
                operator_profile
            ) if operator_profile not in option.parent.profiles else None
        if option.url in {
            "/dashboard",
            "/alerts",
            "/assignments",
            "/history",
            "/reports",
            "/master-data",
        }:
            option.profiles.append(supervisor_profile)
            option.parent.profiles.append(
                supervisor_profile
            ) if supervisor_profile not in option.parent.profiles else None
    event_seed = [
        ("SOS", "Botón de pánico o SOS", "critical", True),
        ("SPEEDING", "Exceso de velocidad", "high", True),
        ("GEOFENCE_EXIT", "Salida de geocerca", "high", True),
        ("GEOFENCE_ENTRY", "Ingreso a geocerca", "low", False),
        ("GPS_SIGNAL_LOSS", "Pérdida de señal GPS", "high", True),
        ("LOW_FUEL", "Combustible bajo", "high", True),
        ("POWER_CUT", "Corte de alimentación del dispositivo", "critical", True),
        ("LOW_BATTERY", "Batería baja", "medium", True),
        ("DEVICE_TAMPER", "Manipulación o desconexión del dispositivo", "critical", True),
        ("UNAUTHORIZED_MOVEMENT", "Movimiento no autorizado", "critical", True),
        ("OUT_OF_HOURS_IGNITION", "Encendido fuera del horario permitido", "high", True),
        ("PROLONGED_STOP", "Parada o inactividad prolongada", "medium", False),
        ("COMMUNICATION_FAILURE", "Falla de comunicación del dispositivo", "high", True),
    ]
    db.session.add_all(
        [
            EventType(
                code=code,
                name=name,
                description=name,
                default_priority=priority,
                generates_alert=generates,
                expected_action="Aplicar el protocolo operativo vigente",
                state_id=states[0].id,
            )
            for code, name, priority, generates in event_seed
        ]
    )
    db.session.commit()
