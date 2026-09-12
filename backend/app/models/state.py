"""
models/state.py - Modelo Estado (State)
Representa los estados posibles para usuarios y alertas.
"""

from app.datetime_utils import utcnow, as_utc_naive, iso_utc
from app import db


class State(db.Model):
    __tablename__ = "states"

    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(50), nullable=False, unique=True)
    # 'user' | 'alert' | 'general'
    type = db.Column(db.String(20), nullable=False, default="general")
    description = db.Column(db.String(255), nullable=True)
    created_at = db.Column(db.DateTime, default=utcnow)

    # Relaciones inversas
    users = db.relationship("User", back_populates="state", lazy="dynamic")
    profiles = db.relationship("Profile", back_populates="state", lazy="dynamic")
    alerts = db.relationship("Alert", back_populates="state", lazy="dynamic")
    clients = db.relationship("Client", back_populates="state", lazy="dynamic")
    vehicles = db.relationship("Vehicle", back_populates="state", lazy="dynamic")
    gps_devices = db.relationship("GpsDevice", back_populates="state", lazy="dynamic")
    event_types = db.relationship("EventType", back_populates="state", lazy="dynamic")

    def to_dict(self) -> dict:
        return {
            "id": self.id,
            "name": self.name,
            "type": self.type,
            "description": self.description,
            "created_at": iso_utc(self.created_at),
        }

    def __repr__(self) -> str:
        return f"<State {self.name} ({self.type})>"
