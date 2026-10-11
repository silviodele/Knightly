import io
import sys
import time
import zipfile
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from knime_scheduler.app import create_app
from knime_scheduler.auth import create_user
from knime_scheduler.models import Role

FAKE_KNIME = [sys.executable, str(Path(__file__).with_name("fake_knime.py"))]
CORE = "org.knime.features.base.feature.group"
PYTHON = "org.knime.features.python3.scripting.feature.group"


def knwf_bytes(*features: str) -> bytes:
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as zf:
        for i, fid in enumerate(features):
            zf.writestr(f"WF/Node (#{i})/settings.xml", f"""<config xmlns="http://www.knime.org/2008/09/XMLConfig">
<entry key="node-feature-name" type="xstring" value="Feature {i}"/>
<entry key="node-feature-symbolic-name" type="xstring" value="{fid}"/>
<entry key="node-feature-version" type="xstring" value="5.3.0"/>
</config>""")
    return buf.getvalue()


@pytest.fixture
def client(tmp_path):
    knime = tmp_path / "knime" / "features"
    knime.mkdir(parents=True)
    (knime / "org.knime.features.base_5.3.1.v2024").mkdir()
    app = create_app(data_dir=tmp_path / "data", launcher=FAKE_KNIME)
    with app.state.session_factory() as s:
        create_user(s, "admin", "password-admin", Role.ADMIN)
    with TestClient(app, headers={"X-KS-CSRF": "1"}) as c:
        assert c.post("/api/auth/login", json={"username": "admin", "password": "password-admin"}).status_code == 200
        c.knime_path = str(tmp_path / "knime")
        yield c


def create_env(client, name="KNIME 5.3"):
    r = client.post("/api/environments", json={"name": name, "knime_path": client.knime_path, "jvm_args": ["-Xmx1g"]})
    assert r.status_code == 201, r.text
    return r.json()


def upload_wf(client, *features):
    r = client.post("/api/workflows", files={"file": ("report.knwf", knwf_bytes(*features))})
    assert r.status_code == 201, r.text
    return r.json()


def create_schedule(client, env_id, wf_id, **extra):
    body = {"name": "Report", "workflow_id": wf_id, "environment_id": env_id,
            "trigger_type": "cron", "trigger_value": "0 6 * * 1-5", **extra}
    r = client.post("/api/schedules", json=body)
    assert r.status_code == 201, r.text
    return r.json()


def wait_finished(client, run_id, timeout=15):
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        run = client.get(f"/api/runs/{run_id}").json()
        if run["status"] not in ("queued", "running"):
            return run
        time.sleep(0.1)
    raise AssertionError("run non terminato")


# --- API ---------------------------------------------------------------------

def test_api_full_flow(client):
    env = create_env(client)
    wf = upload_wf(client, CORE, PYTHON)
    assert {d["feature_id"] for d in wf["dependencies"]} == {CORE, PYTHON}

    sched = create_schedule(client, env["id"], wf["id"],
                            variables=[{"name": "anno", "type": "int", "value": "2026"}],
                            credentials=[{"name": "db", "login": "u", "password": "segreta"}])
    assert sched["next_run_time"] is not None
    assert "password" not in sched["credentials"][0]

    report = client.get(f"/api/schedules/{sched['id']}/dependencies").json()
    assert {d["feature_id"]: d["status"] for d in report} == {CORE: "ok", PYTHON: "missing"}

    # manca l'estensione Python: il run fallisce prima di lanciare KNIME
    run = wait_finished(client, client.post(f"/api/schedules/{sched['id']}/run").json()["id"])
    assert run["status"] == "failed" and "Feature 1" in run["error"]

    # rimossa la dipendenza, il run parte e riceve variabili e credenziali
    python_dep = next(d for d in wf["dependencies"] if d["feature_id"] == PYTHON)
    client.delete(f"/api/workflows/{wf['id']}/dependencies/{python_dep['id']}")
    run = wait_finished(client, client.post(f"/api/schedules/{sched['id']}/run").json()["id"])
    assert run["status"] == "success" and run["exit_code"] == 0
    log = client.get(f"/api/runs/{run['id']}/log").text
    assert "-workflow.variable=anno,2026,int" in log and "-credential=db;u;segreta" in log
    assert [r["id"] for r in client.get(f"/api/runs?schedule_id={sched['id']}").json()][0] == run["id"]


def test_api_validation_errors(client):
    env = create_env(client)
    assert client.post("/api/environments", json={"name": "KNIME 5.3", "knime_path": "x"}).status_code == 422
    wf = upload_wf(client, CORE)
    bad = client.post("/api/schedules", json={"name": "x", "workflow_id": wf["id"], "environment_id": env["id"],
                                              "trigger_type": "cron", "trigger_value": "non valido"})
    assert bad.status_code == 422 and "Pianificazione" in bad.json()["detail"]
    bad_var = client.post("/api/schedules", json={"name": "x", "workflow_id": wf["id"], "environment_id": env["id"],
                                                  "trigger_value": "5", "trigger_type": "interval",
                                                  "variables": [{"name": "n", "type": "int", "value": "abc"}]})
    assert bad_var.status_code == 422
    not_zip = client.post("/api/workflows", files={"file": ("x.knwf", b"not a zip")})
    assert not_zip.status_code == 422


