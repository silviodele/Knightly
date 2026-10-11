import sys
import threading
import time
from pathlib import Path

import pytest

from knime_scheduler.executor import RunSpec, build_command, run_workflow

FAKE_KNIME = [sys.executable, str(Path(__file__).with_name("fake_knime.py"))]


def make_spec(**kwargs) -> RunSpec:
    return RunSpec(knime_path="C:/knime", workflow_file="C:/wf/test.knwf", launcher=FAKE_KNIME, **kwargs)


def test_build_command_full():
    spec = RunSpec(
        knime_path="/opt/knime",
        workflow_file="/wf/a.knwf",
        variables=[{"name": "anno", "type": "int", "value": "2026"}],
        credentials=[{"name": "db", "login": "user", "password": "pwd"}],
        jvm_args=["-Xmx4g"],
    )
    cmd = build_command(spec, "/tmp/p.epf")
    assert cmd[0].endswith(("knime", "knime.exe"))
    assert "-application" in cmd and "org.knime.product.KNIME_BATCH_APPLICATION" in cmd
    assert "-workflowFile=/wf/a.knwf" in cmd
    assert "-reset" in cmd
    assert "-preferences=/tmp/p.epf" in cmd
    assert "-workflow.variable=anno,2026,int" in cmd
    assert "-credential=db;user;pwd" in cmd
    assert cmd[-2:] == ["-vmargs", "-Xmx4g"]


def test_build_command_rejects_unknown_variable_type():
    with pytest.raises(ValueError):
        build_command(make_spec(variables=[{"name": "x", "type": "Boolean", "value": "1"}]))


def test_run_success_writes_log_and_streams_lines(tmp_path):
    lines = []
    result = run_workflow(make_spec(), tmp_path / "run.log", on_line=lines.append)
    assert result.success and result.exit_code == 0
    assert "Workflow executed sucessfully." in lines
    assert "-workflowFile=C:/wf/test.knwf" in (tmp_path / "run.log").read_text(encoding="utf-8")


def test_run_failure_exit_code(tmp_path):
    result = run_workflow(
        make_spec(variables=[{"name": "mode", "type": "String", "value": "fail"}]), tmp_path / "run.log"
    )
    assert not result.success and result.exit_code == 4


def test_preferences_merged(tmp_path):
    epf = tmp_path / "base.epf"
    epf.write_text("file_export_version=3.0\n/instance/a=1\n", encoding="utf-8")
    lines = []
    run_workflow(
        make_spec(preferences_file=str(epf), preference_entries={"/instance/b": "2"}),
        tmp_path / "run.log",
        on_line=lines.append,
    )
    assert "PREF /instance/a=1" in lines and "PREF /instance/b=2" in lines


def test_timeout_kills_process(tmp_path):
    start = time.monotonic()
    result = run_workflow(
        make_spec(variables=[{"name": "mode", "type": "String", "value": "sleep"}], timeout_seconds=1),
        tmp_path / "run.log",
    )
    assert result.timed_out and not result.success
    assert time.monotonic() - start < 10


def test_cancel_kills_process(tmp_path):
    cancel = threading.Event()
    threading.Timer(1, cancel.set).start()
    result = run_workflow(
        make_spec(variables=[{"name": "mode", "type": "String", "value": "sleep"}]),
        tmp_path / "run.log",
        cancel_event=cancel,
    )
    assert result.cancelled and not result.success
