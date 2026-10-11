"""Operazioni sul dominio condivise da API JSON e pagine HTML.

Gli errori di validazione sono sollevati come ValueError con un messaggio per l'utente.
"""

import re
import shutil
import uuid
import zipfile
from collections.abc import Callable
from datetime import datetime, timedelta
from pathlib import Path
from typing import BinaryIO

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from .dependencies import (
    Dependency,
    check_dependencies,
    extract_dependencies,
    installed_features,
    normalize_feature_id,
)
from .models import (
    DependencySource,
    Environment,
    Run,
    RunStatus,
    Schedule,
    Workflow,
    WorkflowDependency,
)
from .scheduler import make_trigger
from .schemas import (
    DailyRuns,
    DependencyCheckOut,
    DependencyIn,
    EnvironmentIn,
    RunOut,
    ScheduleIn,
    Stats,
    TriggerPreview,
    UpcomingRun,
)


# --- Environment -------------------------------------------------------------

def save_environment(s: Session, data: EnvironmentIn, env: Environment | None = None) -> Environment:
    duplicate = s.scalar(select(Environment).where(Environment.name == data.name))
    if duplicate and duplicate is not env:
        raise ValueError(f"Esiste gia' un environment chiamato '{data.name}'")
    if data.preferences_file and not Path(data.preferences_file).is_file():
        raise ValueError(f"File di preferenze non trovato: {data.preferences_file}")
    values = data.model_dump()
    values["extensions"] = sorted({normalize_feature_id(e) for e in data.extensions})
    env = env or Environment()
    for key, value in values.items():
        setattr(env, key, value)
    s.add(env)
    s.commit()
    return env


def delete_environment(s: Session, env: Environment) -> None:
    if env.schedules:
        raise ValueError("L'environment e' usato da uno o piu' schedule")
    s.delete(env)
    s.commit()


def request_extension(s: Session, env: Environment, feature_id: str) -> None:
    """Aggiunge una feature alla lista estensioni richieste dell'environment."""
    env.extensions = sorted(set(env.extensions) | {normalize_feature_id(feature_id)})
    s.commit()


# --- Workflow ----------------------------------------------------------------

def _safe_filename(filename: str) -> str:
    return re.sub(r"[^\w.\- ]", "_", Path(filename).name) or "workflow.knwf"


def store_workflow(
    s: Session,
    workflows_dir: Path,
    filename: str,
    content: BinaryIO,
    name: str = "",
    notes: str = "",
    workflow: Workflow | None = None,
) -> Workflow:
    """Salva (o sostituisce) il .knwf e aggiorna le dipendenze rilevate.

    Le dipendenze aggiunte a mano vengono mantenute.
    """
    if not filename.lower().endswith(".knwf"):
        raise ValueError("Il file deve avere estensione .knwf")
    workflows_dir.mkdir(parents=True, exist_ok=True)
    path = workflows_dir / f"{uuid.uuid4().hex[:8]}_{_safe_filename(filename)}"
    with open(path, "wb") as f:
        shutil.copyfileobj(content, f)
    try:
        detected = extract_dependencies(path)
    except zipfile.BadZipFile:
        path.unlink()
        raise ValueError("Il file non e' un workflow KNIME (.knwf) valido") from None

    workflow = workflow or Workflow()
    old_file = workflow.file_path
    workflow.name = name or workflow.name or Path(filename).stem
    workflow.notes = notes or workflow.notes or ""
    workflow.file_path = str(path)

    manual = {d.feature_id for d in workflow.dependencies if d.source == DependencySource.MANUAL}
    workflow.dependencies = [d for d in workflow.dependencies if d.source == DependencySource.MANUAL] + [
        WorkflowDependency(feature_id=d.feature_id, name=d.name, vendor=d.vendor, version=d.version)
        for d in detected
        if d.feature_id not in manual
    ]
    s.add(workflow)
    s.commit()
    if old_file and old_file != workflow.file_path:
        Path(old_file).unlink(missing_ok=True)
    return workflow


def update_workflow_info(s: Session, workflow: Workflow, name: str, notes: str) -> None:
    if not name.strip():
        raise ValueError("Il nome e' obbligatorio")
    workflow.name, workflow.notes = name.strip(), notes
    s.commit()


def delete_workflow(s: Session, workflow: Workflow) -> None:
    if workflow.schedules:
        raise ValueError("Il workflow e' usato da uno o piu' schedule")
    Path(workflow.file_path).unlink(missing_ok=True)
    s.delete(workflow)
    s.commit()


def add_dependency(s: Session, workflow: Workflow, data: DependencyIn) -> WorkflowDependency:
    feature_id = normalize_feature_id(data.feature_id.strip())
    if any(d.feature_id == feature_id for d in workflow.dependencies):
        raise ValueError(f"Dipendenza gia' presente: {feature_id}")
    dep = WorkflowDependency(
        feature_id=feature_id,
        name=data.name,
        version=data.version,
        update_site=data.update_site or None,
        source=DependencySource.MANUAL,
    )
    workflow.dependencies.append(dep)
    s.commit()
    return dep


def delete_dependency(s: Session, workflow: Workflow, dependency_id: int) -> None:
    workflow.dependencies = [d for d in workflow.dependencies if d.id != dependency_id]
    s.commit()


# --- Schedule ----------------------------------------------------------------

