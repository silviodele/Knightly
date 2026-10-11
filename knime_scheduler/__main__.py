"""Riga di comando.

    python -m knime_scheduler [serve] [--host 127.0.0.1] [--port 8000]
    python -m knime_scheduler create-user USERNAME [--role admin|operator|viewer]
    python -m knime_scheduler reset-password USERNAME
"""

import argparse
import getpass
import logging
import os
import sys
from pathlib import Path

from .models import Role


def _data_dir(args) -> Path:
    return Path(args.data_dir or os.environ.get("KNIME_SCHEDULER_DATA", "data"))


def _session_factory(args):
    from .db import make_session_factory

    url = os.environ.get("KNIME_SCHEDULER_DB", f"sqlite:///{(_data_dir(args) / 'knime_scheduler.db').as_posix()}")
    return make_session_factory(url)


def _ask_password() -> str:
    password = getpass.getpass("Password: ")
    if password != getpass.getpass("Ripeti la password: "):
        sys.exit("Le password non coincidono")
    return password


def serve(args) -> None:
    import uvicorn

    from .app import create_app

    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
    app = create_app(data_dir=args.data_dir, max_workers=args.max_workers)
    uvicorn.run(app, host=args.host, port=args.port)


def create_user_cmd(args) -> None:
    from .auth import create_user

    with _session_factory(args)() as s:
        try:
            user = create_user(s, args.username, _ask_password(), Role(args.role), args.full_name)
        except ValueError as exc:
            sys.exit(str(exc))
    print(f"Utente '{user.username}' creato con ruolo {user.role}")


def reset_password_cmd(args) -> None:
    from sqlalchemy import func, select

    from .auth import set_password
    from .models import User

    with _session_factory(args)() as s:
        user = s.scalar(select(User).where(func.lower(User.username) == args.username.lower()))
        if user is None:
            sys.exit(f"Utente '{args.username}' non trovato")
        try:
            set_password(s, user, _ask_password())
        except ValueError as exc:
            sys.exit(str(exc))
        user.active = True
        s.commit()
    print(f"Password di '{args.username}' aggiornata (sessioni aperte chiuse)")


def main() -> None:
    parser = argparse.ArgumentParser(prog="knime-scheduler", description="Scheduler per workflow KNIME")
    parser.add_argument("--data-dir", default=None, help="cartella per database, workflow e log (default: ./data)")
    commands = parser.add_subparsers(dest="command")

    srv = commands.add_parser("serve", help="avvia il server web (default)")
    for p in (parser, srv):
        p.add_argument("--host", default="127.0.0.1")
        p.add_argument("--port", type=int, default=8000)
        p.add_argument("--max-workers", type=int, default=4, help="run KNIME in parallelo al massimo")

    cu = commands.add_parser("create-user", help="crea un utente (chiede la password)")
    cu.add_argument("username")
    cu.add_argument("--role", choices=[r.value for r in Role], default=Role.ADMIN.value)
    cu.add_argument("--full-name", default="")

    rp = commands.add_parser("reset-password", help="reimposta la password di un utente e lo riattiva")
    rp.add_argument("username")

    args = parser.parse_args()
    {"create-user": create_user_cmd, "reset-password": reset_password_cmd}.get(args.command, serve)(args)


if __name__ == "__main__":
    main()
