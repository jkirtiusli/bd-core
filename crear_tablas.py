# -*- coding: utf-8 -*-
"""
Crea las tablas del Core en la base apuntada por CORE_DB_URL.
Funciona igual con SQLite o Postgres (Neon).

Uso:
  1) export/set CORE_DB_URL=postgresql+psycopg://...   (tu cadena de Neon)
  2) python crear_tablas.py
"""
import os
from core_app.db import init_db, engine, Base

def main():
    url = os.environ.get("CORE_DB_URL", "sqlite:///./core.db (por defecto)")
    # ocultar la password al imprimir
    mostrar = url
    if "@" in url and "://" in url:
        proto, resto = url.split("://", 1)
        if "@" in resto:
            cred, host = resto.split("@", 1)
            usuario = cred.split(":")[0]
            mostrar = f"{proto}://{usuario}:****@{host}"
    print("Conectando a:", mostrar)
    print("Motor detectado:", engine.dialect.name)
    init_db()
    # listar las tablas creadas
    tablas = list(Base.metadata.tables.keys())
    print("Tablas creadas/verificadas:", ", ".join(tablas))
    print("OK")

if __name__ == "__main__":
    main()
