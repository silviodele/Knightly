"""Pagine HTML (Jinja2 + HTMX)."""

import asyncio
import html
from datetime import datetime
from pathlib import Path
from typing import Annotated

from fastapi import APIRouter, Depends, Form, HTTPException, Request, UploadFile
from fastapi.responses import HTMLResponse, RedirectResponse, StreamingResponse
from fastapi.templating import Jinja2Templates
from pydantic import ValidationError
from sqlalchemy import select
from sqlalchemy.orm import Session

from . import crud
from .app import HERE, get_or_404, get_service, get_session
from .dependencies import installed_features
from .executor import VARIABLE_TYPES
from .models import Concurrency, Environment, Run, RunStatus, Schedule, TriggerType, Workflow
from .scheduler import SchedulerService
from .schemas import DependencyIn, EnvironmentIn, ScheduleIn

router = APIRouter(include_in_schema=False)
templates = Jinja2Templates(directory=HERE / "templates")
SessionDep = Annotated[Session, Depends(get_session)]
ServiceDep = Annotated[SchedulerService, Depends(get_service)]

ACTIVE = (RunStatus.QUEUED, RunStatus.RUNNING)
STATUS_LABELS = {
    RunStatus.QUEUED: "In coda",
    RunStatus.RUNNING: "In esecuzione",
    RunStatus.SUCCESS: "Riuscito",
    RunStatus.FAILED: "Fallito",
    RunStatus.CANCELLED: "Annullato",
    RunStatus.TIMEOUT: "Timeout",
}
CONCURRENCY_LABELS = {
    Concurrency.SKIP: "Salta il nuovo run",
    Concurrency.QUEUE: "Accoda (uno alla volta)",
    Concurrency.REPLACE: "Annulla quello attivo e riparti",
    Concurrency.ALLOW: "Consenti in parallelo",
}
TRIGGER_LABELS = {
    TriggerType.CRON: "Cron",
    TriggerType.INTERVAL: "Ogni N minuti",
    TriggerType.DATE: "Una tantum",
}


def _fmt_dt(value: datetime | None) -> str:
    return value.strftime("%d/%m/%Y %H:%M:%S") if value else "—"


def _duration(run: Run) -> str:
    if not run.started_at:
        return "—"
    seconds = int(((run.finished_at or datetime.now()) - run.started_at).total_seconds())
    return f"{seconds // 3600:d}:{seconds // 60 % 60:02d}:{seconds % 60:02d}"


templates.env.filters["dt"] = _fmt_dt
templates.env.globals.update(
    duration=_duration,
    STATUS_LABELS=STATUS_LABELS,
    CONCURRENCY_LABELS=CONCURRENCY_LABELS,
    TRIGGER_LABELS=TRIGGER_LABELS,
    VARIABLE_TYPES=sorted(VARIABLE_TYPES),
    ACTIVE=ACTIVE,
)


def render(request: Request, name: str, status_code: int = 200, **context) -> HTMLResponse:
    return templates.TemplateResponse(request, name, context, status_code=status_code)


def redirect(url: str) -> RedirectResponse:
    return RedirectResponse(url, status_code=303)


def error_text(exc: Exception) -> str:
    if isinstance(exc, ValidationError):
        return "; ".join(
            f"{'.'.join(str(p) for p in e['loc'])}: {e['msg']}" if e["loc"] else e["msg"]
            for e in exc.errors()
        )
    return str(exc)


# --- parsing dei form ----------------------------------------------------------

def _lines(text: str) -> list[str]:
    return [line.strip() for line in text.splitlines() if line.strip()]


def _key_values(text: str) -> dict[str, str]:
    result = {}
    for line in _lines(text):
        key, sep, value = line.partition("=")
        if not sep or not key.strip():
            raise ValueError(f"Riga non valida (usa chiave=valore): {line}")
        result[key.strip()] = value.strip()
    return result


def _rows(form, prefix: str, fields: list[str]) -> list[dict]:
    """Righe ripetute del form (es. var_name/var_type/var_value), scarta quelle senza nome."""
    columns = [form.getlist(f"{prefix}_{f}") for f in fields]
    return [dict(zip(fields, values)) for values in zip(*columns) if values[0].strip()]


def _environment_in(form) -> EnvironmentIn:
    return EnvironmentIn(
        name=form.get("name", "").strip(),
        notes=form.get("notes", ""),
        knime_path=form.get("knime_path", "").strip(),
        update_sites=_lines(form.get("update_sites", "")),
        extensions=_lines(form.get("extensions", "")),
        preferences_file=form.get("preferences_file", "").strip() or None,
        preference_entries=_key_values(form.get("preference_entries", "")),
        jvm_args=_lines(form.get("jvm_args", "")),
        env_vars=_key_values(form.get("env_vars", "")),
    )


