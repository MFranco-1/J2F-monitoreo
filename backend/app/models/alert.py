"""
models/alert.py - Modelo Alerta (Alert)
Entidad central del sistema de monitoreo.
"""

from app.datetime_utils import utcnow, as_utc_naive, iso_utc
from app import db


class Alert(db.Model):
    __tablename__ = "alerts"

    id = db.Column(db.Integer, primary_key=True)
    title = db.Column(db.String(200), nullable=False)
    description = db.Column(db.Text, nullable=True)
    # 'critical' | 'high' | 'medium' | 'low'
    priority = db.Column(db.String(20), nullable=False, default="medium", index=True)
    # Tipo de servicio afectado (ej: Red, Servidor, Aplicación)
    service_type = db.Column(db.String(100), nullable=True)
    # Lugar / ubicación donde se origina la alerta
    location = db.Column(db.String(200), nullable=True)
    # Fuente de la alerta (ej: SNMP, Manual, API externa)
    source = db.Column(db.String(100), nullable=True, default="Manual")
    state_id = db.Column(db.Integer, db.ForeignKey("states.id"), nullable=False, index=True)
    vehicle_id = db.Column(db.Integer, db.ForeignKey("vehicles.id"), nullable=True, index=True)
    gps_device_id = db.Column(db.Integer, db.ForeignKey("gps_devices.id"), nullable=True, index=True)
    event_type_id = db.Column(db.Integer, db.ForeignKey("event_types.id"), nullable=True, index=True)
    # Usuario que creó la alerta
    created_by = db.Column(db.Integer, db.ForeignKey("users.id"), nullable=True)
    # Tiempos de respuesta
    opened_at = db.Column(db.DateTime, default=utcnow)
    acknowledged_at = db.Column(db.DateTime, nullable=True)
    resolved_at = db.Column(db.DateTime, nullable=True)
    created_at = db.Column(db.DateTime, default=utcnow)
    updated_at = db.Column(
        db.DateTime,
        default=utcnow,
        onupdate=utcnow,
    )

    # Relaciones
    state = db.relationship("State", back_populates="alerts")
    creator = db.relationship("User", foreign_keys=[created_by])
    vehicle = db.relationship("Vehicle", back_populates="alerts")
    gps_device = db.relationship("GpsDevice", back_populates="alerts")
    event_type = db.relationship("EventType", back_populates="alerts")
    assignments = db.relationship("Assignment", back_populates="alert", lazy="dynamic", cascade="all, delete-orphan")
    history = db.relationship("History", back_populates="alert", lazy="dynamic", cascade="all, delete-orphan")

    @property
    def response_time_minutes(self) -> float | None:
        """Calcula el tiempo de respuesta en minutos desde apertura hasta cierre."""
        if self.opened_at and self.resolved_at:
            delta = as_utc_naive(self.resolved_at) - as_utc_naive(self.opened_at)
            return round(delta.total_seconds() / 60, 2)
        return None

    @property
    def current_assignee(self):
        """Retorna el operador actualmente asignado a esta alerta."""
        latest = self.assignments.filter_by(completed_at=None).order_by(
            db.desc("assigned_at"), db.desc("id")
        ).first()
        return latest.user if latest else None

    def to_dict(self, include_history: bool = False) -> dict:
        data = {
            "id": self.id,
            "title": self.title,
            "description": self.description,
            "priority": self.priority,
            "service_type": self.service_type,
            "location": self.location,
            "source": self.source,
            "state_id": self.state_id,
            "state": self.state.to_dict() if self.state else None,
            "created_by": self.created_by,
            "vehicle_id": self.vehicle_id,
            "gps_device_id": self.gps_device_id,
            "event_type_id": self.event_type_id,
            "vehicle": self.vehicle.to_dict(include_client=True) if self.vehicle else None,
            "client": self.vehicle.client.to_dict() if self.vehicle and self.vehicle.client else None,
            "gps_device": self.gps_device.to_dict() if self.gps_device else None,
            "event_type": self.event_type.to_dict() if self.event_type else None,
            "opened_at": iso_utc(self.opened_at),
            "acknowledged_at": iso_utc(self.acknowledged_at),
            "resolved_at": iso_utc(self.resolved_at),
            "response_time_minutes": self.response_time_minutes,
            "created_at": iso_utc(self.created_at),
            "updated_at": iso_utc(self.updated_at),
        }
        assignee = self.current_assignee
        data["current_assignee"] = assignee.to_dict(include_profile=False) if assignee else None

        if include_history:
            data["history"] = [h.to_dict() for h in self.history.order_by("timestamp")]
        return data

    def __repr__(self) -> str:
        return f"<Alert #{self.id} [{self.priority}]: {self.title}>"
