"""API REST JSON."""

import asyncio
import json
from pathlib import Path
from typing import Annotated

from fastapi import APIRouter, Depends, File, Form, HTTPException, Request, UploadFile
from fastapi.responses import PlainTextResponse, StreamingResponse
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.orm import Session

from . import crud
from .app import get_or_404, get_service, get_session
from .dependencies import installed_features
from .models import Environment, Run, RunStatus, Schedule, TriggerType, Workflow
from .scheduler import SchedulerService
from .schemas import (
    DependencyCheckOut,
    DependencyIn,
    DependencyOut,
    EnvironmentIn,
    EnvironmentOut,
    ExtensionRequest,
    RunOut,
    ScheduleIn,
    ScheduleOut,
    Stats,
    TriggerPreview,
    WorkflowOut,
)

router = APIRouter(prefix="/api", tags=["api"])
SessionDep = Annotated[Session, Depends(get_session)]
ServiceDep = Annotated[SchedulerService, Depends(get_service)]


def _validation(fn, *args, **kwargs):
    """Esegue un'operazione di crud traducendo ValueError in HTTP 422."""
    try:
        return fn(*args, **kwargs)
    except ValueError as exc:
        raise HTTPException(422, str(exc)) from None


# --- Environment -------------------------------------------------------------

@router.get("/environments", response_model=list[EnvironmentOut])
def list_environments(s: SessionDep):
    return s.scalars(select(Environment).order_by(Environment.name)).all()


@router.post("/environments", response_model=EnvironmentOut, status_code=201)
def create_environment(data: EnvironmentIn, s: SessionDep):
    return _validation(crud.save_environment, s, data)


@router.get("/environments/{env_id}", response_model=EnvironmentOut)
def get_environment(env_id: int, s: SessionDep):
    return get_or_404(s, Environment, env_id)


@router.put("/environments/{env_id}", response_model=EnvironmentOut)
def update_environment(env_id: int, data: EnvironmentIn, s: SessionDep):
    return _validation(crud.save_environment, s, data, get_or_404(s, Environment, env_id))


@router.delete("/environments/{env_id}", status_code=204)
def delete_environment(env_id: int, s: SessionDep):
    _validation(crud.delete_environment, s, get_or_404(s, Environment, env_id))


@router.post("/environments/{env_id}/extensions", response_model=EnvironmentOut)
def request_extension(env_id: int, data: ExtensionRequest, s: SessionDep):
    """Aggiunge una feature alla lista delle estensioni richieste dall'environment."""
    env = get_or_404(s, Environment, env_id)
    crud.request_extension(s, env, data.feature_id)
    return env


@router.get("/environments/{env_id}/features")
def environment_features(env_id: int, s: SessionDep) -> dict[str, str]:
    """Estensioni installate nella cartella KNIME dell'environment."""
    return installed_features(get_or_404(s, Environment, env_id).knime_path)


# --- Workflow ----------------------------------------------------------------

@router.get("/workflows", response_model=list[WorkflowOut])
def list_workflows(s: SessionDep):
    return s.scalars(select(Workflow).order_by(Workflow.name)).all()


@router.post("/workflows", response_model=WorkflowOut, status_code=201)
def upload_workflow(
    request: Request,
    s: SessionDep,
    file: Annotated[UploadFile, File()],
    name: Annotated[str, Form()] = "",
    notes: Annotated[str, Form()] = "",
):
    return _validation(
        crud.store_workflow, s, request.app.state.workflows_dir, file.filename or "", file.file, name, notes
    )


@router.get("/workflows/{workflow_id}", response_model=WorkflowOut)
def get_workflow(workflow_id: int, s: SessionDep):
    return get_or_404(s, Workflow, workflow_id)


@router.put("/workflows/{workflow_id}/file", response_model=WorkflowOut)
def replace_workflow_file(
    workflow_id: int, request: Request, s: SessionDep, file: Annotated[UploadFile, File()]
):
    wf = get_or_404(s, Workflow, workflow_id)
    return _validation(
        crud.store_workflow, s, request.app.state.workflows_dir, file.filename or "", file.file, workflow=wf
    )


