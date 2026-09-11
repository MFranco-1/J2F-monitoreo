"""
models/menu_option.py - Modelo Opción de Menú (MenuOption)
Permite configurar dinámicamente el menú lateral de la aplicación.
"""

from app.datetime_utils import utcnow, as_utc_naive, iso_utc
from app import db
from app.models.profile import profile_menu_option


class MenuOption(db.Model):
    __tablename__ = "menu_options"

    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(100), nullable=False)
    url = db.Column(db.String(255), nullable=True)
    icon = db.Column(db.String(100), nullable=True)  # e.g. nombre de ícono Material
    # Referencia a sí mismo para menú padre (self-referential)
    parent_id = db.Column(db.Integer, db.ForeignKey("menu_options.id"), nullable=True)
    order = db.Column(db.Integer, default=0)  # Orden de aparición
    state_id = db.Column(db.Integer, db.ForeignKey("states.id"), nullable=False)
    created_at = db.Column(db.DateTime, default=utcnow)
    updated_at = db.Column(
        db.DateTime,
        default=utcnow,
        onupdate=utcnow,
    )

    # Relaciones
    state = db.relationship("State", foreign_keys=[state_id])
    children = db.relationship(
        "MenuOption",
        backref=db.backref("parent", remote_side=[id]),
        lazy="subquery",
    )
    profiles = db.relationship(
        "Profile",
        secondary=profile_menu_option,
        back_populates="menu_options",
        lazy="subquery",
    )

    def to_dict(self, include_children: bool = True) -> dict:
        data = {
            "id": self.id,
            "name": self.name,
            "url": self.url,
            "icon": self.icon,
            "parent_id": self.parent_id,
            "parent": {"id": self.parent.id, "name": self.parent.name} if self.parent else None,
            "order": self.order,
            "state_id": self.state_id,
            "state": self.state.to_dict() if self.state else None,
            "profiles": [{"id": p.id, "name": p.name} for p in self.profiles],
            "created_at": iso_utc(self.created_at),
            "updated_at": iso_utc(self.updated_at),
        }
        if include_children:
            data["children"] = [c.to_dict(include_children=False) for c in self.children]
        return data

    def __repr__(self) -> str:
        return f"<MenuOption {self.name}>"
