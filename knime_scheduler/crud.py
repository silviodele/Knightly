"""Operazioni sul dominio condivise da API JSON e pagine HTML.

Gli errori di validazione sono sollevati come ValueError con un messaggio per l'utente.
"""

import re
import shutil
import uuid
import zipfile
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
from .schemas import DependencyCheckOut, DependencyIn, EnvironmentIn, ScheduleIn


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
