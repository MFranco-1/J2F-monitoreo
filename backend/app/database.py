"""Único acceso a datos: nombres de subprogramas y parámetros, sin consultas SQL."""
from contextlib import contextmanager
import re
import psycopg2
from psycopg2.extras import Json
from sqlalchemy.exc import DBAPIError, TimeoutError as PoolTimeout
from flask import current_app

@contextmanager
def connection():
    engine = current_app.extensions["postgres_engine"]
    try:
        conn = engine.raw_connection()
    except DBAPIError as error:
        raise error.orig from None
    except PoolTimeout:
        raise psycopg2.OperationalError("No hay una conexión disponible") from None
    try:
        yield conn
    except psycopg2.Error:
        if conn.driver_connection.closed:
            conn.invalidate()
        raise
    finally:
        # Devuelve la conexión al pool; una transacción fallida se revierte antes del próximo uso.
        conn.close()

def call_routine(cursor, name, *parameters):
    cursor.callproc(name, [Json(p) if isinstance(p, (dict, list)) else p for p in parameters])
    return utc_json(cursor.fetchone()[0])


def invoke(name, *parameters):
    # El nombre proviene del backend, nunca de un parámetro HTTP.
    with connection() as conn:
        with conn.cursor() as cursor:
            value = call_routine(cursor, name, *parameters)
        conn.commit()
        return value


def utc_json(value):
    if isinstance(value, dict):
        return {key: utc_json(item) for key, item in value.items()}
    if isinstance(value, list):
        return [utc_json(item) for item in value]
    if isinstance(value, str) and re.fullmatch(r"\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}(?:\.\d+)?", value):
        return value + "Z"
    return value
