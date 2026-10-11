"""Executor: lancia KNIME in batch mode su una installazione locale.

Exit code del batch executor di KNIME:
    0 = successo, 2 = parametri errati, 3 = errore nel caricamento, 4 = errore in esecuzione
"""

import os
import subprocess
import sys
import tempfile
import threading
import time
from collections.abc import Callable
from dataclasses import dataclass, field
from pathlib import Path

BATCH_APPLICATION = "org.knime.product.KNIME_BATCH_APPLICATION"
VARIABLE_TYPES = {"String", "int", "double"}


@dataclass
class RunSpec:
    """Tutto quello che serve per una esecuzione, gia' risolto da Schedule + Environment."""

    knime_path: str
    workflow_file: str
    variables: list[dict] = field(default_factory=list)    # {"name", "type", "value"}
    credentials: list[dict] = field(default_factory=list)  # {"name", "login", "password"}
    reset: bool = True
    preferences_file: str | None = None
    preference_entries: dict[str, str] = field(default_factory=dict)
    jvm_args: list[str] = field(default_factory=list)
    env_vars: dict[str, str] = field(default_factory=dict)
    timeout_seconds: float | None = None
    # comando al posto di knime.exe (test o launcher non standard), es. ["python", "fake_knime.py"]
    launcher: list[str] | None = None


@dataclass
class RunResult:
    exit_code: int | None
    timed_out: bool = False
    cancelled: bool = False

    @property
    def success(self) -> bool:
        return self.exit_code == 0 and not (self.timed_out or self.cancelled)


def knime_executable(knime_path: str) -> str:
    name = "knime.exe" if sys.platform == "win32" else "knime"
    return str(Path(knime_path) / name)


def write_preferences(spec: RunSpec, directory: str) -> str | None:
    """Unisce file .epf e singole voci in un unico file di preferenze per il run."""
    if not spec.preferences_file and not spec.preference_entries:
        return None
    lines = ["file_export_version=3.0"]
    if spec.preferences_file:
        lines += [
            line for line in Path(spec.preferences_file).read_text(encoding="utf-8").splitlines()
            if line.strip() and not line.startswith("file_export_version")
        ]
    lines += [f"{key}={value}" for key, value in spec.preference_entries.items()]
    path = Path(directory) / "preferences.epf"
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return str(path)


def build_command(spec: RunSpec, preferences_path: str | None = None) -> list[str]:
    cmd = [
        *(spec.launcher or [knime_executable(spec.knime_path)]),
        "-nosplash",
        "-consoleLog",
        "-nosave",
        "-application", BATCH_APPLICATION,
        f"-workflowFile={spec.workflow_file}",
    ]
    if spec.reset:
        cmd.append("-reset")
    if preferences_path:
        cmd.append(f"-preferences={preferences_path}")
    for var in spec.variables:
        if var["type"] not in VARIABLE_TYPES:
            raise ValueError(f"Tipo variabile non supportato: {var['type']!r}")
        cmd.append(f"-workflow.variable={var['name']},{var['value']},{var['type']}")
    for cred in spec.credentials:
        # NB: la password e' visibile nella riga di comando del processo
        cmd.append(f"-credential={cred['name']};{cred.get('login', '')};{cred.get('password', '')}")
    if spec.jvm_args:
        cmd += ["-vmargs", *spec.jvm_args]
    return cmd


def run_workflow(
    spec: RunSpec,
    log_path: str | Path,
    on_line: Callable[[str], None] | None = None,
    cancel_event: threading.Event | None = None,
) -> RunResult:
    """Esegue il workflow, scrive stdout+stderr su log_path e attende la fine.

    on_line viene chiamata per ogni riga di output (per i log in tempo reale).
    """
    with tempfile.TemporaryDirectory(prefix="knime-run-") as tmp:
        cmd = build_command(spec, write_preferences(spec, tmp))
        env = {**os.environ, **spec.env_vars}
        Path(log_path).parent.mkdir(parents=True, exist_ok=True)
        with open(log_path, "w", encoding="utf-8") as log:
            proc = subprocess.Popen(
                cmd,
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
                env=env,
                text=True,
                encoding="utf-8",
                errors="replace",
            )
            finished = threading.Event()
            timed_out = threading.Event()
            deadline = (
                time.monotonic() + spec.timeout_seconds if spec.timeout_seconds is not None else None
            )

            def watchdog() -> None:
                # Termina il processo allo scadere del timeout o se il run viene annullato
                while not finished.wait(0.2):
                    if deadline is not None and time.monotonic() >= deadline:
                        timed_out.set()
                    if timed_out.is_set() or (cancel_event and cancel_event.is_set()):
                        proc.kill()
                        return

            threading.Thread(target=watchdog, daemon=True).start()

            assert proc.stdout is not None
            for line in proc.stdout:
                log.write(line)
                log.flush()
                if on_line:
                    on_line(line.rstrip("\n"))
            proc.wait()
            finished.set()

    return RunResult(
        exit_code=proc.returncode,
        timed_out=timed_out.is_set(),
        cancelled=bool(cancel_event and cancel_event.is_set()),
    )