@router.delete("/workflows/{workflow_id}", status_code=204)
def delete_workflow(workflow_id: int, s: SessionDep):
    _validation(crud.delete_workflow, s, get_or_404(s, Workflow, workflow_id))


@router.post("/workflows/{workflow_id}/dependencies", response_model=DependencyOut, status_code=201)
def add_dependency(workflow_id: int, data: DependencyIn, s: SessionDep):
    return _validation(crud.add_dependency, s, get_or_404(s, Workflow, workflow_id), data)


@router.delete("/workflows/{workflow_id}/dependencies/{dependency_id}", status_code=204)
def delete_dependency(workflow_id: int, dependency_id: int, s: SessionDep):
    crud.delete_dependency(s, get_or_404(s, Workflow, workflow_id), dependency_id)


# --- Schedule ----------------------------------------------------------------

def _schedule_outs(s: Session, schedules: list[Schedule], service: SchedulerService) -> list[ScheduleOut]:
    last = crud.last_runs(s, [x.id for x in schedules])
    result = []
    for schedule in schedules:
        out = ScheduleOut.model_validate(schedule)
        out.next_run_time = service.next_run_time(schedule.id)
        if schedule.id in last:
            out.last_run = RunOut.model_validate(last[schedule.id])
        out.missing_dependencies = sum(
            1 for d in crud.dependency_report(schedule.workflow, schedule.environment) if d.status == "missing"
        )
        result.append(out)
    return result


def _schedule_out(s: Session, schedule: Schedule, service: SchedulerService) -> ScheduleOut:
    return _schedule_outs(s, [schedule], service)[0]


@router.get("/schedules", response_model=list[ScheduleOut])
def list_schedules(s: SessionDep, service: ServiceDep):
    return _schedule_outs(s, s.scalars(select(Schedule).order_by(Schedule.name)).all(), service)


@router.post("/schedules", response_model=ScheduleOut, status_code=201)
def create_schedule(data: ScheduleIn, s: SessionDep, service: ServiceDep):
    schedule = _validation(crud.save_schedule, s, data)
    service.sync_schedule(schedule)
    return _schedule_out(s, schedule, service)


@router.get("/schedules/{schedule_id}", response_model=ScheduleOut)
def get_schedule(schedule_id: int, s: SessionDep, service: ServiceDep):
    return _schedule_out(s, get_or_404(s, Schedule, schedule_id), service)


@router.put("/schedules/{schedule_id}", response_model=ScheduleOut)
def update_schedule(schedule_id: int, data: ScheduleIn, s: SessionDep, service: ServiceDep):
    schedule = _validation(crud.save_schedule, s, data, get_or_404(s, Schedule, schedule_id))
    service.sync_schedule(schedule)
    return _schedule_out(s, schedule, service)


class ActiveIn(BaseModel):
    active: bool


@router.patch("/schedules/{schedule_id}/active", response_model=ScheduleOut)
def set_schedule_active(schedule_id: int, data: ActiveIn, s: SessionDep, service: ServiceDep):
    """Mette in pausa o riattiva lo schedule."""
    schedule = get_or_404(s, Schedule, schedule_id)
    schedule.active = data.active
    s.commit()
    service.sync_schedule(schedule)
    return _schedule_out(s, schedule, service)


@router.delete("/schedules/{schedule_id}", status_code=204)
def delete_schedule(schedule_id: int, s: SessionDep, service: ServiceDep):
    _validation(crud.delete_schedule, s, get_or_404(s, Schedule, schedule_id))
    service.remove_schedule(schedule_id)


@router.get("/schedules/{schedule_id}/dependencies", response_model=list[DependencyCheckOut])
def schedule_dependencies(schedule_id: int, s: SessionDep):
    schedule = get_or_404(s, Schedule, schedule_id)
    return crud.dependency_report(schedule.workflow, schedule.environment)


