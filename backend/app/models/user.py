"""
models/user.py - Modelo Usuario (User)
Representa a los operadores y administradores del sistema.
"""

from app.datetime_utils import utcnow, as_utc_naive, iso_utc
from werkzeug.security import generate_password_hash, check_password_hash
from app import db


class User(db.Model):
    __tablename__ = "users"

    id = db.Column(db.Integer, primary_key=True)
    dni = db.Column(db.String(20), nullable=False, unique=True, index=True)
    full_name = db.Column(db.String(150), nullable=False)
    email = db.Column(db.String(150), nullable=False, unique=True, index=True)
    password_hash = db.Column(db.String(256), nullable=False, default="")
    profile_id = db.Column(db.Integer, db.ForeignKey("profiles.id"), nullable=True)
    state_id = db.Column(db.Integer, db.ForeignKey("states.id"), nullable=False)
    last_login = db.Column(db.DateTime, nullable=True)
    created_at = db.Column(db.DateTime, default=utcnow)
    updated_at = db.Column(
        db.DateTime,
        default=utcnow,
        onupdate=utcnow,
    )

    # Relaciones
    state = db.relationship("State", back_populates="users")
    profile = db.relationship("Profile", back_populates="users")
    assignments = db.relationship("Assignment", back_populates="user", lazy="dynamic")
    history_entries = db.relationship("History", back_populates="user", lazy="dynamic")

    # --- Métodos de contraseña ---
    def set_password(self, password: str) -> None:
        """Genera y almacena el hash de la contraseña."""
        self.password_hash = generate_password_hash(password)

    def check_password(self, password: str) -> bool:
        """Verifica si la contraseña dada coincide con el hash almacenado."""
        return check_password_hash(self.password_hash, password)

    @property
    def active_assignments_count(self) -> int:
        """Número de alertas activas asignadas a este operador."""
        from app.models.assignment import Assignment
        from app.models.alert import Alert
        return (
            self.assignments.join(Alert)
            .filter(Assignment.completed_at.is_(None), ~Alert.state.has(name="Cerrado"))
            .count()
        )

    def to_dict(self, include_profile: bool = True) -> dict:
        data = {
            "id": self.id,
            "dni": self.dni,
            "full_name": self.full_name,
            "email": self.email,
            "profile_id": self.profile_id,
            "state_id": self.state_id,
            "state": self.state.to_dict() if self.state else None,
            "last_login": iso_utc(self.last_login),
            "created_at": iso_utc(self.created_at),
            "updated_at": iso_utc(self.updated_at),
        }
        if include_profile:
            data["profile"] = self.profile.to_dict() if self.profile else None
        return data

    def __repr__(self) -> str:
        return f"<User {self.dni} - {self.full_name}>"
