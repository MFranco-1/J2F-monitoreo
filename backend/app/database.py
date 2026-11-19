"""Único acceso a datos: nombres de subprogramas y parámetros, sin consultas SQL."""
from contextlib import contextmanager
import re
import psycopg2
from psycopg2.extras import Json
from flask import current_app

@contextmanager
def connection():
    url = current_app.config["SQLALCHEMY_DATABASE_URI"]
    conn = psycopg2.connect(url.set(drivername="postgresql").render_as_string(hide_password=False))
    try:
        yield conn
    finally:
        conn.close()

def invoke(name, *parameters):
    # El nombre proviene del backend, nunca de un parámetro HTTP.
    with connection() as conn:
        with conn.cursor() as cursor:
            cursor.callproc(name, [Json(p) if isinstance(p, (dict, list)) else p for p in parameters])
            value = cursor.fetchone()[0]
        conn.commit()
        return utc_json(value)


def utc_json(value):
    if isinstance(value, dict):
        return {key: utc_json(item) for key, item in value.items()}
    if isinstance(value, list):
        return [utc_json(item) for item in value]
    if isinstance(value, str) and re.fullmatch(r"\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}(?:\.\d+)?", value):
        return value + "Z"
    return value
