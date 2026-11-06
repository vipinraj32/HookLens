"""Report renderers. Every renderer takes the canonical report document from `hooklens.scanner`."""

from __future__ import annotations

import json
import os
import tempfile
from pathlib import Path
from typing import Any

from hooklens.errors import ReportError


def write_text(path: str | Path, content: str) -> Path:
    """Atomic write: a failed run never leaves a truncated report behind."""
    p = Path(path)
    try:
        p.parent.mkdir(parents=True, exist_ok=True)
        fd, tmp = tempfile.mkstemp(prefix=".hooklens-", dir=p.parent)
        try:
            with os.fdopen(fd, "w", encoding="utf-8", newline="\n") as fh:
                fh.write(content)
            os.replace(tmp, p)
        except BaseException:
            Path(tmp).unlink(missing_ok=True)
            raise
    except OSError as e:
        raise ReportError(f"Cannot write report {p}: {e.strerror or e}") from e
    return p


def dumps(report: dict[str, Any]) -> str:
    return json.dumps(report, indent=2, ensure_ascii=False, sort_keys=False) + "\n"


def schema_path() -> Path:
    return Path(__file__).resolve().parent.parent / "schema" / "report-v1.schema.json"


def load_schema() -> dict[str, Any]:
    data: dict[str, Any] = json.loads(schema_path().read_text(encoding="utf-8"))
    return data
