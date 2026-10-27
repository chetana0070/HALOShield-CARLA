from __future__ import annotations

import logging
from pathlib import Path


class SectionFormatter(logging.Formatter):
    def format(self, record: logging.LogRecord) -> str:
        section = getattr(record, "section", "RUN")
        return f"[{section}] {super().format(record)}"


def configure_logging(log_path: Path | None = None, verbose: bool = False) -> logging.Logger:
    logger = logging.getLogger("haloshield")
    logger.setLevel(logging.DEBUG if verbose else logging.INFO)
    logger.handlers.clear()
    formatter = SectionFormatter("%(asctime)s %(levelname)s %(message)s", "%H:%M:%S")
    stream = logging.StreamHandler()
    stream.setFormatter(formatter)
    logger.addHandler(stream)
    if log_path:
        log_path.parent.mkdir(parents=True, exist_ok=True)
        file_handler = logging.FileHandler(log_path, encoding="utf-8")
        file_handler.setLevel(logging.DEBUG)
        file_handler.setFormatter(formatter)
        logger.addHandler(file_handler)
    return logger


def log(logger: logging.Logger, section: str, message: str, level: int = logging.INFO) -> None:
    logger.log(level, message, extra={"section": section})
