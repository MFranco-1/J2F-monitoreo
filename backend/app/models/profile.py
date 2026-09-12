"""
models/profile.py - Modelo Perfil (Profile)
Representa los roles de usuario dentro del sistema.
"""

from app.datetime_utils import utcnow, as_utc_naive, iso_utc
from app import db

# Tabla intermedia Profile <-> MenuOption (Many-to-Many)
profile_menu_option = db.Table(
    "profile_menu_option",
    db.Column("profile_id", db.Integer, db.ForeignKey("profiles.id"), primary_key=True),
    db.Column("menu_option_id", db.Integer, db.ForeignKey("menu_options.id"), primary_key=True),
)

# Fuente principal de perfiles asignados a cada usuario. ``users.profile_id`` se
# conserva como respaldo temporal para instalaciones todavía no migradas.
user_profile = db.Table(
    "user_profile",
    db.Column("user_id", db.Integer, db.ForeignKey("users.id"), primary_key=True),
    db.Column("profile_id", db.Integer, db.ForeignKey("profiles.id"), primary_key=True),
)


class Profile(db.Model):
    __tablename__ = "profiles"

    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(100), nullable=False, unique=True)
    description = db.Column(db.String(255), nullable=True)
    state_id = db.Column(db.Integer, db.ForeignKey("states.id"), nullable=False)
    created_at = db.Column(db.DateTime, default=utcnow)
    updated_at = db.Column(
        db.DateTime,
        default=utcnow,
        onupdate=utcnow,
    )

    # Relaciones
    state = db.relationship("State", back_populates="profiles")
    users = db.relationship(
        "User", secondary=user_profile, back_populates="profiles", lazy="dynamic"
    )
    legacy_users = db.relationship(
        "User", back_populates="profile", foreign_keys="User.profile_id", lazy="dynamic"
    )
    menu_options = db.relationship(
        "MenuOption",
        secondary=profile_menu_option,
        back_populates="profiles",
        lazy="subquery",
    )

    def to_dict(self, include_menus: bool = False) -> dict:
        data = {
            "id": self.id,
            "name": self.name,
            "description": self.description,
            "state_id": self.state_id,
            "state": self.state.to_dict() if self.state else None,
            "created_at": iso_utc(self.created_at),
            "updated_at": iso_utc(self.updated_at),
        }
        if include_menus:
            data["menu_options"] = [m.to_dict() for m in self.menu_options]
        return data

    def __repr__(self) -> str:
        return f"<Profile {self.name}>"
