"""Uvicorn entry point: ``python -m src.api.server``."""

from __future__ import annotations

import logging

import uvicorn

from src.api.app import create_app
from src.config import ConfigError, load_config

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)-7s %(name)s: %(message)s",
    datefmt="%H:%M:%S",
)

app = create_app()


def main() -> int:
    import os

    try:
        load_config().validate()
    except ConfigError as exc:
        print(f"Configuration error: {exc}")
        return 2
    port = int(os.getenv("ATLAS_API_PORT", "8000"))
    uvicorn.run("src.api.server:app", host="127.0.0.1", port=port, log_level="info")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
