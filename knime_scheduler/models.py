"""Modello dati: Environment, Workflow (+ dipendenze), Schedule, Run.

Ispirato a NodePit Runner:
- Environment = *dove* gira un workflow (installazione KNIME, estensioni, preferenze, JVM)
- Schedule    = *come e quando* gira (workflow + environment + trigger + variabili)
- Run         = singola esecuzione
"""

from datetime import datetime
from enum import StrEnum

from sqlalchemy import JSON, ForeignKey, String, Text, UniqueConstraint
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship


class Base(DeclarativeBase):
    pass


class TriggerType(StrEnum):
    CRON = "cron"          # espressione cron a 5 campi
    INTERVAL = "interval"  # ogni N minuti
    DATE = "date"          # una tantum (ISO datetime)


class Concurrency(StrEnum):
    """Cosa fare se lo schedule scatta mentre un suo run e' ancora attivo."""

    ALLOW = "allow"
    SKIP = "skip"
    QUEUE = "queue"
    REPLACE = "replace"  # annulla il run attivo e ne avvia uno nuovo


class RunStatus(StrEnum):
    QUEUED = "queued"
    RUNNING = "running"
    SUCCESS = "success"
    FAILED = "failed"
    CANCELLED = "cancelled"
    TIMEOUT = "timeout"


class DependencySource(StrEnum):
    DETECTED = "detected"  # letta dal .knwf
    MANUAL = "manual"      # aggiunta a mano dall'utente


class Environment(Base):
    __tablename__ = "environments"

    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(String(100), unique=True)
    notes: Mapped[str] = mapped_column(Text, default="")
    # Cartella dell'installazione KNIME (contiene knime.exe / knime e features/)
    knime_path: Mapped[str] = mapped_column(String(500))
    # Update site da cui installare le estensioni (URL p2)
    update_sites: Mapped[list[str]] = mapped_column(JSON, default=list)
    # Feature da garantire installate (es. "org.knime.features.python3.scripting.feature.group")
    extensions: Mapped[list[str]] = mapped_column(JSON, default=list)
    # File .epf esportato da KNIME + singole voci che lo sovrascrivono
    preferences_file: Mapped[str | None] = mapped_column(String(500))
    preference_entries: Mapped[dict[str, str]] = mapped_column(JSON, default=dict)
    jvm_args: Mapped[list[str]] = mapped_column(JSON, default=list)  # es. ["-Xmx4g"]
    env_vars: Mapped[dict[str, str]] = mapped_column(JSON, default=dict)
    created_at: Mapped[datetime] = mapped_column(default=datetime.now)

    schedules: Mapped[list["Schedule"]] = relationship(back_populates="environment")


class Workflow(Base):
    __tablename__ = "workflows"

    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(String(200))
    notes: Mapped[str] = mapped_column(Text, default="")
    file_path: Mapped[str] = mapped_column(String(500))  # .knwf caricato
    uploaded_at: Mapped[datetime] = mapped_column(default=datetime.now)

    dependencies: Mapped[list["WorkflowDependency"]] = relationship(
        back_populates="workflow", cascade="all, delete-orphan"
    )
    schedules: Mapped[list["Schedule"]] = relationship(back_populates="workflow")


class WorkflowDependency(Base):
    """Estensione KNIME (feature) richiesta da un workflow."""

    __tablename__ = "workflow_dependencies"
    __table_args__ = (UniqueConstraint("workflow_id", "feature_id"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    workflow_id: Mapped[int] = mapped_column(ForeignKey("workflows.id"))
    feature_id: Mapped[str] = mapped_column(String(300))  # es. "org.knime.features.base.feature.group"
    name: Mapped[str] = mapped_column(String(300), default="")
    vendor: Mapped[str] = mapped_column(String(300), default="")
    version: Mapped[str] = mapped_column(String(100), default="")  # versione con cui e' stato salvato
    update_site: Mapped[str | None] = mapped_column(String(500))
    source: Mapped[DependencySource] = mapped_column(String(20), default=DependencySource.DETECTED)

    workflow: Mapped[Workflow] = relationship(back_populates="dependencies")


class Schedule(Base):
    __tablename__ = "schedules"

    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(String(200))
    notes: Mapped[str] = mapped_column(Text, default="")
    workflow_id: Mapped[int] = mapped_column(ForeignKey("workflows.id"))
    environment_id: Mapped[int] = mapped_column(ForeignKey("environments.id"))
    active: Mapped[bool] = mapped_column(default=True)

    trigger_type: Mapped[TriggerType] = mapped_column(String(20), default=TriggerType.CRON)
    trigger_value: Mapped[str] = mapped_column(String(100))  # "0 6 * * 1-5" | "30" | ISO datetime

    # [{"name": ..., "type": "String"|"int"|"double", "value": ...}]
    variables: Mapped[list[dict]] = mapped_column(JSON, default=list)
    # [{"name": ..., "login": ..., "password": ...}]  TODO: cifrare le password
    credentials: Mapped[list[dict]] = mapped_column(JSON, default=list)
    reset_before_run: Mapped[bool] = mapped_column(default=True)
    concurrency: Mapped[Concurrency] = mapped_column(String(20), default=Concurrency.SKIP)
    timeout_minutes: Mapped[int | None]
    retention_days: Mapped[int | None]
    notify_on: Mapped[list[str]] = mapped_column(JSON, default=lambda: ["failed"])

    workflow: Mapped[Workflow] = relationship(back_populates="schedules")
    environment: Mapped[Environment] = relationship(back_populates="schedules")
    runs: Mapped[list["Run"]] = relationship(back_populates="schedule", cascade="all, delete-orphan")

    @property
    def workflow_name(self) -> str:
        return self.workflow.name

    @property
    def environment_name(self) -> str:
        return self.environment.name


class Run(Base):
    __tablename__ = "runs"

    id: Mapped[int] = mapped_column(primary_key=True)
    schedule_id: Mapped[int] = mapped_column(ForeignKey("schedules.id"))
    status: Mapped[RunStatus] = mapped_column(String(20), default=RunStatus.QUEUED)
    triggered_by: Mapped[str] = mapped_column(String(20), default="schedule")  # schedule | manual
    queued_at: Mapped[datetime] = mapped_column(default=datetime.now)
    started_at: Mapped[datetime | None]
    finished_at: Mapped[datetime | None]
    exit_code: Mapped[int | None]
    log_path: Mapped[str | None] = mapped_column(String(500))
    error: Mapped[str | None] = mapped_column(Text)

    schedule: Mapped[Schedule] = relationship(back_populates="runs")

    @property
    def schedule_name(self) -> str:
        return self.schedule.name
