import io
import sqlite3
import sys
import time
import zipfile
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from knightly.app import create_app
from knightly.auth import LoginThrottle, create_user, hash_password, verify_password
from knightly.db import make_session_factory
from knightly.models import Role

CSRF = {"X-Knightly-CSRF": "1"}


@pytest.fixture
def app(tmp_path):
    return create_app(data_dir=tmp_path / "data", start_scheduler=False)


def add_users(app):
    with app.state.session_factory() as s:
        for role in Role:
            create_user(s, role.value, f"password-{role.value}", role)


def login(app, username: str) -> TestClient:
    client = TestClient(app, headers=CSRF)
    r = client.post("/api/auth/login", json={"username": username, "password": f"password-{username}"})
    assert r.status_code == 200, r.text
    return client


def test_password_hashing():
    stored = hash_password("segreta-123")
    assert stored.startswith("scrypt$") and "segreta" not in stored
    assert verify_password("segreta-123", stored)
    assert not verify_password("sbagliata", stored)
    assert not verify_password("x", "formato-non-valido")
    assert hash_password("segreta-123") != stored  # salt diverso


def test_first_setup_creates_admin_once(app):
    client = TestClient(app)
    assert client.get("/api/auth/status").json() == {"needs_setup": True, "user": None}
    assert client.post("/api/auth/setup", json={"username": "boss", "password": "password-boss"}).status_code == 403
    r = client.post("/api/auth/setup", json={"username": "boss", "password": "corta"}, headers=CSRF)
    assert r.status_code == 422 and "8 caratteri" in r.json()["detail"]
    r = client.post("/api/auth/setup", json={"username": "boss", "password": "password-boss"}, headers=CSRF)
    assert r.status_code == 201 and r.json()["role"] == "admin"
    status = client.get("/api/auth/status").json()
    assert status["needs_setup"] is False and status["user"]["username"] == "boss"
    again = TestClient(app).post("/api/auth/setup", json={"username": "x", "password": "password-x"}, headers=CSRF)
    assert again.status_code == 409


def test_api_requires_login(app):
    add_users(app)
    client = TestClient(app, headers=CSRF)
    assert client.get("/api/schedules").status_code == 401
    assert client.get("/api/stats").status_code == 401
    assert client.get("/api/runs/1/log/stream").status_code == 401
    assert client.get("/api/auth/status").status_code == 200  # pubblico
    assert client.get("/").status_code in (200, 503)  # la pagina si carica, poi chiede il login


def test_login_errors_and_logout(app):
    add_users(app)
    client = TestClient(app, headers=CSRF)
    bad = client.post("/api/auth/login", json={"username": "admin", "password": "sbagliata"})
    unknown = client.post("/api/auth/login", json={"username": "nessuno", "password": "x"})
    assert bad.status_code == unknown.status_code == 401
    assert bad.json()["detail"] == unknown.json()["detail"]  # non rivela se l'utente esiste

    client = login(app, "ADMIN".lower())
    assert client.get("/api/auth/me").json()["username"] == "admin"
    cookie = client.cookies.get("knightly_session")
    assert client.post("/api/auth/logout").status_code == 204
    reuse = TestClient(app, headers=CSRF, cookies={"knightly_session": cookie})
    assert reuse.get("/api/schedules").status_code == 401  # la sessione e' stata cancellata


def test_username_is_case_insensitive(app):
    add_users(app)
    client = TestClient(app, headers=CSRF)
    assert client.post("/api/auth/login", json={"username": " Admin ", "password": "password-admin"}).status_code == 200


def test_csrf_header_required_for_changes(app):
    add_users(app)
    client = login(app, "operator")
    no_csrf = TestClient(app, cookies={"knightly_session": client.cookies.get("knightly_session")})
    assert no_csrf.get("/api/environments").status_code == 200
    r = no_csrf.post("/api/environments", json={"name": "x", "knime_path": "x"})
    assert r.status_code == 403 and "CSRF" in r.json()["detail"]


def test_roles(app):
    add_users(app)
    viewer, operator, admin = login(app, "viewer"), login(app, "operator"), login(app, "admin")
    env = {"name": "KNIME", "knime_path": "C:/knime"}

    assert viewer.get("/api/schedules").status_code == 200
    assert viewer.post("/api/environments", json=env).status_code == 403
    assert operator.post("/api/environments", json=env).status_code == 201

    assert viewer.get("/api/users").status_code == 403
    assert operator.get("/api/users").status_code == 403
    assert [u["username"] for u in admin.get("/api/users").json()] == ["admin", "operator", "viewer"]