@router.post("/schedules/{schedule_id}/run", response_model=RunOut, status_code=202)
def run_schedule(schedule_id: int, s: SessionDep, service: ServiceDep):
    get_or_404(s, Schedule, schedule_id)
    run_id = service.trigger_run(schedule_id, triggered_by="manual")
    if run_id is None:
        raise HTTPException(409, "C'e' gia' un run attivo e lo schedule e' impostato su 'salta'")
    s.expire_all()
    return s.get(Run, run_id)


@router.get("/dependency-check", response_model=list[DependencyCheckOut])
def dependency_check(workflow_id: int, environment_id: int, s: SessionDep):
    """Dipendenze di un workflow confrontate con un environment (form dello schedule)."""
    return crud.dependency_report(
        get_or_404(s, Workflow, workflow_id), get_or_404(s, Environment, environment_id)
    )


@router.get("/triggers/preview", response_model=TriggerPreview)
def preview_trigger(trigger_type: TriggerType, trigger_value: str, count: int = 5):
    """Valida un trigger e restituisce i prossimi orari di esecuzione."""
    return crud.trigger_preview(trigger_type, trigger_value, min(count, 20))


@router.get("/stats", response_model=Stats)
def stats(s: SessionDep, service: ServiceDep):
    return crud.compute_stats(s, service.next_run_time)


# --- Run ---------------------------------------------------------------------

@router.get("/runs", response_model=list[RunOut])
def list_runs(s: SessionDep, schedule_id: int | None = None, status: str | None = None, limit: int = 100):
    query = select(Run).order_by(Run.id.desc()).limit(min(limit, 1000))
    if schedule_id is not None:
        query = query.where(Run.schedule_id == schedule_id)
    if status:
        query = query.where(Run.status == status)
    return s.scalars(query).all()


@router.get("/runs/{run_id}", response_model=RunOut)
def get_run(run_id: int, s: SessionDep):
    return get_or_404(s, Run, run_id)


@router.post("/runs/{run_id}/cancel", status_code=202)
def cancel_run(run_id: int, s: SessionDep, service: ServiceDep):
    get_or_404(s, Run, run_id)
    if not service.cancel_run(run_id):
        raise HTTPException(409, "Il run non e' attivo")
    return {"ok": True}


@router.get("/runs/{run_id}/log", response_class=PlainTextResponse)
def run_log(run_id: int, s: SessionDep):
    run = get_or_404(s, Run, run_id)
    if not run.log_path or not Path(run.log_path).is_file():
        return ""
    return Path(run.log_path).read_text(encoding="utf-8", errors="replace")


@router.get("/runs/{run_id}/log/stream")
async def stream_log(run_id: int, request: Request, s: SessionDep):
    """Server-Sent Events: evento 'line' per ogni riga di log, 'done' (con lo stato) a run concluso."""
    get_or_404(s, Run, run_id)
    session_factory = request.app.state.session_factory
    active = (RunStatus.QUEUED, RunStatus.RUNNING)

    def snapshot() -> tuple[str, str | None]:
        with session_factory() as session:
            run = session.get(Run, run_id)
            return (run.status, run.log_path) if run else (RunStatus.CANCELLED, None)

    async def events():
        position = 0
        while not await request.is_disconnected():
            status, log_path = snapshot()
            finished = status not in active
            if log_path and Path(log_path).is_file():
                with open(log_path, "rb") as f:
                    f.seek(position)
                    for raw in f:
                        if not raw.endswith(b"\n") and not finished:
                            break  # riga ancora in scrittura
                        position += len(raw)
                        line = raw.decode("utf-8", errors="replace").rstrip("\r\n")
                        yield f"event: line\ndata: {json.dumps(line)}\n\n"
            if finished:
                yield f"event: done\ndata: {json.dumps(status)}\n\n"
                return
            await asyncio.sleep(0.5)

    return StreamingResponse(events(), media_type="text/event-stream")
