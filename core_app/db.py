# -*- coding: utf-8 -*-
"""
Capa de base de datos. SQLite hoy, Postgres manana.
La portabilidad esta aqui: cambiar DATABASE_URL y nada mas.
"""
import os
from sqlalchemy import create_engine, Column, Integer, String, Date, Float, UniqueConstraint, Index
from sqlalchemy.orm import declarative_base, sessionmaker

# SQLite local por defecto. Para Postgres: postgresql+psycopg://user:pass@host/db
DATABASE_URL = os.environ.get("CORE_DB_URL", "sqlite:///./core.db")

# check_same_thread solo aplica a sqlite
connect_args = {"check_same_thread": False} if DATABASE_URL.startswith("sqlite") else {}
engine = create_engine(DATABASE_URL, connect_args=connect_args)
SessionLocal = sessionmaker(bind=engine, autoflush=False, autocommit=False)
Base = declarative_base()

class Registro(Base):
    __tablename__ = "registros"
    id = Column(Integer, primary_key=True)
    granja = Column(String, nullable=False, index=True)
    galpon = Column(String, nullable=False, index=True)
    ciclo = Column(String, nullable=False)
    metrica = Column(String, nullable=False, index=True)
    fecha_dato = Column(Date, nullable=False, index=True)
    hora_cierre = Column(String)
    zona_horaria = Column(String)
    valor = Column(Float)
    edad_dia = Column(Integer)
    semana = Column(Integer)
    fuente = Column(String)
    # Idempotencia: un valor unico por (granja, galpon, ciclo, metrica, fecha)
    __table_args__ = (
        UniqueConstraint("granja", "galpon", "ciclo", "metrica", "fecha_dato",
                         name="uq_registro"),
    )

def init_db():
    Base.metadata.create_all(engine)
