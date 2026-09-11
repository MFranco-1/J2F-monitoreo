# models/__init__.py
# Exportar todos los modelos para facilitar importaciones
from app.models.state import State
from app.models.profile import Profile
from app.models.user import User
from app.models.menu_option import MenuOption
from app.models.alert import Alert
from app.models.assignment import Assignment
from app.models.history import History
from app.models.report import Report

__all__ = [
    "State",
    "Profile",
    "User",
    "MenuOption",
    "Alert",
    "Assignment",
    "History",
    "Report",
]
