"""Applicazione FastAPI: API JSON sotto /api, pagine HTML (Jinja2 + HTMX) sotto /."""

import os
from collections.abc import Iterator
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI, HTTPException, Request
from fastapi.staticfiles import StaticFiles
from sqlalchemy.orm import Session

from .db import make_session_factory
from .scheduler import SchedulerService

HERE = Path(__file__).parent


def create_app(
    data_dir: str | Path | None = None,
    database_url: str | None = None,
    start_scheduler: bool = True,
    max_workers: int = 4,
    launcher: list[str] | None = None,
) -> FastAPI:
    data_dir = Path(data_dir or os.environ.get("KNIME_SCHEDULER_DATA", "data"))
    database_url = database_url or os.environ.get(
        "KNIME_SCHEDULER_DB", f"sqlite:///{(data_dir / 'knime_scheduler.db').as_posix()}"
    )
    session_factory = make_session_factory(database_url)
    service = SchedulerService(
        session_factory, logs_dir=data_dir / "logs", max_workers=max_workers, launcher=launcher
    )

    @asynccontextmanager
    async def lifespan(app: FastAPI):
        if start_scheduler:
            service.start()
        yield
        service.shutdown(cancel_running=True)

    app = FastAPI(title="knime-scheduler", lifespan=lifespan)
    app.state.session_factory = session_factory
    app.state.service = service
    app.state.workflows_dir = data_dir / "workflows"

    from . import api, web

    app.mount("/static", StaticFiles(directory=HERE / "static"), name="static")
    app.include_router(api.router)
    app.include_router(web.router)
    return app


# --- dipendenze FastAPI ------------------------------------------------------

def get_session(request: Request) -> Iterator[Session]:
    with request.app.state.session_factory() as session:
        yield session


def get_service(request: Request) -> SchedulerService:
    return request.app.state.service


def get_or_404(s: Session, model, obj_id: int):
    obj = s.get(model, obj_id)
    if obj is None:
        raise HTTPException(404, f"{model.__name__} {obj_id} non trovato")
    return obj
