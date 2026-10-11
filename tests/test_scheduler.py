import sys
import time
from datetime import datetime, timedelta
from pathlib import Path

import pytest
from sqlalchemy import create_engine, select
from sqlalchemy.orm import sessionmaker

from knightly.models import (
    Base,
    Concurrency,
    Environment,
    Run,
    RunStatus,
    Schedule,
    Workflow,
    WorkflowDependency,
)
from knightly.scheduler import SchedulerService, make_trigger

FAKE_KNIME = [sys.executable, str(Path(__file__).with_name("fake_knime.py"))]
FINAL = {RunStatus.SUCCESS, RunStatus.FAILED, RunStatus.CANCELLED, RunStatus.TIMEOUT}


@pytest.fixture
def session_factory(tmp_path):
    engine = create_engine(f"sqlite:///{tmp_path / 'test.db'}")
    Base.metadata.create_all(engine)
    return sessionmaker(bind=engine, expire_on_commit=False)


@pytest.fixture
def service(session_factory, tmp_path):
    svc = SchedulerService(session_factory, logs_dir=tmp_path / "logs", launcher=FAKE_KNIME)
    yield svc
    svc.shutdown(cancel_running=True)


def add_schedule(session_factory, tmp_path, mode="ok", deps=(), **kwargs) -> int:
    (tmp_path / "knime" / "features").mkdir(parents=True, exist_ok=True)
    with session_factory() as s:
        env = Environment(name=f"env-{time.monotonic_ns()}", knime_path=str(tmp_path / "knime"))
        wf = Workflow(name="wf", file_path="wf.knwf")
        wf.dependencies = [WorkflowDependency(feature_id=d, name=d) for d in deps]
        sched = Schedule(
            name="test", workflow=wf, environment=env, trigger_value="0 6 * * *",
            variables=[{"name": "mode", "type": "String", "value": mode}], **kwargs,
        )
        s.add(sched)
        s.commit()
        return sched.id


def wait_run(session_factory, run_id, statuses=FINAL, timeout=15) -> Run:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        with session_factory() as s:
            run = s.get(Run, run_id)
            if run.status in statuses:
                return run
        time.sleep(0.1)
    raise AssertionError(f"run {run_id} rimasto in stato {run.status}")


def test_run_success(service, session_factory, tmp_path):
    run_id = service.trigger_run(add_schedule(session_factory, tmp_path), triggered_by="manual")
    run = wait_run(session_factory, run_id)
    assert run.status == RunStatus.SUCCESS and run.exit_code == 0
    assert run.triggered_by == "manual" and run.started_at and run.finished_at
    assert "Workflow executed" in Path(run.log_path).read_text(encoding="utf-8")


def test_run_failure_explains_exit_code(service, session_factory, tmp_path):
    finished = []
    service.on_run_finished.append(lambda rid, st: finished.append((rid, st)))
    run_id = service.trigger_run(add_schedule(session_factory, tmp_path, mode="fail"))
    run = wait_run(session_factory, run_id)
    assert run.status == RunStatus.FAILED and run.exit_code == 4
    assert "esecuzione" in run.error
    assert finished == [(run_id, RunStatus.FAILED)]


def test_missing_dependency_fails_before_launch(service, session_factory, tmp_path):
    sid = add_schedule(session_factory, tmp_path, deps=["com.example.missing.feature.group"])
    run = wait_run(session_factory, service.trigger_run(sid))
    assert run.status == RunStatus.FAILED and run.log_path is None
    assert "com.example.missing.feature.group" in run.error


def test_concurrency_skip(service, session_factory, tmp_path):
    sid = add_schedule(session_factory, tmp_path, mode="sleep", concurrency=Concurrency.SKIP)
    first = service.trigger_run(sid)
    assert service.trigger_run(sid) is None
    service.cancel_run(first)
    assert wait_run(session_factory, first).status == RunStatus.CANCELLED


def test_concurrency_queue_runs_one_at_a_time(service, session_factory, tmp_path):
    sid = add_schedule(session_factory, tmp_path, concurrency=Concurrency.QUEUE)
    ids = [service.trigger_run(sid) for _ in range(3)]
    runs = [wait_run(session_factory, rid) for rid in ids]
    assert all(r.status == RunStatus.SUCCESS for r in runs)
    for prev, nxt in zip(runs, runs[1:]):
        assert prev.finished_at <= nxt.started_at


