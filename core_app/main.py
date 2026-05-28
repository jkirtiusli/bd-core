# -*- coding: utf-8 -*-
"""
Core API (v1, local).
- POST /ingest : recibe registros del Agente (idempotente).
- GET endpoints: sirven datos y calculan derivados (postura %, etc.) para "Huevos K".
"""
import os
import datetime as dt
from typing import Optional, List
from fastapi import FastAPI, Header, HTTPException
from pydantic import BaseModel
from sqlalchemy import select, func

from core_app.db import init_db, SessionLocal, Registro, LoteMaestro, engine

# Upsert dialect-aware: usa la sintaxis correcta segun sea sqlite o postgres
if engine.dialect.name == "postgresql":
    from sqlalchemy.dialects.postgresql import insert as _insert
else:
    from sqlalchemy.dialects.sqlite import insert as _insert

app = FastAPI(title="Core Granjas", version="1.0")

# Token simple para el push del Agente (en produccion: uno por granja)
# Token de ingesta: SIEMPRE desde variable de entorno en produccion.
# Si no esta seteada, usa el de desarrollo (solo sirve en local).
TOKEN_INGESTA = os.environ.get("CORE_INGEST_TOKEN", "DEV_TOKEN_LOCAL")

# Crear tablas al cargar el modulo (idempotente)
init_db()

# ---------- Modelo de entrada (lo que manda el Agente) ----------
class RegistroIn(BaseModel):
    granja: str
    galpon: str
    ciclo: str
    metrica: str
    fecha_dato: str
    hora_cierre: Optional[str] = None
    zona_horaria: Optional[str] = None
    capturado_en: Optional[str] = None
    valor: Optional[float] = None
    edad_dia: Optional[int] = None
    semana: Optional[int] = None
    fuente: Optional[str] = None

# ---------- INGESTA ----------
@app.post("/ingest")
def ingest(registros: List[RegistroIn], authorization: str = Header(default="")):
    if authorization != f"Bearer {TOKEN_INGESTA}":
        raise HTTPException(status_code=401, detail="Token invalido")
    if not registros:
        return {"recibidos": 0, "procesados": 0}

    # 1) Convertir a filas y deduplicar dentro del lote por la clave unica
    #    (Postgres no permite ON CONFLICT afectar la misma fila 2 veces en un comando)
    por_clave = {}
    for r in registros:
        clave = (r.granja, r.galpon, r.ciclo, r.metrica, r.fecha_dato)
        por_clave[clave] = {
            "granja": r.granja, "galpon": r.galpon, "ciclo": r.ciclo, "metrica": r.metrica,
            "fecha_dato": dt.date.fromisoformat(r.fecha_dato),
            "hora_cierre": r.hora_cierre, "zona_horaria": r.zona_horaria,
            "valor": r.valor, "edad_dia": r.edad_dia, "semana": r.semana, "fuente": r.fuente,
        }
    filas = list(por_clave.values())

    db = SessionLocal()
    try:
        # 2) Upsert MASIVO: un solo statement por sub-lote (1 viaje a la base, no 1 por fila)
        SUB = 1000  # filas por statement (bajo el limite de parametros de Postgres)
        for i in range(0, len(filas), SUB):
            bloque = filas[i:i+SUB]
            stmt = _insert(Registro).values(bloque)
            stmt = stmt.on_conflict_do_update(
                index_elements=["granja","galpon","ciclo","metrica","fecha_dato"],
                set_={
                    "valor": stmt.excluded.valor,
                    "edad_dia": stmt.excluded.edad_dia,
                    "semana": stmt.excluded.semana,
                    "hora_cierre": stmt.excluded.hora_cierre,
                    "zona_horaria": stmt.excluded.zona_horaria,
                    "fuente": stmt.excluded.fuente,
                },
            )
            db.execute(stmt)
        db.commit()
    finally:
        db.close()
    return {"recibidos": len(registros), "procesados": len(filas)}

