import io
import sys
import time
import zipfile
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from knime_scheduler.app import create_app

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
    with TestClient(app) as c:
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


# --- pagine ------------------------------------------------------------------

def test_pages_render(client):
    env = create_env(client)
    wf = upload_wf(client, CORE, PYTHON)
    sched = create_schedule(client, env["id"], wf["id"])
    run_id = client.post(f"/api/schedules/{sched['id']}/run").json()["id"]
    wait_finished(client, run_id)
    for url in ["/schedules", "/schedules/new", f"/schedules/{sched['id']}", "/environments",
                "/environments/new", f"/environments/{env['id']}", "/workflows", f"/workflows/{wf['id']}",
                "/runs", "/runs?status=failed", f"/runs/{run_id}"]:
        r = client.get(url)
        assert r.status_code == 200, url
    assert client.get("/", follow_redirects=False).headers["location"] == "/schedules"


def test_dependency_panel_and_request_extension(client):
    env = create_env(client)
    wf = upload_wf(client, CORE, PYTHON)
    html = client.get(f"/dependency-panel?workflow_id={wf['id']}&environment_id={env['id']}").text
    assert "Mancante" in html and "Installata" in html and "Aggiungi all'environment" in html
    html = client.post(f"/environments/{env['id']}/request-extension",
                       data={"feature_id": PYTHON, "workflow_id": str(wf["id"])}).text
    assert "nella lista dell'environment" in html
    assert "non è ancora disponibile" in html
    assert PYTHON in client.get(f"/api/environments/{env['id']}").json()["extensions"]
    assert "Scegli workflow" in client.get("/dependency-panel").text


def test_schedule_form_create_and_errors(client):
    env = create_env(client)
    wf = upload_wf(client, CORE)
    form = {"name": "Da form", "workflow_id": str(wf["id"]), "environment_id": str(env["id"]),
            "trigger_type": "cron", "trigger_value": "sbagliato", "concurrency": "queue", "active": "on",
            "var_name": ["mese", ""], "var_type": ["int", "String"], "var_value": ["10", ""]}
    r = client.post("/schedules/new", data=form, follow_redirects=False)
    assert r.status_code == 422 and "Pianificazione non valida" in r.text and 'value="mese"' in r.text

    form["trigger_value"] = "30 7 * * *"
    r = client.post("/schedules/new", data=form, follow_redirects=False)
    assert r.status_code == 303
    sched = client.get(r.headers["location"].replace("/schedules", "/api/schedules")).json()
    assert sched["concurrency"] == "queue" and sched["variables"] == [{"name": "mese", "type": "int", "value": "10"}]


def test_environment_and_workflow_forms(client):
    r = client.post("/environments/new", data={"name": "Form env", "knime_path": client.knime_path,
                                               "jvm_args": "-Xmx2g\n-Dfoo=1", "env_vars": "senza uguale"})
    assert r.status_code == 422 and "chiave=valore" in r.text
    r = client.post("/environments/new", data={"name": "Form env", "knime_path": client.knime_path,
                                               "jvm_args": "-Xmx2g\n-Dfoo=1", "env_vars": "A=1"},
                    follow_redirects=False)
    assert r.status_code == 303
    assert "org.knime.features.base.feature.group" in client.get(r.headers["location"]).text

    r = client.post("/workflows", files={"file": ("wf.knwf", knwf_bytes(CORE))}, follow_redirects=False)
    assert r.status_code == 303
    wf_url = r.headers["location"]
    html = client.post(f"{wf_url}/dependencies", data={"feature_id": "com.example.x"}).text
    assert "com.example.x.feature.group" in html and "manuale" in html
    assert "Dipendenza gia" in client.post(f"{wf_url}/dependencies", data={"feature_id": "com.example.x"}).text
    r = client.post("/workflows", files={"file": ("wf.txt", b"x")})
    assert r.status_code == 422 and ".knwf" in r.text


def test_run_buttons_and_log_stream(client):
    env = create_env(client)
    wf = upload_wf(client, CORE)
    sched = create_schedule(client, env["id"], wf["id"])
    row = client.post(f"/schedules/{sched['id']}/run").text
    assert f'id="schedule-{sched["id"]}"' in row
    runs = client.post(f"/schedules/{sched['id']}/run", headers={"HX-Target": "runs"}).text
    assert 'id="runs-table"' in runs
    run_id = client.get("/api/runs").json()[0]["id"]
    wait_finished(client, run_id)
    stream = client.get(f"/runs/{run_id}/log/stream").text
    assert "event: line" in stream and "Workflow executed" in stream and stream.endswith("event: done\ndata: \n\n")
    toggled = client.post(f"/schedules/{sched['id']}/toggle").text
    assert "In pausa" in toggled