def test_api_update_keeps_password_and_delete_rules(client):
    env = create_env(client)
    wf = upload_wf(client, CORE)
    sched = create_schedule(client, env["id"], wf["id"],
                            credentials=[{"name": "db", "login": "u", "password": "segreta"}])
    r = client.put(f"/api/schedules/{sched['id']}", json={
        "name": "Rinominato", "workflow_id": wf["id"], "environment_id": env["id"],
        "trigger_type": "interval", "trigger_value": "15", "active": False,
        "credentials": [{"name": "db", "login": "u2", "password": ""}]})
    assert r.status_code == 200 and r.json()["next_run_time"] is None
    run = wait_finished(client, client.post(f"/api/schedules/{sched['id']}/run").json()["id"])
    assert "-credential=db;u2;segreta" in client.get(f"/api/runs/{run['id']}/log").text

    assert client.delete(f"/api/environments/{env['id']}").status_code == 422  # usato da uno schedule
    assert client.delete(f"/api/schedules/{sched['id']}").status_code == 204
    assert client.delete(f"/api/environments/{env['id']}").status_code == 204


def test_replacing_workflow_file_keeps_manual_dependencies(client):
    wf = upload_wf(client, CORE)
    client.post(f"/api/workflows/{wf['id']}/dependencies", json={"feature_id": "com.example.extra"})
    r = client.put(f"/api/workflows/{wf['id']}/file", files={"file": ("v2.knwf", knwf_bytes(PYTHON))})
    deps = {d["feature_id"]: d["source"] for d in r.json()["dependencies"]}
    assert deps == {"com.example.extra.feature.group": "manual", PYTHON: "detected"}


# --- endpoint per l'interfaccia ----------------------------------------------

def test_schedule_list_has_last_run_and_missing_dependencies(client):
    env = create_env(client)
    wf = upload_wf(client, CORE, PYTHON)
    sched = create_schedule(client, env["id"], wf["id"])
    run = wait_finished(client, client.post(f"/api/schedules/{sched['id']}/run").json()["id"])
    [item] = client.get("/api/schedules").json()
    assert item["workflow_name"] == "report" and item["environment_name"] == "KNIME 5.3"
    assert item["missing_dependencies"] == 1
    assert item["last_run"]["id"] == run["id"] and item["last_run"]["schedule_name"] == "Report"


def test_pause_and_resume(client):
    env = create_env(client)
    wf = upload_wf(client, CORE)
    sched = create_schedule(client, env["id"], wf["id"])
    paused = client.patch(f"/api/schedules/{sched['id']}/active", json={"active": False}).json()
    assert paused["active"] is False and paused["next_run_time"] is None
    resumed = client.patch(f"/api/schedules/{sched['id']}/active", json={"active": True}).json()
    assert resumed["next_run_time"] is not None


def test_dependency_check_and_request_extension(client):
    env = create_env(client)
    wf = upload_wf(client, CORE, PYTHON)
    report = client.get(f"/api/dependency-check?workflow_id={wf['id']}&environment_id={env['id']}").json()
    assert {d["feature_id"]: (d["status"], d["requested"]) for d in report} == {
        CORE: ("ok", False), PYTHON: ("missing", False)}
    r = client.post(f"/api/environments/{env['id']}/extensions", json={"feature_id": PYTHON})
    assert PYTHON in r.json()["extensions"]
    report = client.get(f"/api/dependency-check?workflow_id={wf['id']}&environment_id={env['id']}").json()
    assert next(d for d in report if d["feature_id"] == PYTHON)["requested"] is True


def test_trigger_preview(client):
    ok = client.get("/api/triggers/preview", params={"trigger_type": "cron", "trigger_value": "0 6 * * 1-5"}).json()
    assert ok["valid"] and len(ok["next_runs"]) == 5
    bad = client.get("/api/triggers/preview", params={"trigger_type": "cron", "trigger_value": "x"}).json()
    assert not bad["valid"] and bad["error"]


def test_stats(client):
    env = create_env(client)
    wf = upload_wf(client, CORE, PYTHON)  # Python mancante: il run fallisce
    sched = create_schedule(client, env["id"], wf["id"])
    wait_finished(client, client.post(f"/api/schedules/{sched['id']}/run").json()["id"])
    stats = client.get("/api/stats").json()
    assert stats["schedules_total"] == 1 and stats["schedules_active"] == 1
    assert stats["runs_today"] == 1 and stats["failed_24h"] == 1 and stats["success_rate_7d"] == 0
    assert len(stats["daily"]) == 14 and stats["daily"][-1]["failed"] == 1
    assert stats["upcoming"][0]["schedule_name"] == "Report"
    assert stats["recent_failures"][0]["schedule_name"] == "Report"


def test_log_stream(client):
    env = create_env(client)
    wf = upload_wf(client, CORE)
    sched = create_schedule(client, env["id"], wf["id"])
    run = wait_finished(client, client.post(f"/api/schedules/{sched['id']}/run").json()["id"])
    stream = client.get(f"/api/runs/{run['id']}/log/stream").text
    assert 'event: line' + chr(10) + 'data: "Workflow executed sucessfully."' in stream
    assert stream.endswith('event: done' + chr(10) + 'data: "success"' + chr(10) * 2)


def test_spa_fallback(client):
    r = client.get("/schedules/3")
    assert r.status_code in (200, 503)  # 200 se il frontend e' compilato, altrimenti istruzioni
    assert client.get("/api/non-esiste").status_code == 404
