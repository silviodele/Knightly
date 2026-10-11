"""Scheduler: trigger degli Schedule, coda dei Run, concorrenza ed esecuzione.

Gli Schedule vivono nel nostro database: all'avvio vengono caricati in APScheduler
(job store in memoria), quindi il DB resta l'unica fonte di verita'.
I run persi mentre il servizio era spento non vengono recuperati.
"""

import logging
import threading
from collections.abc import Callable
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta
from pathlib import Path

from apscheduler.schedulers.background import BackgroundScheduler
from apscheduler.triggers.cron import CronTrigger
from apscheduler.triggers.date import DateTrigger
from apscheduler.triggers.interval import IntervalTrigger
from sqlalchemy import select
from sqlalchemy.orm import Session, sessionmaker

from .dependencies import Dependency, DependencyStatus, check_dependencies, installed_features
from .executor import RunSpec, run_workflow
from .models import Concurrency, Run, RunStatus, Schedule, TriggerType

log = logging.getLogger(__name__)

ACTIVE_STATUSES = (RunStatus.QUEUED, RunStatus.RUNNING)
KNIME_EXIT_CODES = {
    2: "Parametri della riga di comando non validi",
    3: "Errore nel caricamento del workflow",
    4: "Errore durante l'esecuzione del workflow",
}


_DAY_NAMES = ["sun", "mon", "tue", "wed", "thu", "fri", "sat"]


def _crontab_day_of_week(field: str) -> str:
    """Converte il giorno della settimana dal cron standard (0/7 = domenica) ai nomi.

    APScheduler 3 conta da 0 = lunedi': senza conversione "1-5" diventerebbe mar-sab.
    """
    if not any(ch.isdigit() for ch in field):
        return field  # "*" o nomi (mon-fri), gia' corretti
    days: set[int] = set()
    for part in field.split(","):
        base, _, step_text = part.partition("/")
        step = int(step_text) if step_text else 1
        if base == "*":
            start, end = 0, 6
        elif "-" in base:
            start, end = (int(x) for x in base.split("-", 1))
        else:
            start = int(base)
            end = 6 if step_text else start
        if not (0 <= start <= 7 and 0 <= end <= 7 and start <= end and step > 0):
            raise ValueError(f"Giorno della settimana non valido: {part!r}")
        days.update(d % 7 for d in range(start, end + 1, step))
    return ",".join(_DAY_NAMES[d] for d in sorted(days))


def make_trigger(trigger_type: str, value: str):
    """Crea il trigger APScheduler; ValueError se il valore non e' valido."""
    match trigger_type:
        case TriggerType.CRON:
            fields = value.split()
            if len(fields) != 5:
                raise ValueError("L'espressione cron deve avere 5 campi: minuto ora giorno mese giorno-settimana")
            minute, hour, day, month, day_of_week = fields
            return CronTrigger(
                minute=minute, hour=hour, day=day, month=month,
                day_of_week=_crontab_day_of_week(day_of_week),
            )
        case TriggerType.INTERVAL:
            minutes = int(value)
            if minutes <= 0:
                raise ValueError("L'intervallo deve essere di almeno 1 minuto")
            return IntervalTrigger(minutes=minutes)
        case TriggerType.DATE:
            return DateTrigger(run_date=datetime.fromisoformat(value))
    raise ValueError(f"Tipo di trigger sconosciuto: {trigger_type!r}")


def _job_id(schedule_id: int) -> str:
    return f"schedule-{schedule_id}"


