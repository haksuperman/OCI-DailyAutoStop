from __future__ import annotations

import logging
from pathlib import Path

from app.config import LoggingSettings


def configure_logging(settings: LoggingSettings) -> Path:
    settings.directory.mkdir(parents=True, exist_ok=True)
    app_log_file = settings.directory / "autostop_daily.log"

    formatter = logging.Formatter(
        fmt="[%(asctime)s] [%(levelname)s] %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
    )

    root = logging.getLogger()
    root.handlers.clear()
    root.setLevel(settings.level)

    file_handler = logging.FileHandler(app_log_file, mode="w", encoding="utf-8")
    file_handler.setFormatter(formatter)
    root.addHandler(file_handler)

    return app_log_file
