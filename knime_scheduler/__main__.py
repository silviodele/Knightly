"""Avvio: python -m knime_scheduler [--host 127.0.0.1] [--port 8000]"""

import argparse
import logging

import uvicorn

from .app import create_app


def main() -> None:
    parser = argparse.ArgumentParser(description="knime-scheduler")
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=8000)
    parser.add_argument("--data-dir", default=None, help="cartella per database, workflow e log (default: ./data)")
    parser.add_argument("--max-workers", type=int, default=4, help="run KNIME in parallelo al massimo")
    args = parser.parse_args()

    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
    app = create_app(data_dir=args.data_dir, max_workers=args.max_workers)
    uvicorn.run(app, host=args.host, port=args.port)


if __name__ == "__main__":
    main()
