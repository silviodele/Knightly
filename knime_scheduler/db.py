"""Connessione al database (SQLite di default)."""

from pathlib import Path

from sqlalchemy import Engine, create_engine, inspect, text
from sqlalchemy.orm import Session, sessionmaker

from .models import Base


def make_session_factory(url: str) -> sessionmaker[Session]:
    """Crea engine e tabelle; per SQLite crea anche la cartella del file."""
    if url.startswith("sqlite:///"):
        Path(url.removeprefix("sqlite:///")).parent.mkdir(parents=True, exist_ok=True)
    engine = create_engine(url)
    Base.metadata.create_all(engine)
    _add_missing_columns(engine)
    return sessionmaker(bind=engine, expire_on_commit=False)


def _add_missing_columns(engine: Engine) -> None:
    """Migrazione minima: aggiunge le colonne nullable introdotte dopo la creazione delle tabelle."""
    inspector = inspect(engine)
    with engine.begin() as conn:
        for table in Base.metadata.sorted_tables:
            existing = {c["name"] for c in inspector.get_columns(table.name)}
            for column in table.columns:
                if column.name not in existing and column.nullable:
                    col_type = column.type.compile(engine.dialect)
                    conn.execute(text(f'ALTER TABLE "{table.name}" ADD COLUMN "{column.name}" {col_type}'))
