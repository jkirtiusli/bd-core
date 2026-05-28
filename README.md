# Core Granjas

API que recibe los datos del Agente, los guarda CRUDOS y calcula derivados
(postura %, edad real, etc.) al momento de servir. SQLite o PostgreSQL (Neon).

## Instalar
    pip install -r requirements.txt

## Base de datos: SQLite (local, pruebas) o Postgres/Neon (produccion)
Por defecto usa SQLite (archivo core.db). Para usar Neon, define la variable
de entorno CORE_DB_URL ANTES de crear tablas o levantar el Core.

Mac / Linux:
    export CORE_DB_URL="postgresql+psycopg://USUARIO:PASS@ep-xxx.neon.tech/dbname?sslmode=require"

Windows (cmd):
    set CORE_DB_URL=postgresql+psycopg://USUARIO:PASS@ep-xxx.neon.tech/dbname?sslmode=require

IMPORTANTE: Neon entrega la cadena como "postgresql://...".
Cambia el prefijo a "postgresql+psycopg://..." (agrega +psycopg).

## Crear las tablas (una vez)
    python crear_tablas.py
Crea: registros, lotes_maestros. No borra datos si ya existen.

## Levantar el Core
    python -m uvicorn core_app.main:app --host 0.0.0.0 --port 8000
Docs interactivas: http://localhost:8000/docs

## Endpoints
- POST /ingest                     recibe registros del Agente (token)
- GET  /galpones
- GET  /galpones/{id}/serie?metrica=huevos|aves_vivas|postura|...
- GET  /lotes                      lotes con edad REAL (si hay ficha maestra)
- GET  /lotes?activos=true|false
- PUT  /lotes/maestro              carga/edita ficha del lote (fecha_encasetado, raza, etc.)

## Nota sobre la edad
El edad_dia del PLC NO es confiable. El Core solo reporta edad real cuando
existe una ficha maestra con fecha_encasetado (cargada via PUT /lotes/maestro).

## Desplegar en la nube (Render)

El Core necesita estar en internet para que las granjas le empujen datos.

Variables de entorno a configurar en el panel de Render (NO van al repo):
- CORE_DB_URL        -> tu cadena de Neon con prefijo postgresql+psycopg://
- CORE_INGEST_TOKEN  -> un token secreto largo (lo invents vos), el Agente usa el mismo

Pasos (Render):
1. Subi este repo a GitHub.
2. En render.com -> New -> Web Service -> conecta el repo.
3. Render detecta render.yaml. Si pide comandos:
   Build:  pip install -r requirements.txt && python crear_tablas.py
   Start:  uvicorn core_app.main:app --host 0.0.0.0 --port $PORT
4. En Environment, agrega CORE_DB_URL y CORE_INGEST_TOKEN.
5. Deploy. Te da una URL https://bd-core-xxxx.onrender.com

Luego el Agente apunta su destino.url a esa URL + /ingest y usa el mismo token.
