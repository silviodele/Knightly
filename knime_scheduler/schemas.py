"""Schemi Pydantic: input validati (API e form) e output delle API."""

from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from .executor import VARIABLE_TYPES
from .models import Concurrency, TriggerType


class EnvironmentIn(BaseModel):
    name: str = Field(min_length=1, max_length=100)
    notes: str = ""
    knime_path: str = Field(min_length=1)
    update_sites: list[str] = []
    extensions: list[str] = []
    preferences_file: str | None = None
    preference_entries: dict[str, str] = {}
    jvm_args: list[str] = []
    env_vars: dict[str, str] = {}


class EnvironmentOut(EnvironmentIn):
    model_config = ConfigDict(from_attributes=True)
    id: int
    created_at: datetime


class DependencyIn(BaseModel):
    feature_id: str = Field(min_length=1)
    name: str = ""
    version: str = ""
    update_site: str | None = None


class DependencyOut(DependencyIn):
    model_config = ConfigDict(from_attributes=True)
    id: int
    vendor: str
    source: str


class WorkflowOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: int
    name: str
    notes: str
    file_path: str
    uploaded_at: datetime
    dependencies: list[DependencyOut]


class Variable(BaseModel):
    name: str = Field(min_length=1)
    type: str = "String"
    value: str = ""

    @field_validator("type")
    @classmethod
    def _check_type(cls, v: str) -> str:
        if v not in VARIABLE_TYPES:
            raise ValueError(f"tipo non supportato, usare uno tra {sorted(VARIABLE_TYPES)}")
        return v

    @model_validator(mode="after")
    def _check_value(self):
        try:
            {"int": int, "double": float}.get(self.type, str)(self.value)
        except ValueError:
            raise ValueError(f"valore {self.value!r} non valido per la variabile {self.name} ({self.type})")
        return self


class Credential(BaseModel):
    name: str = Field(min_length=1)
    login: str = ""
    password: str = ""


class ScheduleIn(BaseModel):
    name: str = Field(min_length=1, max_length=200)
    notes: str = ""
    workflow_id: int
    environment_id: int
    active: bool = True
    trigger_type: TriggerType = TriggerType.CRON
    trigger_value: str = Field(min_length=1)
    variables: list[Variable] = []
    credentials: list[Credential] = []
    reset_before_run: bool = True
    concurrency: Concurrency = Concurrency.SKIP
    timeout_minutes: int | None = Field(default=None, gt=0)
    retention_days: int | None = Field(default=None, gt=0)
    notify_on: list[str] = ["failed"]


class CredentialOut(BaseModel):
    name: str
    login: str = ""


class ScheduleOut(ScheduleIn):
    model_config = ConfigDict(from_attributes=True)
    id: int
    credentials: list[CredentialOut]  # mai restituire le password
    next_run_time: datetime | None = None


class RunOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: int
    schedule_id: int
    status: str
    triggered_by: str
    queued_at: datetime
    started_at: datetime | None
    finished_at: datetime | None
    exit_code: int | None
    error: str | None


class DependencyCheckOut(BaseModel):
    feature_id: str
    name: str
    required_version: str
    installed_version: str | None
    status: str
    requested: bool  # gia' nella lista estensioni dell'environment
