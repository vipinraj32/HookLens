"""Structured JSON logging with correlation IDs and secret redaction."""

from __future__ import annotations

import contextvars
import json
import logging
import re
import sys
from datetime import UTC, datetime
from typing import Any

correlation_id: contextvars.ContextVar[str] = contextvars.ContextVar("correlation_id", default="-")

_SECRET_PATTERNS = [
    re.compile(r"(apikey=)[^&\s\"']+", re.I),
    re.compile(r"(api[_-]?key[\"']?\s*[:=]\s*[\"']?)[^\"'\s,}]+", re.I),
    re.compile(r"(https?://[^/\s]+/(?:v2|v3|rpc)/)[A-Za-z0-9_\-]{16,}", re.I),  # Alchemy/Infura style keys in paths
    re.compile(r"(sk-ant-)[A-Za-z0-9_\-]+"),
    re.compile(r"(Bearer\s+)[A-Za-z0-9._\-]+", re.I),
]
_STD = set(vars(logging.LogRecord("", 0, "", 0, "", (), None)).keys()) | {"message", "asctime"}


def redact(text: str) -> str:
    for p in _SECRET_PATTERNS:
        text = p.sub(lambda m: m.group(1) + "[REDACTED]", text)
    return text


class JsonFormatter(logging.Formatter):
    def format(self, record: logging.LogRecord) -> str:
        out: dict[str, Any] = {
            "ts": datetime.now(UTC).isoformat(),
            "level": record.levelname,
            "logger": record.name,
            "msg": redact(record.getMessage()),
            "correlation_id": correlation_id.get(),
        }
        for k, v in record.__dict__.items():
            if k not in _STD and not k.startswith("_"):
                out[k] = redact(str(v)) if isinstance(v, str) else v
        if record.exc_info:
            out["exc"] = redact(self.formatException(record.exc_info))
        return json.dumps(out, default=str)


def configure_logging(level: str = "INFO") -> None:
    root = logging.getLogger()
    if any(isinstance(h.formatter, JsonFormatter) for h in root.handlers):
        return
    h = logging.StreamHandler(sys.stdout)
    h.setFormatter(JsonFormatter())
    root.handlers = [h]
    root.setLevel(level.upper())
    logging.getLogger("httpx").setLevel("WARNING")