class SchedulerService:
    def __init__(
        self,
        session_factory: sessionmaker[Session],
        logs_dir: str | Path = "data/logs",
        max_workers: int = 4,
        launcher: list[str] | None = None,
    ):
        self.session_factory = session_factory
        self.logs_dir = Path(logs_dir)
        self.launcher = launcher  # override di knime.exe (test)
        self.scheduler = BackgroundScheduler(
            job_defaults={"coalesce": True, "max_instances": 1, "misfire_grace_time": 300}
        )
        self.pool = ThreadPoolExecutor(max_workers=max_workers, thread_name_prefix="knime-run")
        self._lock = threading.RLock()
        self._running: dict[int, int] = {}  # run_id -> schedule_id (inviati al pool)
        self._cancel_events: dict[int, threading.Event] = {}
        # chiamate a fine run con (run_id, status): notifiche, aggiornamenti UI
        self.on_run_finished: list[Callable[[int, RunStatus], None]] = []

    # --- ciclo di vita -------------------------------------------------------

    def start(self) -> None:
        with self.session_factory() as s:
            # run rimasti "running" da un arresto precedente: non sappiamo come sono finiti
            for run in s.scalars(select(Run).where(Run.status == RunStatus.RUNNING)):
                run.status = RunStatus.FAILED
                run.finished_at = datetime.now()
                run.error = "Interrotto: il servizio e' stato riavviato durante l'esecuzione"
            s.commit()
            schedules = s.scalars(select(Schedule)).all()
        for schedule in schedules:
            self.sync_schedule(schedule)
        self.scheduler.add_job(
            self.purge_old_runs, CronTrigger(hour=3), id="purge-old-runs", replace_existing=True
        )
        self.scheduler.start()
        for schedule in schedules:
            self._dispatch(schedule.id)  # riprende i run rimasti in coda

    def shutdown(self, cancel_running: bool = False) -> None:
        if self.scheduler.running:
            self.scheduler.shutdown(wait=False)
        if cancel_running:
            for event in list(self._cancel_events.values()):
                event.set()
        self.pool.shutdown(wait=True)

    # --- schedule ------------------------------------------------------------

    def sync_schedule(self, schedule: Schedule) -> None:
        """Da chiamare dopo ogni creazione/modifica di uno Schedule."""
        job_id = _job_id(schedule.id)
        trigger = make_trigger(schedule.trigger_type, schedule.trigger_value)
        expired = isinstance(trigger, DateTrigger) and trigger.run_date < datetime.now(
            trigger.run_date.tzinfo
        )
        if not schedule.active or expired:
            self.remove_schedule(schedule.id)
            return
        self.scheduler.add_job(
            self.trigger_run, trigger, args=[schedule.id], id=job_id, replace_existing=True
        )

    def remove_schedule(self, schedule_id: int) -> None:
        if self.scheduler.get_job(_job_id(schedule_id)):
            self.scheduler.remove_job(_job_id(schedule_id))

    def next_run_time(self, schedule_id: int) -> datetime | None:
        job = self.scheduler.get_job(_job_id(schedule_id))
        return job.next_run_time if job else None

    # --- run -----------------------------------------------------------------

    def trigger_run(self, schedule_id: int, triggered_by: str = "schedule") -> int | None:
        """Accoda un run applicando la politica di concorrenza. None se saltato."""
        with self._lock:
            with self.session_factory() as s:
                schedule = s.get(Schedule, schedule_id)
                if schedule is None:
                    return None
                active = s.scalars(
                    select(Run).where(Run.schedule_id == schedule_id, Run.status.in_(ACTIVE_STATUSES))
                ).all()
                if active and schedule.concurrency == Concurrency.SKIP:
                    log.info("Schedule %s: run saltato, ce n'e' gia' uno attivo", schedule_id)
                    return None
                if active and schedule.concurrency == Concurrency.REPLACE:
                    for run in active:
                        self._cancel(s, run)
                run = Run(schedule_id=schedule_id, triggered_by=triggered_by)
                s.add(run)
                s.commit()
                run_id = run.id
            self._dispatch(schedule_id)
        return run_id

    def cancel_run(self, run_id: int) -> bool:
        with self._lock, self.session_factory() as s:
            run = s.get(Run, run_id)
            if run is None or run.status not in ACTIVE_STATUSES:
                return False
            self._cancel(s, run)
            s.commit()
            return True

    def _cancel(self, s: Session, run: Run) -> None:
        if run.id in self._running:
            self._cancel_events[run.id].set()  # il worker chiude il run come CANCELLED
        else:
            run.status = RunStatus.CANCELLED
            run.finished_at = datetime.now()

    def _dispatch(self, schedule_id: int) -> None:
        """Invia al pool i run in coda che possono partire."""
        with self._lock, self.session_factory() as s:
            schedule = s.get(Schedule, schedule_id)
            if schedule is None:
                return
            queued = s.scalars(
                select(Run)
                .where(Run.schedule_id == schedule_id, Run.status == RunStatus.QUEUED)
                .order_by(Run.id)
            ).all()
            if schedule.concurrency != Concurrency.ALLOW:
                if schedule_id in self._running.values():
                    return
                queued = queued[:1]
            for run in queued:
                run.status = RunStatus.RUNNING
                self._running[run.id] = schedule_id
                self._cancel_events[run.id] = threading.Event()
                self.pool.submit(self._execute, run.id)
            s.commit()

    def _execute(self, run_id: int) -> None:
        status, exit_code, error = RunStatus.FAILED, None, None
        try:
            status, exit_code, error = self._run(run_id)
        except Exception as exc:  # noqa: BLE001 - qualsiasi errore chiude il run come fallito
            log.exception("Run %s: errore inatteso", run_id)
            error = f"Errore interno: {exc}"
        finally:
            with self._lock:
                with self.session_factory() as s:
                    run = s.get(Run, run_id)
                    run.status, run.exit_code, run.error = status, exit_code, error
                    run.finished_at = datetime.now()
                    s.commit()
                schedule_id = self._running.pop(run_id)
                self._cancel_events.pop(run_id)
            self._dispatch(schedule_id)
            for callback in self.on_run_finished:
                try:
                    callback(run_id, status)
                except Exception:  # noqa: BLE001
                    log.exception("Callback on_run_finished fallita per il run %s", run_id)

    def _run(self, run_id: int) -> tuple[RunStatus, int | None, str | None]:
        cancel_event = self._cancel_events[run_id]
        if cancel_event.is_set():
            return RunStatus.CANCELLED, None, None

        with self.session_factory() as s:
            run = s.get(Run, run_id)
            schedule, env, workflow = run.schedule, run.schedule.environment, run.schedule.workflow

            required = [
                Dependency(d.feature_id, d.name, d.vendor, d.version) for d in workflow.dependencies
            ]
            missing = [
                c.dependency for c in check_dependencies(required, installed_features(env.knime_path))
                if c.status == DependencyStatus.MISSING
            ]
            if missing:
                names = ", ".join(d.name or d.feature_id for d in missing)
                return RunStatus.FAILED, None, f"Estensioni mancanti nell'environment '{env.name}': {names}"

            log_path = self.logs_dir / f"run_{run_id}.log"
            run.log_path = str(log_path)
            run.started_at = datetime.now()
            spec = RunSpec(
                knime_path=env.knime_path,
                workflow_file=workflow.file_path,
                variables=schedule.variables,
                credentials=schedule.credentials,
                reset=schedule.reset_before_run,
                preferences_file=env.preferences_file,
                preference_entries=env.preference_entries,
                jvm_args=env.jvm_args,
                env_vars=env.env_vars,
                timeout_seconds=schedule.timeout_minutes * 60 if schedule.timeout_minutes else None,
                launcher=self.launcher,
            )
            s.commit()

        result = run_workflow(spec, log_path, cancel_event=cancel_event)
        if result.cancelled:
            return RunStatus.CANCELLED, result.exit_code, None
        if result.timed_out:
            return RunStatus.TIMEOUT, result.exit_code, f"Superato il timeout di {schedule.timeout_minutes} minuti"
        if result.success:
            return RunStatus.SUCCESS, 0, None
        reason = KNIME_EXIT_CODES.get(result.exit_code, "KNIME terminato con errore")
        return RunStatus.FAILED, result.exit_code, f"{reason} (exit code {result.exit_code})"

    # --- manutenzione --------------------------------------------------------

    def purge_old_runs(self) -> int:
        """Elimina run (e log) piu' vecchi della retention dello schedule."""
        deleted = 0
        with self.session_factory() as s:
            for schedule in s.scalars(select(Schedule).where(Schedule.retention_days.is_not(None))):
                cutoff = datetime.now() - timedelta(days=schedule.retention_days)
                old = s.scalars(
                    select(Run).where(
                        Run.schedule_id == schedule.id,
                        Run.finished_at.is_not(None),
                        Run.finished_at < cutoff,
                    )
                ).all()
                for run in old:
                    if run.log_path:
                        Path(run.log_path).unlink(missing_ok=True)
                    s.delete(run)
                    deleted += 1
            s.commit()
        return deleted
