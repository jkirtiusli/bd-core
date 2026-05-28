# -*- coding: utf-8 -*-
"""
Core API (v1, local).
- POST /ingest : recibe registros del Agente (idempotente).
- GET endpoints: sirven datos y calculan derivados (postura %, etc.) para "Huevos K".
"""
import datetime as dt
from typing import Optional, List
from fastapi import FastAPI, Header, HTTPException
from pydantic import BaseModel
from sqlalchemy.dialects.sqlite import insert as sqlite_insert
from sqlalchemy import select, func

from core_app.db import init_db, SessionLocal, Registro

app = FastAPI(title="Core Granjas", version="1.0")

# Token simple para el push del Agente (en produccion: uno por granja)
TOKEN_INGESTA = "DEV_TOKEN_LOCAL"

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
    db = SessionLocal()
    insertados = 0
    try:
        for r in registros:
            stmt = sqlite_insert(Registro).values(
                granja=r.granja, galpon=r.galpon, ciclo=r.ciclo, metrica=r.metrica,
                fecha_dato=dt.date.fromisoformat(r.fecha_dato),
                hora_cierre=r.hora_cierre, zona_horaria=r.zona_horaria,
                valor=r.valor, edad_dia=r.edad_dia, semana=r.semana, fuente=r.fuente,
            )
            # idempotente: si ya existe (mismo galpon/metrica/fecha), actualiza el valor
            stmt = stmt.on_conflict_do_update(
                index_elements=["granja","galpon","ciclo","metrica","fecha_dato"],
                set_={"valor": r.valor, "edad_dia": r.edad_dia, "semana": r.semana},
            )
            db.execute(stmt)
            insertados += 1
        db.commit()
    finally:
        db.close()
    return {"recibidos": len(registros), "procesados": insertados}

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