def _schedule_in(form) -> ScheduleIn:
    def optional_int(key: str) -> int | None:
        value = form.get(key, "").strip()
        return int(value) if value else None

    return ScheduleIn(
        name=form.get("name", "").strip(),
        notes=form.get("notes", ""),
        workflow_id=int(form.get("workflow_id") or 0),
        environment_id=int(form.get("environment_id") or 0),
        active="active" in form,
        trigger_type=form.get("trigger_type", TriggerType.CRON),
        trigger_value=form.get("trigger_value", "").strip(),
        variables=_rows(form, "var", ["name", "type", "value"]),
        credentials=_rows(form, "cred", ["name", "login", "password"]),
        reset_before_run="reset_before_run" in form,
        concurrency=form.get("concurrency", Concurrency.SKIP),
        timeout_minutes=optional_int("timeout_minutes"),
        retention_days=optional_int("retention_days"),
        notify_on=form.getlist("notify_on"),
    )


# --- home ------------------------------------------------------------------------

@router.get("/")
def home():
    return redirect("/schedules")


# --- Schedule --------------------------------------------------------------------

def _schedule_rows(s: Session, service: SchedulerService, schedules: list[Schedule]) -> list[dict]:
    last = crud.last_runs(s, [x.id for x in schedules])
    return [
        {"schedule": x, "last_run": last.get(x.id), "next_run": service.next_run_time(x.id)}
        for x in schedules
    ]


def _schedule_fields(schedule: Schedule | None, form) -> dict:
    """Valori da mostrare nel form: quelli inviati (se errore), altrimenti quelli salvati."""
    if form is not None:
        return {
            **{k: form.get(k, "") for k in (
                "name", "notes", "workflow_id", "environment_id", "trigger_type", "trigger_value",
                "concurrency", "timeout_minutes", "retention_days",
            )},
            "active": "active" in form,
            "reset_before_run": "reset_before_run" in form,
            "notify_on": form.getlist("notify_on"),
            "variables": _rows(form, "var", ["name", "type", "value"]),
            "credentials": _rows(form, "cred", ["name", "login", "password"]),
        }
    if schedule is None:
        return {
            "name": "", "notes": "", "workflow_id": "", "environment_id": "",
            "trigger_type": TriggerType.CRON, "trigger_value": "", "concurrency": Concurrency.SKIP,
            "timeout_minutes": "", "retention_days": "", "active": True, "reset_before_run": True,
            "notify_on": ["failed"], "variables": [], "credentials": [],
        }
    return {
        "name": schedule.name, "notes": schedule.notes,
        "workflow_id": str(schedule.workflow_id), "environment_id": str(schedule.environment_id),
        "trigger_type": schedule.trigger_type, "trigger_value": schedule.trigger_value,
        "concurrency": schedule.concurrency,
        "timeout_minutes": schedule.timeout_minutes or "", "retention_days": schedule.retention_days or "",
        "active": schedule.active, "reset_before_run": schedule.reset_before_run,
        "notify_on": schedule.notify_on, "variables": schedule.variables,
        # le password non tornano mai nella pagina: vuoto = mantieni quella salvata
        "credentials": [{**c, "password": ""} for c in schedule.credentials],
    }


def _schedule_form(request, s, service, schedule=None, error=None, values=None, status_code=200):
    runs = _schedule_runs(s, schedule.id) if schedule else []
    return render(
        request,
        "schedule_form.html",
        status_code,
        schedule=schedule,
        f=_schedule_fields(schedule, values),
        error=error,
        runs=runs,
        refresh_url=f"/schedules/{schedule.id}/runs" if schedule else None,
        next_run=service.next_run_time(schedule.id) if schedule else None,
        workflows=s.scalars(select(Workflow).order_by(Workflow.name)).all(),
        environments=s.scalars(select(Environment).order_by(Environment.name)).all(),
    )


@router.get("/schedules")
def schedules_page(request: Request, s: SessionDep, service: ServiceDep):
    schedules = s.scalars(select(Schedule).order_by(Schedule.name)).all()
    return render(request, "schedules.html", rows=_schedule_rows(s, service, schedules))


@router.get("/schedules/new")
def new_schedule_page(request: Request, s: SessionDep, service: ServiceDep):
    return _schedule_form(request, s, service)


