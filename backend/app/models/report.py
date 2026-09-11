"""
models/report.py - Modelo Reporte (Report)
Almacena metadatos de los informes generados por el sistema.
"""

from app.datetime_utils import utcnow, as_utc_naive, iso_utc
from app import db


class Report(db.Model):
    __tablename__ = "reports"

    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(200), nullable=False)
    # 'alerts_summary' | 'operator_performance' | 'response_times' | 'custom'
    type = db.Column(db.String(50), nullable=False)
    description = db.Column(db.Text, nullable=True)
    # Filtros aplicados al reporte (guardados como JSON string)
    filters_json = db.Column(db.Text, nullable=True)
    date_range_start = db.Column(db.DateTime, nullable=True)
    date_range_end = db.Column(db.DateTime, nullable=True)
    generated_by = db.Column(db.Integer, db.ForeignKey("users.id"), nullable=True)
    # Resultado del reporte en JSON (para reportes pequeños) o ruta a archivo
    result_json = db.Column(db.Text, nullable=True)
    created_at = db.Column(db.DateTime, default=utcnow)

    # Relaciones
    generator = db.relationship("User", foreign_keys=[generated_by])

    def to_dict(self, include_result: bool = False) -> dict:
        data = {
            "id": self.id,
            "name": self.name,
            "type": self.type,
            "has_result": bool(self.result_json),
            "description": self.description,
            "date_range_start": iso_utc(self.date_range_start),
            "date_range_end": iso_utc(self.date_range_end),
            "generated_by": self.generated_by,
            "generator": (
                {"id": self.generator.id, "full_name": self.generator.full_name}
                if self.generator
                else None
            ),
            "created_at": iso_utc(self.created_at),
        }
        if include_result:
            data["result_json"] = self.result_json
        return data

    def __repr__(self) -> str:
        return f"<Report #{self.id} '{self.name}' [{self.type}]>"
