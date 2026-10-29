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
        if self.action == "note_added" and detail:
            try:
                candidate = json.loads(detail)
                if (isinstance(candidate, dict) and candidate.get("kind") == "assignment_note"
                        and isinstance(candidate.get("text"), str)):
                    metadata = candidate
                    detail = candidate["text"]
            except (TypeError, ValueError):
                pass  # Auditorías antiguas: conservar literalmente, sin adivinar autores ni contenido.
        if self.action in {"fuel_coordinated", "fuel_confirmed"} and detail:
            try:
                metadata = json.loads(detail)
                if not isinstance(metadata, dict):
                    raise ValueError('El detalle de combustible debe ser un objeto')
                station = metadata.get("estacion") or {}
                if not isinstance(station, dict):
                    raise ValueError('La estación registrada debe ser un objeto')
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
            except (TypeError, ValueError):
                metadata = None
        author = {"id": self.user.id, "full_name": self.user.full_name} if self.user else None
        profile = {"id": self.profile.id, "name": self.profile.name} if self.profile else None
        if self.action == 'note_added' and metadata:
            author_snapshot = metadata.get('author')
            profile_snapshot = metadata.get('profile')
            if (isinstance(author_snapshot, dict) and author_snapshot.get('id') == self.user_id
                    and isinstance(author_snapshot.get('full_name'), str)):
                author = author_snapshot
            if (isinstance(profile_snapshot, dict) and profile_snapshot.get('id') == self.profile_id
                    and isinstance(profile_snapshot.get('name'), str)):
                profile = profile_snapshot
        return {
            "id": self.id,
            "alert_id": self.alert_id,
            "user_id": self.user_id,
            "profile_id": self.profile_id,
            "profile": profile,
            "user": author,
            "action": self.action,
            "previous_state": self.previous_state,
            "new_state": self.new_state,
            "detail": detail,
            "metadata": metadata,
            "timestamp": iso_utc(self.timestamp),
        }

    def __repr__(self) -> str:
        return f"<History Alert#{self.alert_id} [{self.action}] at {self.timestamp}>"
