# Core Granjas (v1, local)

API que recibe los datos del Agente, los guarda y calcula derivados (postura %, etc.).
SQLite hoy; migrable a PostgreSQL/Supabase cambiando CORE_DB_URL.

## Instalar
    pip install -r requirements.txt

## Levantar (local)
    python -m uvicorn core_app.main:app --host 127.0.0.1 --port 8000

Queda escuchando en http://127.0.0.1:8000
Documentacion interactiva automatica: http://127.0.0.1:8000/docs

## Endpoints
- POST /ingest               recibe registros del Agente (requiere token)
- GET  /galpones             lista galpones con ultima fecha y conteo
- GET  /galpones/{id}/serie?metrica=huevos
- GET  /galpones/{id}/serie?metrica=postura   (CALCULADO: huevos/aves*100)
- GET  /lotes                lista de lotes con fecha inicio, edad, estado activo/historico
- GET  /lotes?activos=true   solo lotes en produccion
- GET  /lotes?activos=false  solo lotes historicos

## Token de ingesta
Definido en core_app/main.py (TOKEN_INGESTA = "DEV_TOKEN_LOCAL").
El Agente debe usar el mismo token en su config (destino.token).

## Migrar a PostgreSQL/Supabase (despues)
Definir variable de entorno antes de levantar:
    set CORE_DB_URL=postgresql+psycopg://usuario:pass@host:5432/basedatos
El resto del codigo no cambia.

## Base de datos
SQLite genera el archivo core.db en la carpeta donde se levanta.
