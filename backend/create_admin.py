"""Crea el primer administrador, solicitando los datos; sin usuario/clave fijos."""
from getpass import getpass
from werkzeug.security import generate_password_hash
from app import create_app
from app.database import invoke

if __name__ == "__main__":
    dni, name, email = input("DNI: ").strip(), input("Nombre: ").strip(), input("Correo: ").strip()
    password = getpass("Contraseña (mínimo 8 caracteres): ")
    if len(password) < 8:
        raise SystemExit("Contraseña demasiado corta")
    with create_app().app_context():
        print("Usuario creado:", invoke("j2f_bootstrap", dni, name, email, generate_password_hash(password)))
