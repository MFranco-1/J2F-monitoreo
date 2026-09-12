"""Rutas de consulta y mantenimiento de datos maestros."""
from flask import Blueprint, request
from flask_jwt_extended import jwt_required
from app.security import admin_required
from app.controllers import master_data_controller

master_data_bp = Blueprint("master_data", __name__)


@master_data_bp.get("/<kind>/")
@jwt_required()
def list_records(kind):
    if kind not in master_data_controller.MODELS:
        return {"error": "Dato maestro no reconocido"}, 404
    return master_data_controller.list_records(kind, request.args)


@master_data_bp.get("/<kind>/<int:record_id>")
@jwt_required()
def get_record(kind, record_id):
    if kind not in master_data_controller.MODELS:
        return {"error": "Dato maestro no reconocido"}, 404
    return master_data_controller.get_record(kind, record_id)


@master_data_bp.post("/<kind>/")
@jwt_required()
@admin_required
def create_record(kind):
    if kind not in master_data_controller.MODELS:
        return {"error": "Dato maestro no reconocido"}, 404
    return master_data_controller.create_record(kind, request.get_json(silent=True) or {})


@master_data_bp.put("/<kind>/<int:record_id>")
@jwt_required()
@admin_required
def update_record(kind, record_id):
    if kind not in master_data_controller.MODELS:
        return {"error": "Dato maestro no reconocido"}, 404
    return master_data_controller.update_record(kind, record_id, request.get_json(silent=True) or {})


@master_data_bp.delete("/<kind>/<int:record_id>")
@jwt_required()
@admin_required
def delete_record(kind, record_id):
    if kind not in master_data_controller.MODELS:
        return {"error": "Dato maestro no reconocido"}, 404
    return master_data_controller.delete_record(kind, record_id)