# ---------- LECTURA ----------
@app.get("/galpones")
def galpones():
    db = SessionLocal()
    try:
        q = select(
            Registro.galpon, Registro.ciclo,
            func.max(Registro.fecha_dato).label("ultima_fecha"),
            func.count().label("registros"),
        ).group_by(Registro.galpon, Registro.ciclo)
        filas = db.execute(q).all()
        return [
            {"galpon": f.galpon, "ciclo": f.ciclo,
             "ultima_fecha": str(f.ultima_fecha), "registros": f.registros}
            for f in filas
        ]
    finally:
        db.close()

@app.get("/galpones/{galpon}/serie")
def serie(galpon: str, metrica: str, desde: Optional[str] = None):
    """Serie diaria de una metrica. metrica='postura' se calcula (huevos/aves*100)."""
    db = SessionLocal()
    try:
        if metrica == "postura":
            return _serie_postura(db, galpon, desde)
        q = select(Registro.fecha_dato, Registro.valor, Registro.edad_dia, Registro.semana)\
            .where(Registro.galpon == galpon, Registro.metrica == metrica)
        if desde:
            q = q.where(Registro.fecha_dato >= dt.date.fromisoformat(desde))
        q = q.order_by(Registro.fecha_dato)
        return [{"fecha": str(f.fecha_dato), "valor": f.valor,
                 "edad_dia": f.edad_dia, "semana": f.semana} for f in db.execute(q).all()]
    finally:
        db.close()

def _serie_postura(db, galpon, desde):
    """postura % = huevos / aves_vivas * 100, emparejando por fecha."""
    def traer(metrica):
        q = select(Registro.fecha_dato, Registro.valor)\
            .where(Registro.galpon == galpon, Registro.metrica == metrica)
        if desde:
            q = q.where(Registro.fecha_dato >= dt.date.fromisoformat(desde))
        return {f.fecha_dato: f.valor for f in db.execute(q).all()}
    huevos = traer("huevos")
    aves = traer("aves_vivas")
    salida = []
    for fecha in sorted(huevos.keys()):
        a = aves.get(fecha)
        pct = round(huevos[fecha] / a * 100, 2) if a and a > 0 else None
        salida.append({"fecha": str(fecha), "postura_pct": pct,
                       "huevos": huevos[fecha], "aves": a})
    return salida


# ---------- LOTES ----------
def _fecha_inicio_desde_ciclo(ciclo: str):
    """El ciclo viene como DDMMYYYY (ej '25092024' -> 2024-09-25)."""
    if ciclo and len(ciclo) == 8 and ciclo.isdigit():
        try:
            return dt.date(int(ciclo[4:8]), int(ciclo[2:4]), int(ciclo[0:2]))
        except ValueError:
            return None
    return None

def _partes_galpon(galpon: str):
    """De 'Plc15_House15' saca ('Plc15','House15')."""
    if "_" in galpon:
        plc, _, casa = galpon.partition("_")
        return plc, casa
    return galpon, None