@router.post("/schedules/new")
async def create_schedule(request: Request, s: SessionDep, service: ServiceDep):
    form = await request.form()
    try:
        schedule = crud.save_schedule(s, _schedule_in(form))
    except (ValueError, ValidationError) as exc:
        return _schedule_form(request, s, service, error=error_text(exc), values=form, status_code=422)
    service.sync_schedule(schedule)
    return redirect(f"/schedules/{schedule.id}")


@router.get("/schedules/{schedule_id}")
def schedule_page(schedule_id: int, request: Request, s: SessionDep, service: ServiceDep):
    return _schedule_form(request, s, service, get_or_404(s, Schedule, schedule_id))


@router.post("/schedules/{schedule_id}")
async def update_schedule(schedule_id: int, request: Request, s: SessionDep, service: ServiceDep):
    schedule = get_or_404(s, Schedule, schedule_id)
    form = await request.form()
    try:
        crud.save_schedule(s, _schedule_in(form), schedule)
    except (ValueError, ValidationError) as exc:
        s.rollback()
        return _schedule_form(
            request, s, service, schedule, error=error_text(exc), values=form, status_code=422
        )
    service.sync_schedule(schedule)
    return redirect(f"/schedules/{schedule_id}")


@router.post("/schedules/{schedule_id}/delete")
def delete_schedule(schedule_id: int, request: Request, s: SessionDep, service: ServiceDep):
    schedule = get_or_404(s, Schedule, schedule_id)
    try:
        crud.delete_schedule(s, schedule)
    except ValueError as exc:
        return _schedule_form(request, s, service, schedule, error=str(exc), status_code=409)
    service.remove_schedule(schedule_id)
    return redirect("/schedules")


@router.post("/schedules/{schedule_id}/toggle")
def toggle_schedule(schedule_id: int, request: Request, s: SessionDep, service: ServiceDep):
    schedule = get_or_404(s, Schedule, schedule_id)
    schedule.active = not schedule.active
    s.commit()
    service.sync_schedule(schedule)
    return render(request, "_schedule_row.html", row=_schedule_rows(s, service, [schedule])[0])


def _schedule_runs(s: Session, schedule_id: int) -> list[Run]:
    return s.scalars(
        select(Run).where(Run.schedule_id == schedule_id).order_by(Run.id.desc()).limit(20)
    ).all()


def _schedule_runs_fragment(request: Request, s: Session, schedule_id: int, message=None):
    return render(
        request, "_runs_table.html", runs=_schedule_runs(s, schedule_id),
        refresh_url=f"/schedules/{schedule_id}/runs", message=message,
    )


@router.get("/schedules/{schedule_id}/runs")
def schedule_runs(schedule_id: int, request: Request, s: SessionDep):
    get_or_404(s, Schedule, schedule_id)
    return _schedule_runs_fragment(request, s, schedule_id)


@router.post("/schedules/{schedule_id}/run")
def run_schedule(schedule_id: int, request: Request, s: SessionDep, service: ServiceDep):
    schedule = get_or_404(s, Schedule, schedule_id)
    run_id = service.trigger_run(schedule_id, triggered_by="manual")
    message = None if run_id else "Run non avviato: ce n'e' gia' uno attivo e lo schedule e' su 'salta'"
    s.expire_all()
    if request.headers.get("HX-Target") == "runs":
        return _schedule_runs_fragment(request, s, schedule_id, message)
    return render(
        request, "_schedule_row.html", row=_schedule_rows(s, service, [schedule])[0], message=message
    )


@router.get("/dependency-panel")
def dependency_panel(
    request: Request, s: SessionDep, workflow_id: str = "", environment_id: str = ""
):
    workflow = s.get(Workflow, int(workflow_id)) if workflow_id.isdigit() else None
    env = s.get(Environment, int(environment_id)) if environment_id.isdigit() else None
    report = crud.dependency_report(workflow, env) if workflow and env else []
    return render(request, "_dependency_panel.html", workflow=workflow, env=env, report=report)


@router.post("/environments/{env_id}/request-extension")
def request_extension(
    env_id: int,
    request: Request,
    s: SessionDep,
    feature_id: Annotated[str, Form()],
    workflow_id: Annotated[str, Form()] = "",
):
    env = get_or_404(s, Environment, env_id)
    crud.request_extension(s, env, feature_id)
    return dependency_panel(request, s, workflow_id=workflow_id, environment_id=str(env_id))


@router.get("/form-rows/{kind}")
def form_row(kind: str, request: Request):
    if kind not in ("var", "cred"):
        raise HTTPException(404)
    return render(request, f"_{kind}_row.html", item={})


# --- Environment -----------------------------------------------------------------