def test_login_throttle(app):
    add_users(app)
    app.state.login_throttle = LoginThrottle(max_failures=3, lock_seconds=60)
    client = TestClient(app, headers=CSRF)
    for _ in range(3):
        assert client.post("/api/auth/login", json={"username": "admin", "password": "no"}).status_code == 401
    blocked = client.post("/api/auth/login", json={"username": "admin", "password": "password-admin"})
    assert blocked.status_code == 429 and "riprova" in blocked.json()["detail"]


def test_user_management(app):
    add_users(app)
    admin = login(app, "admin")
    r = admin.post("/api/users", json={"username": "mario.rossi", "full_name": "Mario Rossi", "role": "operator"})
    assert r.status_code == 422  # password obbligatoria
    r = admin.post("/api/users", json={"username": "mario.rossi", "role": "operator", "password": "password-mario"})
    assert r.status_code == 201
    mario_id = r.json()["id"]
    assert "password" not in r.json() and "password_hash" not in r.json()
    assert admin.post("/api/users", json={"username": "MARIO.ROSSI", "password": "password-mario"}).status_code == 422

    mario = TestClient(app, headers=CSRF)
    assert mario.post("/api/auth/login", json={"username": "mario.rossi", "password": "password-mario"}).status_code == 200

    # disattivato: la sessione aperta smette di funzionare
    r = admin.put(f"/api/users/{mario_id}", json={"username": "mario.rossi", "role": "operator", "active": False})
    assert r.status_code == 200
    assert mario.get("/api/schedules").status_code == 401
    assert admin.delete(f"/api/users/{mario_id}").status_code == 204


def test_last_admin_is_protected(app):
    add_users(app)
    admin = login(app, "admin")
    me = admin.get("/api/auth/me").json()
    assert admin.delete(f"/api/users/{me['id']}").status_code == 422
    r = admin.put(f"/api/users/{me['id']}", json={"username": "admin", "role": "viewer"})
    assert r.status_code == 422 and "amministratore" in r.json()["detail"]


def test_change_own_password(app):
    add_users(app)
    client = login(app, "viewer")
    other_session = login(app, "viewer")
    r = client.post("/api/auth/password", json={"current_password": "sbagliata", "new_password": "nuova-password"})
    assert r.status_code == 422
    r = client.post("/api/auth/password", json={"current_password": "password-viewer", "new_password": "nuova-password"})
    assert r.status_code == 204
    assert client.get("/api/auth/me").status_code == 200  # resta collegato
    assert other_session.get("/api/auth/me").status_code == 401  # le altre sessioni sono chiuse
    fresh = TestClient(app, headers=CSRF)
    assert fresh.post("/api/auth/login", json={"username": "viewer", "password": "nuova-password"}).status_code == 200


def test_manual_run_records_user(tmp_path):
    (tmp_path / "knime" / "features").mkdir(parents=True)
    app = create_app(data_dir=tmp_path / "data", launcher=[sys.executable, str(Path(__file__).with_name("fake_knime.py"))])
    add_users(app)
    with TestClient(app, headers=CSRF) as client:
        client.post("/api/auth/login", json={"username": "operator", "password": "password-operator"})
        env = client.post("/api/environments", json={"name": "E", "knime_path": str(tmp_path / "knime")}).json()
        buf = io.BytesIO()
        zipfile.ZipFile(buf, "w").close()
        wf = client.post("/api/workflows", files={"file": ("w.knwf", buf.getvalue())}).json()
        sched = client.post("/api/schedules", json={"name": "S", "workflow_id": wf["id"], "environment_id": env["id"],
                                                   "trigger_type": "interval", "trigger_value": "60"}).json()
        run = client.post(f"/api/schedules/{sched['id']}/run").json()
        assert run["triggered_by"] == "manual" and run["triggered_by_user"] == "operator"
        for _ in range(100):
            if client.get(f"/api/runs/{run['id']}").json()["status"] not in ("queued", "running"):
                break
            time.sleep(0.1)


def test_missing_columns_are_added(tmp_path):
    """Un database creato prima di triggered_by_user viene aggiornato all'avvio."""
    db = tmp_path / "old.db"
    con = sqlite3.connect(db)
    con.execute("CREATE TABLE runs (id INTEGER PRIMARY KEY, schedule_id INTEGER, status VARCHAR(20), "
                "triggered_by VARCHAR(20), queued_at DATETIME, started_at DATETIME, finished_at DATETIME, "
                "exit_code INTEGER, log_path VARCHAR(500), error TEXT)")
    con.commit()
    con.close()
    make_session_factory(f"sqlite:///{db.as_posix()}")
    columns = [row[1] for row in sqlite3.connect(db).execute("PRAGMA table_info(runs)")]
    assert "triggered_by_user" in columns
