"""
models/history.py - Modelo Historial (History)
Registro inmutable de trazabilidad: cada acción sobre una alerta queda registrada.
"""

import json
from app.datetime_utils import utcnow, iso_utc
from app import db


class History(db.Model):
    __tablename__ = "history"

    id = db.Column(db.Integer, primary_key=True)
    alert_id = db.Column(db.Integer, db.ForeignKey("alerts.id"), nullable=False, index=True)
    user_id = db.Column(db.Integer, db.ForeignKey("users.id"), nullable=True)
    profile_id = db.Column(db.Integer, db.ForeignKey("profiles.id"), nullable=True)
    # Acción realizada: 'created' | 'state_changed' | 'assigned' | 'note_added' | 'escalated' | 'closed'
    action = db.Column(db.String(50), nullable=False)
    previous_state = db.Column(db.String(100), nullable=True)
    new_state = db.Column(db.String(100), nullable=True)
    # Información adicional de la acción en formato texto libre
    detail = db.Column(db.Text, nullable=True)
    timestamp = db.Column(db.DateTime, default=utcnow, index=True)

    # Relaciones
    alert = db.relationship("Alert", back_populates="history")
    user = db.relationship("User", back_populates="history_entries")
    profile = db.relationship("Profile")

    def to_dict(self) -> dict:
        detail = self.detail
        metadata = None
        if self.action in {"fuel_coordinated", "fuel_confirmed"} and detail:
            try:
                metadata = json.loads(detail)
                station = metadata.get("estacion") or {}
                parts = []
                if station.get("name"):
                    parts.append(f"Estación: {station['name']}")
                elif self.action == "fuel_confirmed":
                    parts.append("Confirmación documentada")
                elif metadata.get("modalidad") == "manual":
                    parts.append("Coordinación manual")
                if metadata.get("observacion"):
                    parts.append(f"Observación: {metadata['observacion']}")
                detail = ". ".join(parts)
            except (TypeError, ValueError, json.JSONDecodeError):
                metadata = None
        return {
            "id": self.id,
            "alert_id": self.alert_id,
            "user_id": self.user_id,
            "profile_id": self.profile_id,
            "profile": ({"id": self.profile.id, "name": self.profile.name} if self.profile else None),
            "user": (
                {"id": self.user.id, "full_name": self.user.full_name}
                if self.user
                else None
            ),
            "action": self.action,
            "previous_state": self.previous_state,
            "new_state": self.new_state,
            "detail": detail,
            "metadata": metadata,
            "timestamp": iso_utc(self.timestamp),
        }

    def __repr__(self) -> str:
        return f"<History Alert#{self.alert_id} [{self.action}] at {self.timestamp}>"
