"""Finto eseguibile KNIME per i test: stampa gli argomenti e simula esiti.

La variabile di flusso "mode" decide il comportamento:
    ok (default) -> exit 0 | fail -> exit 4 | sleep -> dorme 30s
"""

import sys
import time

args = sys.argv[1:]
mode = "ok"
for arg in args:
    print(f"ARG {arg}", flush=True)
    if arg.startswith("-workflow.variable=mode,"):
        mode = arg.split(",")[1]
    if arg.startswith("-preferences="):
        with open(arg.split("=", 1)[1], encoding="utf-8") as f:
            for line in f:
                print(f"PREF {line.rstrip()}", flush=True)

if mode == "fail":
    print("ERROR Execution failed", flush=True)
    sys.exit(4)
if mode == "sleep":
    time.sleep(30)
print("Workflow executed sucessfully.", flush=True)
