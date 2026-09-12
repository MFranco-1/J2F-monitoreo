"""Datos maestros de clientes, vehículos, GPS y tipos de evento."""
from app import db
from app.datetime_utils import utcnow, iso_utc


class TimestampStateMixin:
    state_id = db.Column(db.Integer, db.ForeignKey("states.id"), nullable=False, index=True)
    created_at = db.Column(db.DateTime, default=utcnow)
    updated_at = db.Column(db.DateTime, default=utcnow, onupdate=utcnow)

    @property
    def is_active(self):
        return bool(self.state and self.state.name == "Activo")


class Client(TimestampStateMixin, db.Model):
    __tablename__ = "clients"
    id = db.Column(db.Integer, primary_key=True)
    document_type = db.Column(db.String(20), nullable=False)
    document_number = db.Column(db.String(30), nullable=False, unique=True, index=True)
    business_name = db.Column(db.String(180), nullable=False)
    contact_name = db.Column(db.String(150))
    phone = db.Column(db.String(30))
    email = db.Column(db.String(150))
    address = db.Column(db.String(255))
    state = db.relationship("State", back_populates="clients")
    vehicles = db.relationship("Vehicle", back_populates="client", lazy="dynamic")

    def to_dict(self):
        return {"id": self.id, "document_type": self.document_type,
                "document_number": self.document_number, "business_name": self.business_name,
                "contact_name": self.contact_name, "phone": self.phone, "email": self.email,
                "address": self.address, "state_id": self.state_id,
                "state": self.state.to_dict() if self.state else None,
                "created_at": iso_utc(self.created_at), "updated_at": iso_utc(self.updated_at)}


class Vehicle(TimestampStateMixin, db.Model):
    __tablename__ = "vehicles"
    id = db.Column(db.Integer, primary_key=True)
    client_id = db.Column(db.Integer, db.ForeignKey("clients.id"), nullable=False, index=True)
    plate = db.Column(db.String(20), nullable=False, unique=True, index=True)
    brand = db.Column(db.String(100))
    model = db.Column(db.String(100))
    color = db.Column(db.String(50))
    vehicle_type = db.Column(db.String(80))
    state = db.relationship("State", back_populates="vehicles")
    client = db.relationship("Client", back_populates="vehicles")
    gps_devices = db.relationship("GpsDevice", back_populates="vehicle", lazy="dynamic")
    alerts = db.relationship("Alert", back_populates="vehicle", lazy="dynamic")

    def to_dict(self, include_client=False):
        data = {"id": self.id, "client_id": self.client_id, "plate": self.plate,
                "brand": self.brand, "model": self.model, "color": self.color,
                "vehicle_type": self.vehicle_type, "state_id": self.state_id,
                "state": self.state.to_dict() if self.state else None,
                "created_at": iso_utc(self.created_at), "updated_at": iso_utc(self.updated_at)}
        if include_client:
            data["client"] = self.client.to_dict() if self.client else None
        return data


class GpsDevice(TimestampStateMixin, db.Model):
    __tablename__ = "gps_devices"
    id = db.Column(db.Integer, primary_key=True)
    vehicle_id = db.Column(db.Integer, db.ForeignKey("vehicles.id"), nullable=False, index=True)
    imei = db.Column(db.String(40), nullable=False, unique=True, index=True)
    serial_number = db.Column(db.String(80), unique=True)
    model = db.Column(db.String(100))
    provider = db.Column(db.String(100))
    sim_number = db.Column(db.String(30))
    state = db.relationship("State", back_populates="gps_devices")
    vehicle = db.relationship("Vehicle", back_populates="gps_devices")
    alerts = db.relationship("Alert", back_populates="gps_device", lazy="dynamic")

    def to_dict(self, include_vehicle=False):
        data = {"id": self.id, "vehicle_id": self.vehicle_id, "imei": self.imei,
                "serial_number": self.serial_number, "model": self.model,
                "provider": self.provider, "sim_number": self.sim_number,
                "state_id": self.state_id, "state": self.state.to_dict() if self.state else None,
                "created_at": iso_utc(self.created_at), "updated_at": iso_utc(self.updated_at)}
        if include_vehicle:
            data["vehicle"] = self.vehicle.to_dict(include_client=True) if self.vehicle else None
        return data


class EventType(TimestampStateMixin, db.Model):
    __tablename__ = "event_types"
    id = db.Column(db.Integer, primary_key=True)
    code = db.Column(db.String(50), nullable=False, unique=True, index=True)
    name = db.Column(db.String(150), nullable=False)
    description = db.Column(db.Text)
    default_priority = db.Column(db.String(20), nullable=False, default="medium")
    generates_alert = db.Column(db.Boolean, nullable=False, default=True)
    expected_action = db.Column(db.Text)
    state = db.relationship("State", back_populates="event_types")
    alerts = db.relationship("Alert", back_populates="event_type", lazy="dynamic")

    def to_dict(self):
        return {"id": self.id, "code": self.code, "name": self.name,
                "description": self.description, "default_priority": self.default_priority,
                "generates_alert": self.generates_alert, "expected_action": self.expected_action,
                "state_id": self.state_id, "state": self.state.to_dict() if self.state else None,
                "created_at": iso_utc(self.created_at), "updated_at": iso_utc(self.updated_at)}