def _environment_fields(env: Environment | None, form) -> dict:
    keys = ("name", "notes", "knime_path", "update_sites", "extensions", "preferences_file",
            "preference_entries", "jvm_args", "env_vars")
    if form is not None:
        return {k: form.get(k, "") for k in keys}
    if env is None:
        return {k: "" for k in keys} | {"jvm_args": "-Xmx4g"}
    return {
        "name": env.name, "notes": env.notes, "knime_path": env.knime_path,
        "update_sites": "\n".join(env.update_sites), "extensions": "\n".join(env.extensions),
        "preferences_file": env.preferences_file or "",
        "preference_entries": "\n".join(f"{k}={v}" for k, v in env.preference_entries.items()),
        "jvm_args": "\n".join(env.jvm_args),
        "env_vars": "\n".join(f"{k}={v}" for k, v in env.env_vars.items()),
    }


def _environment_form(request, env=None, error=None, values=None, status_code=200):
    features = installed_features(env.knime_path) if env else {}
    return render(
        request, "environment_form.html", status_code,
        env=env, f=_environment_fields(env, values), error=error, features=features,
    )


@router.get("/environments")
def environments_page(request: Request, s: SessionDep):
    envs = s.scalars(select(Environment).order_by(Environment.name)).all()
    return render(request, "environments.html", envs=envs)


@router.get("/environments/new")
def new_environment_page(request: Request):
    return _environment_form(request)


@router.post("/environments/new")
async def create_environment(request: Request, s: SessionDep):
    form = await request.form()
    try:
        env = crud.save_environment(s, _environment_in(form))
    except (ValueError, ValidationError) as exc:
        return _environment_form(request, error=error_text(exc), values=form, status_code=422)
    return redirect(f"/environments/{env.id}")


@router.get("/environments/{env_id}")
def environment_page(env_id: int, request: Request, s: SessionDep):
    return _environment_form(request, get_or_404(s, Environment, env_id))


@router.post("/environments/{env_id}")
async def update_environment(env_id: int, request: Request, s: SessionDep):
    env = get_or_404(s, Environment, env_id)
    form = await request.form()
    try:
        crud.save_environment(s, _environment_in(form), env)
    except (ValueError, ValidationError) as exc:
        s.rollback()
        return _environment_form(request, env, error=error_text(exc), values=form, status_code=422)
    return redirect(f"/environments/{env_id}")


@router.post("/environments/{env_id}/delete")
def delete_environment(env_id: int, request: Request, s: SessionDep):
    env = get_or_404(s, Environment, env_id)
    try:
        crud.delete_environment(s, env)
    except ValueError as exc:
        return _environment_form(request, env, error=str(exc), status_code=409)
    return redirect("/environments")


# --- Workflow --------------------------------------------------------------------

def _workflows_list(request, s, error=None, status_code=200):
    workflows = s.scalars(select(Workflow).order_by(Workflow.name)).all()
    return render(request, "workflows.html", status_code, workflows=workflows, error=error)


@router.get("/workflows")
def workflows_page(request: Request, s: SessionDep):
    return _workflows_list(request, s)


@router.post("/workflows")
def upload_workflow(
    request: Request,
    s: SessionDep,
    file: UploadFile,
    name: Annotated[str, Form()] = "",
    notes: Annotated[str, Form()] = "",
):
    try:
        wf = crud.store_workflow(
            s, request.app.state.workflows_dir, file.filename or "", file.file, name, notes
        )
    except ValueError as exc:
        return _workflows_list(request, s, error=str(exc), status_code=422)
    return redirect(f"/workflows/{wf.id}")


def _workflow_page(request, s, wf, error=None, status_code=200):
    return render(request, "workflow_detail.html", status_code, wf=wf, error=error)


@router.get("/workflows/{workflow_id}")
def workflow_page(workflow_id: int, request: Request, s: SessionDep):
    return _workflow_page(request, s, get_or_404(s, Workflow, workflow_id))


@router.post("/workflows/{workflow_id}")
def update_workflow(
    workflow_id: int,
    request: Request,
    s: SessionDep,
    name: Annotated[str, Form()] = "",
    notes: Annotated[str, Form()] = "",
):
    wf = get_or_404(s, Workflow, workflow_id)
    try:
        crud.update_workflow_info(s, wf, name, notes)
    except ValueError as exc:
        return _workflow_page(request, s, wf, str(exc), 422)
    return redirect(f"/workflows/{workflow_id}")


