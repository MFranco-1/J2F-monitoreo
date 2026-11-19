"""Servicios geográficos; no fabrican estaciones ni rutas si falla el proveedor."""
import json
from urllib.error import HTTPError, URLError
from urllib.parse import urlencode
from urllib.request import Request, urlopen
from flask import abort, current_app, request
from app.api import validate_coordinates
from app.database import invoke

def external(url, data=None):
    try:
        req = Request(url, data=data, headers={"User-Agent": "J2F-Monitoreo", "Content-Type": "application/x-www-form-urlencoded"})
        with urlopen(req, timeout=current_app.config["MAP_SERVICE_TIMEOUT"]) as response:
            return json.load(response)
    except (HTTPError, URLError, TimeoutError, ValueError):
        abort(502, "No se pudo consultar el servicio geográfico")

def access(operation):
    raw = request.args.get("alert_id")
    if raw:
        try:
            operation("alerts", "access", int(raw))
        except ValueError:
            abort(400, "Identificador inválido")
    else:
        # Sin alerta se exige una consulta autorizada de la flota.
        operation("alerts", "map")

def fuel_stations(operation):
    access(operation)
    lat, lng = validate_coordinates(request.args.get("latitude"), request.args.get("longitude"))
    settings = invoke("j2f_param", "station_search")
    try:
        radius = int(request.args.get("radius", settings["radius"]))
    except ValueError:
        abort(400, "Radio inválido")
    if not settings["minimum"] <= radius <= settings["maximum"]:
        abort(400, "Radio fuera del rango permitido")
    query = f'[out:json][timeout:{settings["timeout"]}];nwr["amenity"="fuel"](around:{radius},{lat},{lng});out center tags;'
    payload = external(current_app.config["OVERPASS_API_URL"], urlencode({"data": query}).encode())
    stations = []
    for item in payload.get("elements", []):
        center, tags = item.get("center", item), item.get("tags", {})
        if center.get("lat") is not None and center.get("lon") is not None:
            stations.append({"id": f'{item.get("type")}-{item.get("id")}', "name": tags.get("name") or tags.get("brand") or "Estación sin nombre registrado", "brand": tags.get("brand"), "latitude": center["lat"], "longitude": center["lon"]})
    return {"stations": stations, "source": "OpenStreetMap"}

def street_route(operation):
    access(operation)
    a, b = validate_coordinates(request.args.get("origin_lat"), request.args.get("origin_lng"))
    c, d = validate_coordinates(request.args.get("destination_lat"), request.args.get("destination_lng"))
    endpoint = current_app.config["ROUTING_API_URL"].rstrip("/")
    payload = external(f"{endpoint}/route/v1/driving/{b},{a};{d},{c}?overview=full&geometries=geojson&steps=false")
    routes = payload.get("routes", [])
    if payload.get("code") != "Ok" or not routes:
        abort(404, "No se encontró una ruta por calles")
    route = routes[0]
    return {"coordinates": [[lat, lng] for lng, lat in route["geometry"]["coordinates"]], "distance": route["distance"], "duration": route["duration"]}
