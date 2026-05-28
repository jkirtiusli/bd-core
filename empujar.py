# -*- coding: utf-8 -*-
"""
Lee un JSON de registros normalizados y los empuja al Core en lotes.
Uso:
    python3 empujar.py /ruta/a/datos_normalizados.json
    python3 empujar.py /ruta/a/datos_normalizados.json http://127.0.0.1:8000/ingest DEV_TOKEN_LOCAL
"""
import sys, json, time, urllib.request

ARCHIVO = sys.argv[1] if len(sys.argv) > 1 else "datos_normalizados.json"
URL     = sys.argv[2] if len(sys.argv) > 2 else "http://127.0.0.1:8000/ingest"
TOKEN   = sys.argv[3] if len(sys.argv) > 3 else "DEV_TOKEN_LOCAL"
LOTE    = 2000

with open(ARCHIVO, encoding="utf-8") as f:
    registros = json.load(f)

total = len(registros)
print(f"Leidos {total} registros de {ARCHIVO}")
print(f"Empujando a {URL} en lotes de {LOTE}...")

enviados = 0
t0 = time.time()
for i in range(0, total, LOTE):
    bloque = registros[i:i+LOTE]
    body = json.dumps(bloque, ensure_ascii=False).encode("utf-8")
    req = urllib.request.Request(URL, data=body, method="POST")
    req.add_header("Content-Type", "application/json")
    req.add_header("Authorization", f"Bearer {TOKEN}")
    try:
        with urllib.request.urlopen(req, timeout=120) as resp:
            if resp.status not in (200, 201):
                print(f"  ! lote {i}: HTTP {resp.status}")
    except Exception as e:
        print(f"  ! error en lote {i}: {e}")
        break
    enviados += len(bloque)
    print(f"  {enviados}/{total} ...", end="\r")

print()
print(f"Listo: {enviados}/{total} enviados en {round(time.time()-t0,1)}s")