@router.post("/workflows/{workflow_id}/file")
def replace_workflow_file(workflow_id: int, request: Request, s: SessionDep, file: UploadFile):
    wf = get_or_404(s, Workflow, workflow_id)
    try:
        crud.store_workflow(
            s, request.app.state.workflows_dir, file.filename or "", file.file, workflow=wf
        )
    except ValueError as exc:
        s.rollback()
        return _workflow_page(request, s, wf, str(exc), 422)
    return redirect(f"/workflows/{workflow_id}")


@router.post("/workflows/{workflow_id}/delete")
def delete_workflow(workflow_id: int, request: Request, s: SessionDep):
    wf = get_or_404(s, Workflow, workflow_id)
    try:
        crud.delete_workflow(s, wf)
    except ValueError as exc:
        return _workflow_page(request, s, wf, str(exc), 409)
    return redirect("/workflows")


@router.post("/workflows/{workflow_id}/dependencies")
def add_dependency(
    workflow_id: int,
    request: Request,
    s: SessionDep,
    feature_id: Annotated[str, Form()] = "",
    name: Annotated[str, Form()] = "",
    version: Annotated[str, Form()] = "",
    update_site: Annotated[str, Form()] = "",
):
    wf = get_or_404(s, Workflow, workflow_id)
    error = None
    try:
        data = DependencyIn(feature_id=feature_id, name=name, version=version, update_site=update_site)
        crud.add_dependency(s, wf, data)
    except (ValueError, ValidationError) as exc:
        s.rollback()
        error = error_text(exc)
    return render(request, "_dependencies_table.html", wf=wf, dep_error=error)


@router.post("/workflows/{workflow_id}/dependencies/{dependency_id}/delete")
def delete_dependency(workflow_id: int, dependency_id: int, request: Request, s: SessionDep):
    wf = get_or_404(s, Workflow, workflow_id)
    crud.delete_dependency(s, wf, dependency_id)
    return render(request, "_dependencies_table.html", wf=wf)


# --- Run -------------------------------------------------------------------------

def _recent_runs(s: Session, status: str = "") -> list[Run]:
    query = select(Run).order_by(Run.id.desc()).limit(100)
    if status:
        query = query.where(Run.status == status)
    return s.scalars(query).all()


@router.get("/runs")
def runs_page(request: Request, s: SessionDep, status: str = ""):
    runs = _recent_runs(s, status)
    template = "_runs_table.html" if request.headers.get("HX-Request") else "runs.html"
    refresh_url = f"/runs?status={status}" if status else "/runs"
    return render(
        request, template, runs=runs, status=status, show_schedule=True, refresh_url=refresh_url
    )


@router.get("/runs/{run_id}")
def run_page(run_id: int, request: Request, s: SessionDep):
    run = get_or_404(s, Run, run_id)
    log_text = ""
    if run.status not in ACTIVE and run.log_path and Path(run.log_path).is_file():
        log_text = Path(run.log_path).read_text(encoding="utf-8", errors="replace")
    return render(request, "run_detail.html", run=run, log_text=log_text)


@router.get("/runs/{run_id}/status")
def run_status_fragment(run_id: int, request: Request, s: SessionDep):
    return render(request, "_run_status.html", run=get_or_404(s, Run, run_id))


@router.post("/runs/{run_id}/cancel")
def cancel_run(run_id: int, request: Request, s: SessionDep, service: ServiceDep):
    get_or_404(s, Run, run_id)
    service.cancel_run(run_id)
    return redirect(f"/runs/{run_id}")


@router.get("/runs/{run_id}/log/stream")
async def stream_log(run_id: int, request: Request):
    """Server-Sent Events: una riga di log per evento 'line', poi 'done' a run concluso."""
    session_factory = request.app.state.session_factory

    def snapshot() -> tuple[str, str | None]:
        with session_factory() as s:
            run = s.get(Run, run_id)
            if run is None:
                raise HTTPException(404)
            return run.status, run.log_path

    snapshot()  # 404 prima di aprire lo stream

    async def events():
        position = 0
        while not await request.is_disconnected():
            status, log_path = snapshot()
            finished = status not in ACTIVE
            if log_path and Path(log_path).is_file():
                with open(log_path, encoding="utf-8", errors="replace") as f:
                    f.seek(position)
                    while line := f.readline():
                        if not line.endswith("\n") and not finished:
                            break  # riga ancora in scrittura
                        position = f.tell()
                        yield f"event: line\ndata: <div>{html.escape(line.rstrip())}</div>\n\n"
            if finished:
                yield "event: done\ndata: \n\n"
                return
            await asyncio.sleep(0.5)

    return StreamingResponse(events(), media_type="text/event-stream")