@app.get("/lotes")
def lotes(activos: Optional[bool] = None, dias_activo: int = 3):
    """
    Lista de lotes (galpon + ciclo) con su estado.
    - activos=true  -> solo lotes con datos recientes
    - activos=false -> solo historicos
    - dias_activo   -> margen para considerar 'activo' (default 3 dias)
    """
    db = SessionLocal()
    try:
        # fecha global mas reciente en toda la base (proxy de "hoy con datos")
        max_global = db.execute(select(func.max(Registro.fecha_dato))).scalar()
        maestros = _maestros_dict(db)

        q = select(
            Registro.galpon, Registro.ciclo,
            func.max(Registro.fecha_dato).label("ultima_fecha"),
            func.min(Registro.fecha_dato).label("primera_fecha"),
            func.max(Registro.edad_dia).label("edad_dia"),
            func.max(Registro.semana).label("semana"),
            func.count().label("registros"),
        ).group_by(Registro.galpon, Registro.ciclo)

        salida = []
        for f in db.execute(q).all():
            plc, casa = _partes_galpon(f.galpon)
            inicio_ciclo = _fecha_inicio_desde_ciclo(f.ciclo)
            es_activo = False
            if max_global and f.ultima_fecha:
                es_activo = (max_global - f.ultima_fecha).days <= dias_activo
            if activos is True and not es_activo:
                continue
            if activos is False and es_activo:
                continue

            # Ficha maestra (si existe): la fecha_encasetado es la FUENTE DE VERDAD de la edad
            m = maestros.get((f.galpon, f.ciclo))
            fecha_enc = m.fecha_encasetado if m and m.fecha_encasetado else None
            ref = max_global if es_activo else f.ultima_fecha  # hasta cuando medir la edad
            if fecha_enc and ref:
                edad_real = (ref - fecha_enc).days
                semana_real = edad_real // 7
                fuente_edad = "maestro"
            else:
                edad_real = None
                semana_real = None
                fuente_edad = "sin_dato"  # el edad_dia del PLC no es confiable, no lo usamos como edad real

            salida.append({
                "galpon": f.galpon,
                "plc": plc,
                "casa": casa,
                "ciclo": f.ciclo,
                "fecha_inicio_carpeta": str(inicio_ciclo) if inicio_ciclo else None,
                "primera_fecha_dato": str(f.primera_fecha),
                "ultima_fecha_dato": str(f.ultima_fecha),
                "registros": f.registros,
                "activo": es_activo,
                # --- edad: solo confiable si hay ficha maestra ---
                "fecha_encasetado": str(fecha_enc) if fecha_enc else None,
                "edad_dia": edad_real,
                "semana": semana_real,
                "edad_fuente": fuente_edad,
                "edad_dia_plc": f.edad_dia,   # lo del PLC, a titulo informativo (no confiable)
                # --- datos maestros ---
                "raza": m.raza if m else None,
                "aves_iniciales": m.aves_iniciales if m else None,
                "encargado": m.encargado if m else None,
                "etiqueta": m.etiqueta if m else None,
            })
        # ordenar: activos primero, luego por galpon
        salida.sort(key=lambda x: (not x["activo"], x["galpon"], x["ciclo"]))
        return salida
    finally:
        db.close()


# ---------- DATOS MAESTROS (ficha editable del lote) ----------
class LoteMaestroIn(BaseModel):
    galpon: str
    ciclo: str
    fecha_encasetado: Optional[str] = None
    raza: Optional[str] = None
    aves_iniciales: Optional[int] = None
    encargado: Optional[str] = None
    etiqueta: Optional[str] = None
    notas: Optional[str] = None

@app.put("/lotes/maestro")
def upsert_maestro(m: LoteMaestroIn):
    """Crea o actualiza la ficha maestra de un lote (galpon+ciclo)."""
    db = SessionLocal()
    try:
        vals = dict(
            galpon=m.galpon, ciclo=m.ciclo,
            fecha_encasetado=dt.date.fromisoformat(m.fecha_encasetado) if m.fecha_encasetado else None,
            raza=m.raza, aves_iniciales=m.aves_iniciales,
            encargado=m.encargado, etiqueta=m.etiqueta, notas=m.notas,
        )
        stmt = _insert(LoteMaestro).values(**vals)
        actualizable = {k: v for k, v in vals.items() if k not in ("galpon", "ciclo")}
        stmt = stmt.on_conflict_do_update(
            index_elements=["galpon", "ciclo"], set_=actualizable)
        db.execute(stmt)
        db.commit()
        return {"ok": True, "galpon": m.galpon, "ciclo": m.ciclo}
    finally:
        db.close()

def _maestros_dict(db):
    """Devuelve {(galpon,ciclo): fila_maestro} para combinar con /lotes."""
    out = {}
    for f in db.execute(select(LoteMaestro)).scalars().all():
        out[(f.galpon, f.ciclo)] = f
    return out
