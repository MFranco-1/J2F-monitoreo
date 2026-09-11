"""
models/assignment.py - Modelo Asignación (Assignment)
Registra qué operador atiende qué alerta y sus notas de atención.
"""

from app.datetime_utils import utcnow, as_utc_naive, iso_utc
from app import db


class Assignment(db.Model):
    __tablename__ = "assignments"

    id = db.Column(db.Integer, primary_key=True)
    alert_id = db.Column(db.Integer, db.ForeignKey("alerts.id"), nullable=False, index=True)
    user_id = db.Column(db.Integer, db.ForeignKey("users.id"), nullable=False, index=True)
    notes = db.Column(db.Text, nullable=True)
    # Tipo de asignación: 'manual' | 'auto'
    assignment_type = db.Column(db.String(20), default="manual")
    assigned_at = db.Column(db.DateTime, default=utcnow)
    completed_at = db.Column(db.DateTime, nullable=True)
    # Tiempo de respuesta real en minutos (se calcula al cerrar)
    response_time_minutes = db.Column(db.Float, nullable=True)

    # Relaciones
    alert = db.relationship("Alert", back_populates="assignments")
    user = db.relationship("User", back_populates="assignments")

    def complete(self) -> None:
        """Marca la asignación como completada y calcula el tiempo de respuesta."""
        if self.completed_at is not None:
            return
        now = utcnow()
        self.completed_at = now
        if self.assigned_at:
            delta = now - as_utc_naive(self.assigned_at)
            self.response_time_minutes = round(delta.total_seconds() / 60, 2)

    def to_dict(self) -> dict:
        return {
            "id": self.id,
            "alert_id": self.alert_id,
            "user_id": self.user_id,
            "user": self.user.to_dict(include_profile=False) if self.user else None,
            "notes": self.notes,
            "assignment_type": self.assignment_type,
            "assigned_at": iso_utc(self.assigned_at),
            "completed_at": iso_utc(self.completed_at),
            "response_time_minutes": self.response_time_minutes,
        }

    def __repr__(self) -> str:
        return f"<Assignment Alert#{self.alert_id} -> User#{self.user_id}>"