def save_schedule(s: Session, data: ScheduleIn, schedule: Schedule | None = None) -> Schedule:
    if s.get(Workflow, data.workflow_id) is None:
        raise ValueError("Workflow inesistente")
    if s.get(Environment, data.environment_id) is None:
        raise ValueError("Environment inesistente")
    try:
        make_trigger(data.trigger_type, data.trigger_value)
    except ValueError as exc:
        raise ValueError(f"Pianificazione non valida: {exc}") from None

    values = data.model_dump()
    if schedule is not None:
        # password vuota nel form = mantieni quella salvata
        saved = {c["name"]: c.get("password", "") for c in schedule.credentials}
        for cred in values["credentials"]:
            if not cred["password"]:
                cred["password"] = saved.get(cred["name"], "")
    schedule = schedule or Schedule()
    for key, value in values.items():
        setattr(schedule, key, value)
    s.add(schedule)
    s.commit()
    return schedule


def delete_schedule(s: Session, schedule: Schedule) -> None:
    """Elimina lo schedule con storico e log. Va poi rimosso anche dallo scheduler."""
    if any(r.status in (RunStatus.QUEUED, RunStatus.RUNNING) for r in schedule.runs):
        raise ValueError("Lo schedule ha run attivi: annullali prima di eliminarlo")
    for run in schedule.runs:
        if run.log_path:
            Path(run.log_path).unlink(missing_ok=True)
    s.delete(schedule)
    s.commit()


def dependency_report(workflow: Workflow, env: Environment) -> list[DependencyCheckOut]:
    """Dipendenze del workflow confrontate con l'environment (pannello dello schedule)."""
    required = [Dependency(d.feature_id, d.name, d.vendor, d.version) for d in workflow.dependencies]
    return [
        DependencyCheckOut(
            feature_id=c.dependency.feature_id,
            name=c.dependency.name,
            required_version=c.dependency.version,
            installed_version=c.installed_version,
            status=c.status,
            requested=c.dependency.feature_id in env.extensions,
        )
        for c in check_dependencies(required, installed_features(env.knime_path))
    ]


def last_runs(s: Session, schedule_ids: list[int]) -> dict[int, Run]:
    """Ultimo run per ciascuno schedule."""
    latest = (
        select(func.max(Run.id)).where(Run.schedule_id.in_(schedule_ids)).group_by(Run.schedule_id)
    )
    return {run.schedule_id: run for run in s.scalars(select(Run).where(Run.id.in_(latest)))}


# --- Trigger e statistiche ---------------------------------------------------

def trigger_preview(trigger_type: str, trigger_value: str, count: int = 5) -> TriggerPreview:
    """Valida il trigger e calcola i prossimi orari di esecuzione."""
    try:
        trigger = make_trigger(trigger_type, trigger_value)
    except ValueError as exc:
        return TriggerPreview(valid=False, error=str(exc))
    now = datetime.now().astimezone()
    runs: list[datetime] = []
    previous = None
    while len(runs) < count:
        next_time = trigger.get_next_fire_time(previous, previous or now)
        if next_time is None or next_time < now:
            break
        runs.append(next_time)
        previous = next_time
    return TriggerPreview(valid=True, next_runs=runs)


def compute_stats(s: Session, next_run_time: Callable[[int], datetime | None]) -> Stats:
    now = datetime.now()
    today = now.replace(hour=0, minute=0, second=0, microsecond=0)
    schedules = s.scalars(select(Schedule)).all()

    def count(*where) -> int:
        return s.scalar(select(func.count(Run.id)).where(*where)) or 0

    finished_7d = s.execute(
        select(Run.status, func.count(Run.id))
        .where(Run.finished_at >= now - timedelta(days=7))
        .group_by(Run.status)
    ).all()
    by_status = dict(finished_7d)
    concluded = sum(by_status.values())

    days = {(today - timedelta(days=i)).date().isoformat(): DailyRuns(day=(today - timedelta(days=i)).date().isoformat())
            for i in range(13, -1, -1)}
    for run in s.scalars(select(Run).where(Run.queued_at >= today - timedelta(days=13))):
        bucket = days.get(run.queued_at.date().isoformat())
        if bucket is None:
            continue
        if run.status == RunStatus.SUCCESS:
            bucket.success += 1
        elif run.status == RunStatus.FAILED:
            bucket.failed += 1
        elif run.status in (RunStatus.CANCELLED, RunStatus.TIMEOUT):
            bucket.other += 1

    upcoming = sorted(
        (
            UpcomingRun(schedule_id=x.id, schedule_name=x.name, next_run_time=t)
            for x in schedules
            if (t := next_run_time(x.id)) is not None
        ),
        key=lambda u: u.next_run_time,
    )[:6]
    failures = s.scalars(
        select(Run)
        .where(Run.status.in_((RunStatus.FAILED, RunStatus.TIMEOUT)))
        .order_by(Run.id.desc())
        .limit(5)
    ).all()

    return Stats(
        schedules_total=len(schedules),
        schedules_active=sum(1 for x in schedules if x.active),
        runs_active=count(Run.status.in_((RunStatus.QUEUED, RunStatus.RUNNING))),
        runs_today=count(Run.queued_at >= today),
        failed_24h=count(
            Run.status.in_((RunStatus.FAILED, RunStatus.TIMEOUT)), Run.finished_at >= now - timedelta(days=1)
        ),
        success_rate_7d=by_status.get(RunStatus.SUCCESS, 0) / concluded if concluded else None,
        daily=list(days.values()),
        upcoming=upcoming,
        recent_failures=[RunOut.model_validate(r) for r in failures],
    )