def test_concurrency_replace_cancels_active(service, session_factory, tmp_path):
    sid = add_schedule(session_factory, tmp_path, mode="sleep", concurrency=Concurrency.REPLACE)
    first = service.trigger_run(sid)
    wait_run(session_factory, first, statuses={RunStatus.RUNNING})
    second = service.trigger_run(sid)
    assert wait_run(session_factory, first).status == RunStatus.CANCELLED
    wait_run(session_factory, second, statuses={RunStatus.RUNNING})
    service.cancel_run(second)


def test_concurrency_allow_runs_in_parallel(service, session_factory, tmp_path):
    sid = add_schedule(session_factory, tmp_path, mode="sleep", concurrency=Concurrency.ALLOW)
    ids = [service.trigger_run(sid) for _ in range(2)]
    for rid in ids:
        wait_run(session_factory, rid, statuses={RunStatus.RUNNING})
    for rid in ids:
        service.cancel_run(rid)
        assert wait_run(session_factory, rid).status == RunStatus.CANCELLED


def test_start_recovers_interrupted_and_queued_runs(session_factory, tmp_path):
    sid = add_schedule(session_factory, tmp_path)
    with session_factory() as s:
        s.add_all([Run(schedule_id=sid, status=RunStatus.RUNNING), Run(schedule_id=sid)])
        s.commit()
    svc = SchedulerService(session_factory, logs_dir=tmp_path / "logs", launcher=FAKE_KNIME)
    svc.start()
    try:
        assert wait_run(session_factory, 1).status == RunStatus.FAILED
        assert wait_run(session_factory, 2).status == RunStatus.SUCCESS
        assert svc.next_run_time(sid) is not None
    finally:
        svc.shutdown()


def test_sync_schedule_inactive_and_expired(service, session_factory, tmp_path):
    sid = add_schedule(session_factory, tmp_path)
    with session_factory() as s:
        sched = s.get(Schedule, sid)
    service.sync_schedule(sched)
    assert service.scheduler.get_job(f"schedule-{sid}")
    sched.active = False
    service.sync_schedule(sched)
    assert service.scheduler.get_job(f"schedule-{sid}") is None
    sched.active, sched.trigger_type = True, "date"
    sched.trigger_value = (datetime.now() - timedelta(hours=1)).isoformat()
    service.sync_schedule(sched)
    assert service.scheduler.get_job(f"schedule-{sid}") is None


def test_purge_old_runs(service, session_factory, tmp_path):
    sid = add_schedule(session_factory, tmp_path, retention_days=7)
    log_file = tmp_path / "old.log"
    log_file.write_text("x")
    with session_factory() as s:
        s.add_all([
            Run(schedule_id=sid, status=RunStatus.SUCCESS, log_path=str(log_file),
                finished_at=datetime.now() - timedelta(days=10)),
            Run(schedule_id=sid, status=RunStatus.SUCCESS, finished_at=datetime.now()),
        ])
        s.commit()
    assert service.purge_old_runs() == 1
    assert not log_file.exists()
    with session_factory() as s:
        assert len(s.scalars(select(Run)).all()) == 1


@pytest.mark.parametrize("ttype, value", [("cron", "0 6 * * 1-5"), ("interval", "30"),
                                          ("date", "2030-01-01T06:00:00")])
def test_make_trigger_valid(ttype, value):
    assert make_trigger(ttype, value)


@pytest.mark.parametrize("expr, expected", [
    ("0 6 * * 1-5", {"Mon", "Tue", "Wed", "Thu", "Fri"}),
    ("0 6 * * 0", {"Sun"}),
    ("0 6 * * 7", {"Sun"}),
    ("0 6 * * 6,0", {"Sat", "Sun"}),
    ("0 6 * * */2", {"Sun", "Tue", "Thu", "Sat"}),
    ("0 6 * * mon-fri", {"Mon", "Tue", "Wed", "Thu", "Fri"}),
    ("0 6 * * *", {"Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"}),
])
def test_cron_day_of_week_follows_standard_crontab(expr, expected):
    trigger = make_trigger("cron", expr)
    now = datetime(2026, 10, 11, 12, 0).astimezone()  # domenica
    days, previous = set(), None
    for _ in range(14):
        previous = trigger.get_next_fire_time(previous, previous or now)
        days.add(previous.strftime("%a"))
        previous += timedelta(minutes=1)
    assert days == expected


@pytest.mark.parametrize("ttype, value", [("cron", "not a cron"), ("cron", "0 6 * * 8"), ("interval", "0"),
                                          ("interval", "abc"), ("date", "domani"), ("boh", "1")])
def test_make_trigger_invalid(ttype, value):
    with pytest.raises(ValueError):
        make_trigger(ttype, value)
