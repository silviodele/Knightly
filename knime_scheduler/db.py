"""Connessione al database (SQLite di default)."""

import os

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

DATABASE_URL = os.environ.get("KNIME_SCHEDULER_DB", "sqlite:///data/knime_scheduler.db")


def make_engine(url: str = DATABASE_URL):
    if url.startswith("sqlite:///") and not url.startswith("sqlite:///:memory:"):
        os.makedirs(os.path.dirname(url.removeprefix("sqlite:///")) or ".", exist_ok=True)
    return create_engine(url)


engine = make_engine()
SessionLocal = sessionmaker(bind=engine, expire_on_commit=False)


def init_db(bind=engine) -> None:
    from .models import Base

    Base.metadata.create_all(bind)
