"""
Structured, redacting logging. All harness logs go through here so numbers and
secrets never land in a log line. Framework request-body debug logging is not
used anywhere (the capture service uses stdlib http.server with logging disabled).
"""
from __future__ import annotations

import json
import logging
import sys

from .sanitize import redact_secrets


class RedactingFormatter(logging.Formatter):
    def format(self, record: logging.LogRecord) -> str:
        msg = redact_secrets(record.getMessage())
        payload = {"level": record.levelname, "logger": record.name, "msg": msg}
        return json.dumps(payload)


def get_logger(name: str = "phase0") -> logging.Logger:
    logger = logging.getLogger(name)
    if not logger.handlers:
        h = logging.StreamHandler(sys.stderr)
        h.setFormatter(RedactingFormatter())
        logger.addHandler(h)
        logger.setLevel(logging.INFO)
        logger.propagate = False
    return logger
