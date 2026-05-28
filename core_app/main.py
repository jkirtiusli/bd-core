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
            inicio = _fecha_inicio_desde_ciclo(f.ciclo)
            es_activo = False
            if max_global and f.ultima_fecha:
                es_activo = (max_global - f.ultima_fecha).days <= dias_activo
            if activos is True and not es_activo:
                continue
            if activos is False and es_activo:
                continue
            salida.append({
                "galpon": f.galpon,
                "plc": plc,
                "casa": casa,
                "ciclo": f.ciclo,
                "fecha_inicio": str(inicio) if inicio else None,
                "primera_fecha_dato": str(f.primera_fecha),
                "ultima_fecha_dato": str(f.ultima_fecha),
                "edad_dia": f.edad_dia,
                "semana": f.semana,
                "registros": f.registros,
                "activo": es_activo,
            })
        # ordenar: activos primero, luego por galpon
        salida.sort(key=lambda x: (not x["activo"], x["galpon"], x["ciclo"]))
        return salida
    finally:
        db.close()
