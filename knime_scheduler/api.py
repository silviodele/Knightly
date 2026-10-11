"""API REST JSON."""

from pathlib import Path
from typing import Annotated

from fastapi import APIRouter, Depends, File, Form, HTTPException, Request, UploadFile
from fastapi.responses import PlainTextResponse
from sqlalchemy import select
from sqlalchemy.orm import Session

from . import crud
from .app import get_or_404, get_service, get_session
from .dependencies import installed_features
from .models import Environment, Run, Schedule, Workflow
from .scheduler import SchedulerService
from .schemas import (
    DependencyCheckOut,
    DependencyIn,
    DependencyOut,
    EnvironmentIn,
    EnvironmentOut,
    RunOut,
    ScheduleIn,
    ScheduleOut,
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

def _schedule_out(schedule: Schedule, service: SchedulerService) -> ScheduleOut:
    out = ScheduleOut.model_validate(schedule)
    out.next_run_time = service.next_run_time(schedule.id)
    return out


@router.get("/schedules", response_model=list[ScheduleOut])
def list_schedules(s: SessionDep, service: ServiceDep):
    return [_schedule_out(x, service) for x in s.scalars(select(Schedule).order_by(Schedule.name))]


@router.post("/schedules", response_model=ScheduleOut, status_code=201)
def create_schedule(data: ScheduleIn, s: SessionDep, service: ServiceDep):
    schedule = _validation(crud.save_schedule, s, data)
    service.sync_schedule(schedule)
    return _schedule_out(schedule, service)


@router.get("/schedules/{schedule_id}", response_model=ScheduleOut)
def get_schedule(schedule_id: int, s: SessionDep, service: ServiceDep):
    return _schedule_out(get_or_404(s, Schedule, schedule_id), service)


@router.put("/schedules/{schedule_id}", response_model=ScheduleOut)
def update_schedule(schedule_id: int, data: ScheduleIn, s: SessionDep, service: ServiceDep):
    schedule = _validation(crud.save_schedule, s, data, get_or_404(s, Schedule, schedule_id))
    service.sync_schedule(schedule)
    return _schedule_out(schedule, service)


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
